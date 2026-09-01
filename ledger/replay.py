"""Replay: the orchestrator, and the only place time moves.

Events are processed in stream order, because the brief says they are replayed
in that order and because a system that silently reorders its input has an
unreliable audit trail (AMBIGUITIES item 7). Booking day is retained as data on
every event and entry, so the posting-basis timeline survives intact.

**The day-advance hook.** Authorisation expiry is triggered by the passage of
time rather than by an inbound event, so it needs somewhere to happen. There is
no timer, no background thread and no wall clock here: time moves only when this
loop moves it, synchronously, between events. That is a deliberate, deterministic
stand-in for end-of-day batch processing, which is a real and central concept in
core banking -- and time-triggered processing is architecturally distinct from
event-triggered processing precisely because nothing external prompts it.

Three details in that loop are load-bearing:

* ``while``, not ``if``: a day containing no events must still be advanced
  through, or its end-of-day work never happens.
* The drain loop after the stream: the last event is booked on Day 5, and Day 6
  must still occur.
* The clock is monotonic even though booking days in the stream are not. E9 is
  booked Day 6 and E10 Day 5, so when E10 arrives the clock is already at 6, the
  condition is false, and the clock does not move. It never runs backwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, assert_never

from ledger.allocation import largest_remainder
from ledger.auth import AuthorizationLog, decide_settlement, expire_stale_authorizations, request_authorization
from ledger.entries import Direction, EntryType
from ledger.events import Authorization, Credit, Debit, Event, Reversal, Settlement
from ledger.fees import reconcile
from ledger.interest import Capitalisation, capitalise
from ledger.journal import Journal
from ledger.money import Money

WINDOW_START = 1
WINDOW_END = 6
WINDOW = range(WINDOW_START, WINDOW_END + 1)

ACCOUNTS = ("ACC-001", "ACC-002")


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


def bhd(literal: str) -> Money:
    return Money.from_major(literal, "BHD")


#: The ten events, in the order they are to be replayed. Booking day and value
#: date differ for E7 and E9, and the stream is not in booking-day order.
EVENT_STREAM: tuple[Event, ...] = (
    Credit("E1", 1, 1, "ACC-001", aed("1200.00")),
    Debit("E2", 1, 1, "ACC-001", aed("950.00")),
    Authorization("E3", 2, 2, "ACC-001", "Auth-A", aed("200.00")),
    Credit("E4", 3, 3, "ACC-001", aed("400.00")),
    Settlement("E5", 4, 4, "ACC-001", "Auth-A", aed("185.00")),
    Settlement("E6", 4, 4, "ACC-001", "Auth-Z", aed("180.00")),
    Debit("E7", 5, 2, "ACC-001", aed("620.00")),
    Authorization("E8", 5, 5, "ACC-001", "Auth-B", aed("90.00")),
    Reversal("E9", 6, 2, "ACC-001", "E7"),
    Credit("E10", 5, 5, "ACC-002", bhd("10.000"), instalments=3),
)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    journal: Journal
    auth_log: AuthorizationLog
    capitalisations: tuple[Capitalisation, ...]
    days: range
    accounts: tuple[str, ...]


def advance_to(auth_log: AuthorizationLog, day: int) -> None:
    """End-of-day processing for ``day``.

    Takes no journal: everything it does -- releasing holds whose authorisation
    has expired -- moves no money and appends no ledger entry. If that ever
    stops being true, the signature should change deliberately rather than the
    parameter having been there all along waiting to be used.
    """
    expire_stale_authorizations(auth_log, day)


def handle(
    journal: Journal, auth_log: AuthorizationLog, event: Event, today: int
) -> bool:
    """Apply one event. Returns whether it appended any financial entries."""
    match event:
        case Credit():
            amounts = largest_remainder(
                event.amount.minor_units, [1] * event.instalments
            )
            for index, minor_units in enumerate(amounts, start=1):
                journal.append(
                    booking_day=event.booking_day,
                    value_date=event.value_date,
                    account_id=event.account_id,
                    direction=Direction.CREDIT,
                    amount=Money(minor_units, event.amount.currency),
                    entry_type=EntryType.CREDIT,
                    origin_ref=(
                        event.event_id
                        if event.instalments == 1
                        else f"{event.event_id}:{index}/{event.instalments}"
                    ),
                )
            return True

        case Debit():
            journal.append(
                booking_day=event.booking_day,
                value_date=event.value_date,
                account_id=event.account_id,
                direction=Direction.DEBIT,
                amount=event.amount,
                entry_type=EntryType.DEBIT,
                origin_ref=event.event_id,
            )
            return True

        case Authorization():
            # Appends a transition and possibly a decision record; no entry,
            # because a hold moves no money.
            request_authorization(journal, auth_log, event)
            return False

        case Settlement():
            if not decide_settlement(journal, auth_log, event):
                return False
            journal.append(
                booking_day=event.booking_day,
                value_date=event.value_date,
                account_id=event.account_id,
                direction=Direction.DEBIT,
                amount=event.amount,
                entry_type=EntryType.DEBIT,
                origin_ref=f"{event.event_id}:{event.auth_ref}",
            )
            return True

        case Reversal():
            originals = [
                entry
                for entry in journal
                if entry.origin_ref.split(":")[0] == event.reverses_event_id
                and entry.entry_type in (EntryType.CREDIT, EntryType.DEBIT)
            ]
            if not originals:
                raise ValueError(
                    f"{event.event_id} reverses {event.reverses_event_id}, "
                    "which posted nothing"
                )
            for original in originals:
                journal.append(
                    booking_day=event.booking_day,
                    # The original's value date, not the booking day: a
                    # compensating entry only nets to zero on every day's
                    # balance if it shares it (AMBIGUITIES item 15).
                    value_date=event.value_date,
                    account_id=event.account_id,
                    direction=original.opposite_direction(),
                    amount=original.amount,
                    entry_type=EntryType.REVERSAL,
                    origin_ref=f"{event.event_id}:reverses:{original.origin_ref}",
                )
            return True

        case _:
            assert_never(event)


def replay(
    events: Sequence[Event] = EVENT_STREAM,
    *,
    window_end: int = WINDOW_END,
    accounts: Iterable[str] = ACCOUNTS,
    capitalise_interest: bool = True,
) -> ReplayResult:
    """Replay ``events`` in order and return the resulting state.

    ``capitalise_interest`` and a truncated ``events`` sequence exist so that
    intermediate states -- notably the one after E7 and before E9 -- are
    reachable and testable rather than only inferrable.
    """
    journal = Journal()
    auth_log = AuthorizationLog()
    accounts = tuple(accounts)

    current_day = 0
    for event in events:
        while current_day < event.booking_day:  # while, not if
            current_day += 1
            advance_to(auth_log, current_day)

        if handle(journal, auth_log, event, current_day):
            reconcile(journal, event.account_id, current_day)

    while current_day < window_end:  # the last event is booked Day 5
        current_day += 1
        advance_to(auth_log, current_day)

    days = range(WINDOW_START, window_end + 1)
    capitalisations: tuple[Capitalisation, ...] = ()
    if capitalise_interest:
        capitalisations = tuple(
            capitalise(journal, account_id, days, booking_day=window_end)
            for account_id in accounts
        )

    return ReplayResult(
        journal=journal,
        auth_log=auth_log,
        capitalisations=capitalisations,
        days=days,
        accounts=accounts,
    )
