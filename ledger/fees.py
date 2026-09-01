"""Overdraft fees, as a reconciler rather than an assessor.

The reconciler computes the fee set the current journal *warrants*, diffs it
against the fees actually standing, and appends the difference: a new fee where
one is missing, a reversal where one is no longer warranted. Nothing is ever
mutated and nothing is deleted.

One mechanism, both directions. E7 arrives and the diff appends three fees; E9
arrives and the same code, unchanged, appends three fee reversals. There is no
separate unwind path to keep in step with the assessment path, which is where a
system with two paths eventually goes wrong.

**A day's own fee is excluded from that day's assessment basis.** Prior days'
fees count -- they are history, and they propagate forward like any other entry
-- but the fee being decided cannot also be an input to the decision
(AMBIGUITIES item 2). The consequence is that day D's fee depends only on
non-fee entries and on fees from days strictly earlier than D, so the dependency
graph is acyclic by day and one ascending pass over the window is sufficient. No
fixed-point iteration, and a tripwire assertion if that ever stops being true.
"""

from __future__ import annotations

from typing import assert_never

from ledger.entries import Direction, Entry, EntryType
from ledger.journal import Journal
from ledger.money import Money, currency_of
from ledger.projections import Basis, balance

#: Published fee tariff per currency. BHD is a tariff, not an FX conversion of
#: the AED figure; see AMBIGUITIES item 11 and NUMBERS.md.
OVERDRAFT_FEE_TARIFF: dict[str, Money] = {
    "AED": Money(2500, "AED"),   # 25.00
    "BHD": Money(2500, "BHD"),   # 2.500
}

#: A fee is assessed when the closing balance is *strictly* below this figure.
#: Zero is not an overdraft (AMBIGUITIES item 12).
OVERDRAFT_THRESHOLD_MINOR_UNITS = 0


def is_fee_posting(entry_type: EntryType) -> bool:
    """Whether an entry type is part of the fee mechanism.

    Exhaustive by design: a seventh entry type must be classified here
    deliberately rather than defaulting into "not a fee" and silently changing
    every assessment basis in the system.
    """
    match entry_type:
        case EntryType.OVERDRAFT_FEE | EntryType.FEE_REVERSAL:
            return True
        case (
            EntryType.CREDIT
            | EntryType.DEBIT
            | EntryType.REVERSAL
            | EntryType.INTEREST_CAPITALISATION
        ):
            return False
        case _:
            assert_never(entry_type)


def standing_fee(journal: Journal, account_id: str, day: int) -> Entry | None:
    """The fee value-dated to ``day`` that has been posted and not reversed."""
    posted = [
        entry
        for entry in journal
        if entry.account_id == account_id
        and entry.value_date == day
        and entry.entry_type is EntryType.OVERDRAFT_FEE
    ]
    reversed_count = sum(
        1
        for entry in journal
        if entry.account_id == account_id
        and entry.value_date == day
        and entry.entry_type is EntryType.FEE_REVERSAL
    )
    outstanding = posted[reversed_count:]
    return outstanding[0] if outstanding else None


def assessment_basis(journal: Journal, account_id: str, day: int) -> Money:
    """Closing balance for ``day``, excluding any fee value-dated to ``day``."""
    return balance(
        journal,
        account_id,
        day,
        Basis.VALUE,
        exclude=lambda entry, d=day: is_fee_posting(entry.entry_type)
        and entry.value_date == d,
    )


def reconcile(journal: Journal, account_id: str, today: int) -> list[Entry]:
    """Bring the fees on ``account_id`` into line with what the journal warrants.

    ``today`` is both the last day assessed and the booking day of anything
    appended: a fee discovered on Day 5 for Day 2 is *booked* on Day 5 and
    *value-dated* to Day 2, so it lands in Day 2's balance and propagates
    forward from there like any other back-valued entry.
    """
    currency = currency_of(account_id)
    tariff = OVERDRAFT_FEE_TARIFF[currency]
    appended: list[Entry] = []
    assessed: set[int] = set()

    for day in range(1, today + 1):
        # Tripwire, not a loop bound. If a day is ever assessed twice in one
        # run, the acyclicity argument in AMBIGUITIES item 2 has been broken
        # and the right response is to find out why, not to iterate.
        assert (
            day not in assessed
        ), f"{account_id} day {day} assessed twice in one reconciliation"
        assessed.add(day)

        warranted = (
            assessment_basis(journal, account_id, day).minor_units
            < OVERDRAFT_THRESHOLD_MINOR_UNITS
        )
        standing = standing_fee(journal, account_id, day)

        if warranted and standing is None:
            appended.append(
                journal.append(
                    booking_day=today,
                    value_date=day,
                    account_id=account_id,
                    direction=Direction.DEBIT,
                    amount=tariff,
                    entry_type=EntryType.OVERDRAFT_FEE,
                    origin_ref=f"overdraft-fee:{account_id}:day-{day}",
                )
            )
        elif standing is not None and not warranted:
            # Reverse what was actually posted, not what the tariff says today.
            # The reversal takes the original's value date, or it would correct
            # the last day and leave every earlier one adrift (AMBIGUITIES 15).
            appended.append(
                journal.append(
                    booking_day=today,
                    value_date=standing.value_date,
                    account_id=account_id,
                    direction=standing.opposite_direction(),
                    amount=standing.amount,
                    entry_type=EntryType.FEE_REVERSAL,
                    origin_ref=f"fee-reversal:{standing.origin_ref}",
                )
            )

    _assert_settled(journal, account_id, today)
    return appended


def _assert_settled(journal: Journal, account_id: str, today: int) -> None:
    """A second pass must find nothing to do.

    This is the acyclicity claim, checked rather than trusted: if one ascending
    pass were not sufficient, this would fail loudly at the point of the error
    instead of leaving a wrong balance to be discovered later.
    """
    for day in range(1, today + 1):
        warranted = (
            assessment_basis(journal, account_id, day).minor_units
            < OVERDRAFT_THRESHOLD_MINOR_UNITS
        )
        assert warranted == (
            standing_fee(journal, account_id, day) is not None
        ), f"fee reconciliation did not converge in one pass on day {day}"
