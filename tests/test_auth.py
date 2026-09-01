"""Authorisation lifecycle: approval, decline, partial settlement, expiry."""

from ledger.auth import (
    EXPIRY_WINDOW_DAYS,
    AuthorizationLog,
    AuthState,
    decide_settlement,
    expire_stale_authorizations,
    request_authorization,
)
from ledger.entries import Direction, EntryType
from ledger.events import Authorization, Settlement
from ledger.journal import DecisionType, Journal
from ledger.money import Money
from ledger.projections import available_balance, balance


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


def funded_journal(amount: str = "250.00") -> Journal:
    journal = Journal()
    journal.append(
        booking_day=1,
        value_date=1,
        account_id="ACC-001",
        direction=Direction.CREDIT,
        amount=aed(amount),
        entry_type=EntryType.CREDIT,
        origin_ref="opening",
    )
    return journal


def auth_a(amount: str = "200.00") -> Authorization:
    return Authorization(
        event_id="E3",
        booking_day=2,
        value_date=2,
        account_id="ACC-001",
        auth_ref="Auth-A",
        amount=aed(amount),
    )


def test_auth_a_is_approved():
    journal, log = funded_journal(), AuthorizationLog()
    transition = request_authorization(journal, log, auth_a())

    assert transition.state is AuthState.APPROVED
    assert log.state_of("Auth-A") is AuthState.APPROVED
    # 250.00 available, 200.00 held, 50.00 left. At or above zero, so approved.
    assert available_balance(journal, log, "ACC-001", 2) == aed("50.00")


def test_a_hold_reduces_available_balance_but_not_ledger_balance():
    """The brief's acceptance criterion 5 says a hold reduces available balance
    but not ledger balance. True by construction in this model: holds append no
    entry, and available balance is ledger balance minus active holds."""
    journal, log = funded_journal(), AuthorizationLog()
    request_authorization(journal, log, auth_a())

    assert balance(journal, "ACC-001", 2) == aed("250.00")
    assert available_balance(journal, log, "ACC-001", 2) == aed("50.00")
    assert len(journal) == 1  # the hold appended no entry


def test_exactly_zero_available_is_approved():
    # "at or above zero" is inclusive; a customer may spend to the last fils.
    journal, log = funded_journal(), AuthorizationLog()
    assert (
        request_authorization(journal, log, auth_a("250.00")).state
        is AuthState.APPROVED
    )
    assert available_balance(journal, log, "ACC-001", 2) == aed("0.00")


def test_one_fils_beyond_is_declined():
    journal, log = funded_journal(), AuthorizationLog()
    assert (
        request_authorization(journal, log, auth_a("250.01")).state
        is AuthState.DECLINED
    )


def test_auth_b_is_declined_on_an_overdrawn_account():
    """E8. Declined under either fee-timing reading, so the outcome is robust."""
    for ledger_balance in ("-155.00", "-230.00"):
        journal, log = Journal(), AuthorizationLog()
        journal.append(
            booking_day=1, value_date=1, account_id="ACC-001",
            direction=Direction.DEBIT, amount=aed(ledger_balance.lstrip("-")),
            entry_type=EntryType.DEBIT, origin_ref="setup",
        )
        event = Authorization(
            event_id="E8", booking_day=5, value_date=5, account_id="ACC-001",
            auth_ref="Auth-B", amount=aed("90.00"),
        )
        assert request_authorization(journal, log, event).state is AuthState.DECLINED

        decisions = journal.decisions
        assert len(decisions) == 1
        assert decisions[0].decision is DecisionType.AUTHORIZATION_DECLINED
        assert decisions[0].subject == "Auth-B"
        # A decline is a durable record, not a dropped message.
        assert "insufficient available balance" in decisions[0].reason


def test_declined_authorisation_holds_nothing():
    journal, log = Journal(), AuthorizationLog()
    event = Authorization(
        event_id="E8", booking_day=5, value_date=5, account_id="ACC-001",
        auth_ref="Auth-B", amount=aed("90.00"),
    )
    request_authorization(journal, log, event)
    assert log.active_holds("ACC-001", 5) == aed("0.00")


def test_partial_settlement_releases_the_residual_immediately():
    journal, log = funded_journal(), AuthorizationLog()
    request_authorization(journal, log, auth_a())
    assert log.active_holds("ACC-001", 3) == aed("200.00")

    settlement = Settlement(
        event_id="E5", booking_day=4, value_date=4, account_id="ACC-001",
        auth_ref="Auth-A", amount=aed("185.00"),
    )
    assert decide_settlement(journal, log, settlement) is True

    assert log.state_of("Auth-A") is AuthState.SETTLED
    assert log.active_holds("ACC-001", 4) == aed("0.00")  # 15.00 residual gone
    assert "residual 15.00 AED released" in log.history("Auth-A")[-1].note
    # ... and the hold was still in force on Day 3, which is a different day.
    assert log.active_holds("ACC-001", 3) == aed("200.00")


def test_settlement_with_no_matching_authorisation_is_rejected():
    """E6. No funds leave the account; the rejection is recorded durably."""
    journal, log = funded_journal(), AuthorizationLog()
    settlement = Settlement(
        event_id="E6", booking_day=4, value_date=4, account_id="ACC-001",
        auth_ref="Auth-Z", amount=aed("180.00"),
    )

    assert decide_settlement(journal, log, settlement) is False
    assert balance(journal, "ACC-001", 6) == aed("250.00")  # untouched
    assert len(journal) == 1

    record = journal.decisions[-1]
    assert record.decision is DecisionType.SETTLEMENT_REJECTED
    assert record.subject == "Auth-Z"
    assert record.event_id == "E6"


def test_an_authorisation_cannot_settle_twice():
    journal, log = funded_journal(), AuthorizationLog()
    request_authorization(journal, log, auth_a())
    settlement = Settlement(
        event_id="E5", booking_day=4, value_date=4, account_id="ACC-001",
        auth_ref="Auth-A", amount=aed("185.00"),
    )
    assert decide_settlement(journal, log, settlement) is True
    assert decide_settlement(journal, log, settlement) is False
    assert journal.decisions[-1].decision is DecisionType.SETTLEMENT_REJECTED


def test_state_is_derived_by_folding_not_stored():
    journal, log = funded_journal(), AuthorizationLog()
    request_authorization(journal, log, auth_a())
    decide_settlement(
        journal,
        log,
        Settlement(
            event_id="E5", booking_day=4, value_date=4, account_id="ACC-001",
            auth_ref="Auth-A", amount=aed("185.00"),
        ),
    )
    history = log.history("Auth-A")
    assert [t.state for t in history] == [AuthState.APPROVED, AuthState.SETTLED]
    assert log.state_of("Auth-A") is history[-1].state
    # The whole life of the authorisation is readable, not just its end state.
    assert [str(t.hold) for t in history] == ["200.00 AED", "0.00 AED"]


def test_expiry_releases_an_unsettled_hold():
    journal, log = funded_journal("1000.00"), AuthorizationLog()
    request_authorization(journal, log, auth_a())

    day_before = 2 + EXPIRY_WINDOW_DAYS - 1
    assert expire_stale_authorizations(log, day_before) == []
    assert log.active_holds("ACC-001", day_before) == aed("200.00")

    expired = expire_stale_authorizations(log, 2 + EXPIRY_WINDOW_DAYS)
    assert [t.state for t in expired] == [AuthState.EXPIRED]
    assert log.active_holds("ACC-001", 2 + EXPIRY_WINDOW_DAYS) == aed("0.00")
    assert len(journal) == 1  # expiry moves no money


def test_nothing_expires_inside_the_six_day_window():
    """NUMBERS.md: the 7-day window does not bind on this dataset."""
    journal, log = funded_journal(), AuthorizationLog()
    request_authorization(journal, log, auth_a())
    for day in range(2, 7):
        assert expire_stale_authorizations(log, day) == []
