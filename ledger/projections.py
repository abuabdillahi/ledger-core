"""Balances, computed from the journal on demand. Never stored.

Every function here is a pure fold over the entry list. That is the whole
design: a balance is not a number the ledger keeps up to date, it is a question
the ledger answers by looking at what it has been told. Appending an entry
value-dated to a day that has already closed therefore needs no forward
propagation of any kind -- the next query simply sums a larger set.

Two bases, and they disagree, which is the point:

* **VALUE** -- every entry whose value date falls on or before the day. This is
  the basis for interest and for overdraft assessment: it answers "what was the
  balance on that day, as we now understand it".
* **POSTING** -- additionally requires that the entry had actually been booked
  by that day. This answers a different and equally necessary question: "what
  did we believe, and what would we have told the customer, at the time".

On Day 4, ACC-001's Day 2 balance is 250.00 on both bases. On Day 5, after E7
is booked back to Day 2, the value basis says -370.00 and the posting basis
still says 250.00. Both are true. A ledger that can only produce one of them
cannot both calculate correctly and explain itself to an auditor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Callable, Iterable, Protocol, assert_never

from ledger.entries import Entry
from ledger.journal import Journal
from ledger.money import Money, currency_of


class Basis(StrEnum):
    VALUE = "VALUE"
    POSTING = "POSTING"


class HoldRegistry(Protocol):
    """What ``available_balance`` needs to know about holds.

    Declared structurally so that this module does not depend on ``auth``:
    balances are arithmetic over the journal, and they should not need to know
    what an authorisation is.
    """

    def active_holds(self, account_id: str, day: int) -> Money: ...


def in_scope(entry: Entry, day: int, basis: Basis) -> bool:
    match basis:
        case Basis.VALUE:
            return entry.value_date <= day
        case Basis.POSTING:
            return entry.value_date <= day and entry.booking_day <= day
        case _:
            assert_never(basis)


def entries_for(
    journal: Journal,
    account_id: str,
    day: int,
    basis: Basis = Basis.VALUE,
) -> tuple[Entry, ...]:
    """Every entry counting towards ``account_id`` on ``day`` under ``basis``."""
    return tuple(
        entry
        for entry in journal
        if entry.account_id == account_id and in_scope(entry, day, basis)
    )


def balance(
    journal: Journal,
    account_id: str,
    day: int,
    basis: Basis = Basis.VALUE,
    *,
    exclude: Callable[[Entry], bool] | None = None,
) -> Money:
    """Closing balance for ``account_id`` at end of ``day``.

    ``exclude`` drops entries from the fold. It exists for one caller: the fee
    reconciler, which must assess a day on a basis that excludes that day's own
    fee, or the fee would be an input to its own assessment (AMBIGUITIES item
    2). Prior days' fees are not excluded -- they are history.
    """
    total = sum(
        entry.signed_minor_units
        for entry in entries_for(journal, account_id, day, basis)
        if exclude is None or not exclude(entry)
    )
    return Money(total, currency_of(account_id))


def available_balance(
    journal: Journal,
    holds: HoldRegistry,
    account_id: str,
    day: int,
) -> Money:
    """Value-basis ledger balance less the holds active on that day.

    Not a field. Holds are not entries -- they move no money -- so this is the
    only place the two ideas meet.
    """
    return balance(journal, account_id, day, Basis.VALUE) - holds.active_holds(
        account_id, day
    )


def closing_balances(
    journal: Journal,
    account_id: str,
    days: Iterable[int],
    basis: Basis = Basis.VALUE,
) -> dict[int, Money]:
    """Closing balance per day, for reporting and for interest accrual."""
    return {day: balance(journal, account_id, day, basis) for day in days}
