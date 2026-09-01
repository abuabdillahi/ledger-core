"""Authorisations: holds, decisions, and the lifecycle they move through.

An authorisation is not a ledger entry. It moves no money, so it has no
business in the book of record. What it does is suppress *available* balance
until it either settles, is released, or expires.

It still needs an append-only history. State is never a mutable field on an
authorisation object; it is derived by folding the transition log, exactly as a
balance is derived by folding the journal. Asking "what state is Auth-A in?"
means reading its history, so the answer always comes with its own audit trail.

Decision logic lives here; the durable record of a decision lives in the
journal (see ``journal.DecisionRecord``). Rejecting a settlement and declining
an authorisation are both authorisation-domain judgements, so the rules belong
in this module -- but the resulting audit artefact must not be buried in a
domain module's private state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator

from ledger.events import Authorization, Settlement
from ledger.journal import DecisionType, Journal
from ledger.money import Money, currency_of
from ledger.projections import available_balance

#: Days an approved-but-unsettled hold survives before it is released. See
#: NUMBERS.md; it does not bind on this dataset and is load-bearing anyway.
EXPIRY_WINDOW_DAYS = 7


class AuthState(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    #: Reached only by incremental settlement, which this scope has no event
    #: for: a settlement below the authorised amount releases its residual
    #: immediately and terminates as SETTLED (AMBIGUITIES item 9).
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    SETTLED = "SETTLED"
    #: Merchant-initiated release before settlement. No event represents it
    #: here; modelled because a hold with no release path is a hold forever.
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    #: Cancellation by the merchant before settlement. As RELEASED: modelled,
    #: not reachable from this event stream.
    VOIDED = "VOIDED"


@dataclass(frozen=True, slots=True)
class AuthTransition:
    """One step in an authorisation's life. Immutable, like everything else."""

    sequence: int
    day: int
    auth_ref: str
    account_id: str
    state: AuthState
    #: The hold in force *after* this transition. Zero once it ends.
    hold: Money
    note: str

    def __str__(self) -> str:
        return (
            f"day {self.day} {self.auth_ref} -> {self.state} "
            f"(hold {self.hold}): {self.note}"
        )


class AuthorizationLog:
    """Append-only history of every authorisation transition.

    Satisfies ``projections.HoldRegistry``, which is how holds reach the
    available-balance calculation without balances depending on this module.
    """

    __slots__ = ("_transitions", "_next_sequence")

    def __init__(self) -> None:
        self._transitions: list[AuthTransition] = []
        self._next_sequence = 1

    def append(
        self,
        *,
        day: int,
        auth_ref: str,
        account_id: str,
        state: AuthState,
        hold: Money,
        note: str,
    ) -> AuthTransition:
        transition = AuthTransition(
            sequence=self._next_sequence,
            day=day,
            auth_ref=auth_ref,
            account_id=account_id,
            state=state,
            hold=hold,
            note=note,
        )
        self._next_sequence += 1
        self._transitions.append(transition)
        return transition

    @property
    def transitions(self) -> tuple[AuthTransition, ...]:
        return tuple(self._transitions)

    def __iter__(self) -> Iterator[AuthTransition]:
        return iter(tuple(self._transitions))

    def history(self, auth_ref: str) -> tuple[AuthTransition, ...]:
        return tuple(t for t in self._transitions if t.auth_ref == auth_ref)

    def references(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for transition in self._transitions:
            seen.setdefault(transition.auth_ref, None)
        return tuple(seen)

    def knows(self, auth_ref: str) -> bool:
        return any(t.auth_ref == auth_ref for t in self._transitions)

    def state_of(self, auth_ref: str) -> AuthState | None:
        """Current state, by folding the history. Never a stored field."""
        history = self.history(auth_ref)
        return history[-1].state if history else None

    def state_on(self, auth_ref: str, day: int) -> AuthState | None:
        """State as at end of ``day``, by folding the history up to that day.

        Distinct from :meth:`state_of`, which folds the whole history. Auth-A is
        APPROVED on Day 3 and SETTLED on Day 4, and a report that only ever
        shows the final state cannot say what was true on Day 3.
        """
        applicable = [t for t in self.history(auth_ref) if t.day <= day]
        return applicable[-1].state if applicable else None

    def known_on(self, day: int) -> tuple[str, ...]:
        """Every authorisation the ledger had heard of by end of ``day``."""
        return tuple(
            auth_ref
            for auth_ref in self.references()
            if self.history(auth_ref)[0].day <= day
        )

    def hold_for(self, auth_ref: str, day: int) -> Money | None:
        """The hold in force for one authorisation at end of ``day``."""
        applicable = [t for t in self.history(auth_ref) if t.day <= day]
        return applicable[-1].hold if applicable else None

    def active_holds(self, account_id: str, day: int) -> Money:
        """Total holds suppressing ``account_id``'s available balance on ``day``."""
        total = Money.zero(currency_of(account_id))
        for auth_ref in self.references():
            history = self.history(auth_ref)
            if history[0].account_id != account_id:
                continue
            hold = self.hold_for(auth_ref, day)
            if hold is not None:
                total = total + hold
        return total


def request_authorization(
    journal: Journal, log: AuthorizationLog, event: Authorization
) -> AuthTransition:
    """Approve or decline a hold request.

    Approved only if available balance remains at or above zero *after* the
    hold is applied. Zero is approvable: the rule is "at or above".
    """
    day = event.booking_day
    available = available_balance(journal, log, event.account_id, day)
    remaining = available - event.amount

    if remaining.is_negative:
        journal.record_decision(
            booking_day=day,
            account_id=event.account_id,
            decision=DecisionType.AUTHORIZATION_DECLINED,
            event_id=event.event_id,
            subject=event.auth_ref,
            reason=(
                f"insufficient available balance: {available} available, "
                f"{event.amount} requested"
            ),
        )
        return log.append(
            day=day,
            auth_ref=event.auth_ref,
            account_id=event.account_id,
            state=AuthState.DECLINED,
            hold=Money.zero(event.amount.currency),
            note=f"declined; available {available} before hold",
        )

    return log.append(
        day=day,
        auth_ref=event.auth_ref,
        account_id=event.account_id,
        state=AuthState.APPROVED,
        hold=event.amount,
        note=f"approved; available {available} before hold, {remaining} after",
    )


def decide_settlement(
    journal: Journal, log: AuthorizationLog, event: Settlement
) -> bool:
    """Decide whether a settlement may post. The posting itself is replay's job.

    Returns True if the caller should append a debit for ``event.amount``.

    An unmatched settlement is refused and the refusal is recorded durably.
    That satisfies the brief's acceptance criterion 4 ("a settlement referencing
    an authorisation not present in the ledger is rejected and funds do not
    move") and is correct for this system as scoped -- but it is wrong for a
    real card issuer, where forced posts and late presentments arrive without a
    matching authorisation routinely and scheme rules oblige the issuer to
    honour them with chargeback as the recourse.
    """
    if not log.knows(event.auth_ref):
        journal.record_decision(
            booking_day=event.booking_day,
            account_id=event.account_id,
            decision=DecisionType.SETTLEMENT_REJECTED,
            event_id=event.event_id,
            subject=event.auth_ref,
            reason=f"unknown authorisation reference {event.auth_ref}",
        )
        return False

    state = log.state_of(event.auth_ref)
    if state is not AuthState.APPROVED:
        journal.record_decision(
            booking_day=event.booking_day,
            account_id=event.account_id,
            decision=DecisionType.SETTLEMENT_REJECTED,
            event_id=event.event_id,
            subject=event.auth_ref,
            reason=f"authorisation {event.auth_ref} is {state}, not open",
        )
        return False

    held = log.hold_for(event.auth_ref, event.booking_day)
    assert held is not None  # an APPROVED authorisation always has a hold
    residual = held - event.amount
    note = f"settled {event.amount} against a hold of {held}"
    if residual.is_positive:
        # Residual released immediately rather than held to expiry
        # (AMBIGUITIES item 9).
        note += f"; residual {residual} released"
    elif residual.is_negative:
        note += f"; settled {-residual} above the authorised amount"

    log.append(
        day=event.booking_day,
        auth_ref=event.auth_ref,
        account_id=event.account_id,
        state=AuthState.SETTLED,
        hold=Money.zero(held.currency),
        note=note,
    )
    return True


def expire_stale_authorizations(log: AuthorizationLog, day: int) -> list[AuthTransition]:
    """Release holds whose authorisation has outlived the expiry window.

    Called by the day-advance hook, never by an inbound event: expiry is
    triggered by the passage of time and by nothing else. It appends no ledger
    entry, because releasing a hold moves no money.
    """
    expired: list[AuthTransition] = []
    for auth_ref in log.references():
        if log.state_of(auth_ref) is not AuthState.APPROVED:
            continue
        approved_on = log.history(auth_ref)[0].day
        if day - approved_on < EXPIRY_WINDOW_DAYS:
            continue
        held = log.hold_for(auth_ref, day)
        assert held is not None
        expired.append(
            log.append(
                day=day,
                auth_ref=auth_ref,
                account_id=log.history(auth_ref)[0].account_id,
                state=AuthState.EXPIRED,
                hold=Money.zero(held.currency),
                note=(
                    f"expired unsettled after {EXPIRY_WINDOW_DAYS} days; "
                    f"hold of {held} released"
                ),
            )
        )
    return expired
