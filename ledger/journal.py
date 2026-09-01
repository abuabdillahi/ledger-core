"""The journal: the only state in the system.

Everything else -- balances, available balance, whether a fee is currently
warranted, an authorisation's state -- is a pure function computed over this
list on demand. Nothing is cached and nothing is stored twice, so there is no
second copy of the truth to fall out of step with the first.

That is what makes the back-value cascade free. Appending E7 (a Day 5 booking
value-dated to Day 2) propagates nothing forward, because there is nothing to
propagate to. Every subsequent query returns a different answer simply because
its input set grew. If this module ever acquires an ``update_balance`` method,
the design has gone wrong.

**Two logs, one sequence space.** Append-only means "rejected" cannot mean
"discarded": a decision not to post is still a decision, and it is the one an
auditor is most likely to ask about. Financial postings go to the entry log and
non-financial decisions to the decision log, but both draw from the same
monotonic counter, so the position of a decision relative to the postings around
it is never ambiguous.

In production these would more usually be separated -- an upstream event store
holding all inbound events and decisions, with the ledger downstream holding
financial postings only, so that the book of record contains nothing but money.
They are combined here to stay in scope, and because a single sequence space
gives the ordering guarantee for free that two stores would have to coordinate
to provide.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator

from ledger.entries import Direction, Entry, EntryType
from ledger.money import Money


class DecisionType(StrEnum):
    SETTLEMENT_REJECTED = "SETTLEMENT_REJECTED"
    AUTHORIZATION_DECLINED = "AUTHORIZATION_DECLINED"


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """A durable record of a decision that moved no money."""

    sequence: int
    booking_day: int
    account_id: str
    decision: DecisionType
    event_id: str
    subject: str
    reason: str

    def __str__(self) -> str:
        return (
            f"[{self.sequence}] day {self.booking_day} {self.account_id} "
            f"{self.decision} {self.event_id} ({self.subject}): {self.reason}"
        )


class Journal:
    """An append-only store. There is no update and no delete, by construction."""

    __slots__ = ("_entries", "_decisions", "_next_sequence")

    def __init__(self) -> None:
        self._entries: list[Entry] = []
        self._decisions: list[DecisionRecord] = []
        self._next_sequence = 1

    def _take_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence

    def append(
        self,
        *,
        booking_day: int,
        value_date: int,
        account_id: str,
        direction: Direction,
        amount: Money,
        entry_type: EntryType,
        origin_ref: str,
    ) -> Entry:
        """Append one posting and return it."""
        if amount.minor_units < 0:
            raise ValueError(
                "entry amounts are unsigned; direction carries the sign"
            )
        entry = Entry(
            sequence=self._take_sequence(),
            booking_day=booking_day,
            value_date=value_date,
            account_id=account_id,
            direction=direction,
            amount=amount,
            entry_type=entry_type,
            origin_ref=origin_ref,
        )
        self._entries.append(entry)
        return entry

    def record_decision(
        self,
        *,
        booking_day: int,
        account_id: str,
        decision: DecisionType,
        event_id: str,
        subject: str,
        reason: str,
    ) -> DecisionRecord:
        """Append one non-financial decision record and return it."""
        record = DecisionRecord(
            sequence=self._take_sequence(),
            booking_day=booking_day,
            account_id=account_id,
            decision=decision,
            event_id=event_id,
            subject=subject,
            reason=reason,
        )
        self._decisions.append(record)
        return record

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    @property
    def decisions(self) -> tuple[DecisionRecord, ...]:
        return tuple(self._decisions)

    def __iter__(self) -> Iterator[Entry]:
        return iter(tuple(self._entries))

    def __len__(self) -> int:
        return len(self._entries)
