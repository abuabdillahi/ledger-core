"""The whole event stream, against the verified expected output.

Section references are to the brief. Where a figure here disagrees with the
implementation, the implementation is wrong.
"""

import pytest

from ledger.auth import AuthState
from ledger.entries import EntryType
from ledger.fees import assessment_basis, standing_fee
from ledger.journal import DecisionType
from ledger.money import Money
from ledger.projections import Basis, available_balance, balance
from ledger.replay import EVENT_STREAM, replay
from ledger.report import render

FULL_STREAM = len(EVENT_STREAM)
THROUGH_E7 = 7  # E1..E7: after the back-value, before the reversal
THROUGH_E8 = 8


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


def bhd(literal: str) -> Money:
    return Money.from_major(literal, "BHD")


@pytest.fixture(scope="module")
def final():
    return replay()


@pytest.fixture(scope="module")
def final_without_interest():
    return replay(capitalise_interest=False)


@pytest.fixture(scope="module")
def after_e7():
    """The intermediate state: E7 has landed, E9 has not."""
    return replay(EVENT_STREAM[:THROUGH_E7], capitalise_interest=False)


# -- 4.1 final closing balances ---------------------------------------------


def test_acc_001_final_closing_balances(final_without_interest):
    journal = final_without_interest.journal
    assert [str(balance(journal, "ACC-001", day)) for day in range(1, 7)] == [
        "250.00 AED",
        "250.00 AED",
        "650.00 AED",
        "465.00 AED",
        "465.00 AED",
        "465.00 AED",  # before interest capitalisation
    ]


def test_no_fee_stands_against_acc_001_at_the_end(final):
    for day in range(1, 7):
        assert standing_fee(final.journal, "ACC-001", day) is None


# -- 4.2 the intermediate state, after E7 and before E9 ----------------------


def test_assessment_bases_after_e7(after_e7):
    """The Day-by-day figures the fee decision is taken on."""
    assert [
        str(assessment_basis(after_e7.journal, "ACC-001", day)) for day in range(1, 6)
    ] == [
        "250.00 AED",
        "-370.00 AED",
        "5.00 AED",
        "-180.00 AED",
        "-205.00 AED",
    ]


def test_three_fees_on_days_two_four_and_five(after_e7):
    assessed = [
        day for day in range(1, 7)
        if standing_fee(after_e7.journal, "ACC-001", day) is not None
    ]
    assert assessed == [2, 4, 5]


def test_day_three_escapes_because_of_the_credit_less_the_day_two_fee(after_e7):
    # 30.00 less the Day 2 fee of 25.00, which is value-dated to Day 2 and so
    # propagates forward like any other back-valued entry.
    assert balance(after_e7.journal, "ACC-001", 3) == aed("5.00")


def test_closing_balances_include_each_days_own_fee(after_e7):
    """The assessment basis and the closing balance are not the same figure."""
    assert [
        str(balance(after_e7.journal, "ACC-001", day)) for day in range(1, 7)
    ] == [
        "250.00 AED",
        "-395.00 AED",  # -370.00 less its own fee
        "5.00 AED",
        "-205.00 AED",  # -180.00 less its own fee
        "-230.00 AED",  # -205.00 less its own fee
        "-230.00 AED",
    ]


def test_fee_assessment_is_event_triggered_not_time_triggered(after_e7):
    """AMBIGUITIES item 18, surfaced by this truncated replay.

    Day 6 closes at -230.00 here and carries no fee, because no event after E7
    ever prompts a reconciliation covering it. On the full ten-event stream the
    question is invisible -- E10 triggers a reconciliation across the whole
    window -- but a real core banking system would assess this day from the
    clock, as end-of-day batch work.
    """
    assert balance(after_e7.journal, "ACC-001", 6) == aed("-230.00")
    assert standing_fee(after_e7.journal, "ACC-001", 6) is None


def test_the_reversal_restores_every_day_not_just_the_last(
    final_without_interest, after_e7
):
    """Every day closes positive again, and Day 2 returns to 250.00."""
    restored = final_without_interest.journal
    for day in range(1, 7):
        assert not balance(restored, "ACC-001", day).is_negative
    assert balance(restored, "ACC-001", 2) == aed("250.00")
    assert balance(after_e7.journal, "ACC-001", 2) == aed("-395.00")


def test_fees_are_reversed_by_appended_entries_not_deletions(final):
    entry_types = [entry.entry_type for entry in final.journal]
    assert entry_types.count(EntryType.OVERDRAFT_FEE) == 3
    assert entry_types.count(EntryType.FEE_REVERSAL) == 3
    # The fees are still in the journal. Nothing was removed.
    fees = [e for e in final.journal if e.entry_type is EntryType.OVERDRAFT_FEE]
    assert sorted(entry.value_date for entry in fees) == [2, 4, 5]
    reversals = [e for e in final.journal if e.entry_type is EntryType.FEE_REVERSAL]
    assert sorted(entry.value_date for entry in reversals) == [2, 4, 5]
    assert all(entry.booking_day == 6 for entry in reversals)


# -- 4.3 ACC-002 -------------------------------------------------------------


def test_acc_002_closing_balances(final_without_interest):
    journal = final_without_interest.journal
    assert [str(balance(journal, "ACC-002", day)) for day in range(1, 7)] == [
        "0.000 BHD",
        "0.000 BHD",
        "0.000 BHD",
        "0.000 BHD",
        "10.000 BHD",
        "10.000 BHD",  # before interest capitalisation
    ]


def test_e10_splits_by_largest_remainder(final):
    instalments = [
        entry
        for entry in final.journal
        if entry.account_id == "ACC-002" and entry.entry_type is EntryType.CREDIT
    ]
    assert [str(entry.amount) for entry in instalments] == [
        "3.334 BHD",
        "3.333 BHD",
        "3.333 BHD",
    ]
    assert sum(entry.amount.minor_units for entry in instalments) == 10_000


# -- 4.4 interest ------------------------------------------------------------


def test_interest_capitalisation_totals(final):
    totals = {c.account_id: str(c.total) for c in final.capitalisations}
    assert totals == {"ACC-001": "1.03 AED", "ACC-002": "0.008 BHD"}


def test_final_balances_after_capitalisation(final):
    assert balance(final.journal, "ACC-001", 6) == aed("466.03")
    assert balance(final.journal, "ACC-002", 6) == bhd("10.008")


def test_pre_capitalisation_balance_and_credit_are_reported_separately(final):
    output = render(final)
    assert "Day 6 closing, before capitalisation     465.00 AED" in output
    assert "interest capitalised                      1.03 AED" in output
    assert "Day 6 closing, after capitalisation      466.03 AED" in output


# -- 4.5 authorisations ------------------------------------------------------


def test_auth_a_settles_and_releases_its_residual(final):
    log = final.auth_log
    assert log.state_of("Auth-A") is AuthState.SETTLED
    assert log.active_holds("ACC-001", 3) == aed("200.00")
    assert log.active_holds("ACC-001", 4) == aed("0.00")
    assert "residual 15.00 AED released" in log.history("Auth-A")[-1].note


def test_auth_z_moves_no_money(final):
    posted = [entry.origin_ref for entry in final.journal]
    assert not any("Auth-Z" in ref for ref in posted)
    assert not any("E6" in ref for ref in posted)


def test_auth_b_is_declined(final):
    assert final.auth_log.state_of("Auth-B") is AuthState.DECLINED
    assert final.auth_log.active_holds("ACC-001", 5) == aed("0.00")


def test_auth_b_would_be_declined_under_either_fee_timing(after_e7):
    """The decline does not depend on resolving AMBIGUITIES item 1."""
    journal = after_e7.journal
    with_fees = available_balance(journal, after_e7.auth_log, "ACC-001", 5)
    assert with_fees == aed("-230.00")
    without_fees = assessment_basis(journal, "ACC-001", 5) + aed("50.00")
    assert without_fees == aed("-155.00")  # -205.00 plus the two earlier fees
    assert (with_fees - aed("90.00")).is_negative
    assert (without_fees - aed("90.00")).is_negative


# -- 4.6 errors --------------------------------------------------------------


def test_both_rejections_are_recorded_durably(final):
    decisions = final.journal.decisions
    assert [d.event_id for d in decisions] == ["E6", "E8"]
    assert decisions[0].decision is DecisionType.SETTLEMENT_REJECTED
    assert "Auth-Z" in decisions[0].reason
    assert decisions[1].decision is DecisionType.AUTHORIZATION_DECLINED
    assert "insufficient available balance" in decisions[1].reason


# -- structural guarantees ---------------------------------------------------


def test_both_bases_disagree_on_day_five_and_agree_by_day_six(final):
    journal = final.journal
    assert balance(journal, "ACC-001", 5, Basis.VALUE) == aed("465.00")
    assert balance(journal, "ACC-001", 5, Basis.POSTING) == aed("-230.00")
    assert balance(journal, "ACC-001", 6, Basis.VALUE) == balance(
        journal, "ACC-001", 6, Basis.POSTING
    )


def test_sequence_numbers_are_unbroken_across_both_logs(final):
    sequences = sorted(
        [entry.sequence for entry in final.journal]
        + [record.sequence for record in final.journal.decisions]
    )
    assert sequences == list(range(1, len(sequences) + 1))


def test_entries_are_immutable(final):
    entry = final.journal.entries[0]
    with pytest.raises(Exception):
        entry.amount = aed("1.00")  # type: ignore[misc]


def test_replay_is_deterministic():
    first = [str(entry) for entry in replay().journal]
    for _ in range(5):
        assert [str(entry) for entry in replay().journal] == first


def test_the_report_prints_authorisation_state_on_days_nothing_changed(final):
    """The brief asks for authorisation states per day, not just transitions."""
    output = render(final)
    day_three = output.split("Day 3\n")[1].split("Day 4\n")[0]
    # Auth-A neither opened nor closed on Day 3, but it held 200.00 all day.
    assert "Auth-A (ACC-001)  APPROVED    hold     200.00 AED" in day_three
    assert "authorisation changes today" not in day_three

    day_six = output.split("Day 6\n")[1]
    assert "Auth-A (ACC-001)  SETTLED" in day_six
    assert "Auth-B (ACC-001)  DECLINED" in day_six


def test_the_report_renders(final):
    output = render(final)
    for expected in (
        "unknown authorisation reference Auth-Z",
        "Auth-B: DECLINED",
        "Auth-A: SETTLED",
        "3.334 BHD",
        "1.03 AED",
    ):
        assert expected in output
