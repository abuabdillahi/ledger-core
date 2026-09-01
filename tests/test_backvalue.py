"""The E7 back-value cascade, proved before fees exist at all.

This file deliberately predates the fee reconciler. The claim being tested is
purely about the projection design: appending an entry value-dated into a
already-closed day changes every subsequent day's closing balance, with no
propagation code anywhere, because a balance is a fold over a set defined by
value date.

The figures here are therefore the *pre-fee* cascade. Day 3 closes at 30.00,
not the 5.00 it reaches once the Day 2 fee is added to the picture.
"""

import pytest

from ledger.entries import Direction, EntryType
from ledger.journal import Journal
from ledger.money import Money
from ledger.projections import Basis, balance

WINDOW = range(1, 7)


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


def post(journal, *, booking_day, value_date, direction, amount, entry_type, origin_ref):
    return journal.append(
        booking_day=booking_day,
        value_date=value_date,
        account_id="ACC-001",
        direction=direction,
        amount=amount,
        entry_type=entry_type,
        origin_ref=origin_ref,
    )


@pytest.fixture
def journal_before_e7() -> Journal:
    """E1, E2, E4 and E5's postings. No fees, no authorisations, no interest."""
    journal = Journal()
    post(journal, booking_day=1, value_date=1, direction=Direction.CREDIT,
         amount=aed("1200.00"), entry_type=EntryType.CREDIT, origin_ref="E1")
    post(journal, booking_day=1, value_date=1, direction=Direction.DEBIT,
         amount=aed("950.00"), entry_type=EntryType.DEBIT, origin_ref="E2")
    post(journal, booking_day=3, value_date=3, direction=Direction.CREDIT,
         amount=aed("400.00"), entry_type=EntryType.CREDIT, origin_ref="E4")
    post(journal, booking_day=4, value_date=4, direction=Direction.DEBIT,
         amount=aed("185.00"), entry_type=EntryType.DEBIT, origin_ref="E5")
    return journal


def closing(journal, basis=Basis.VALUE) -> dict[int, str]:
    return {day: str(balance(journal, "ACC-001", day, basis)) for day in WINDOW}


def test_balances_before_the_back_value(journal_before_e7):
    assert closing(journal_before_e7) == {
        1: "250.00 AED",
        2: "250.00 AED",
        3: "650.00 AED",
        4: "465.00 AED",
        5: "465.00 AED",
        6: "465.00 AED",
    }


def test_back_valued_debit_rewrites_every_later_day(journal_before_e7):
    journal = journal_before_e7
    # E7: booked Day 5, value-dated Day 2. One append, no propagation code.
    post(journal, booking_day=5, value_date=2, direction=Direction.DEBIT,
         amount=aed("620.00"), entry_type=EntryType.DEBIT, origin_ref="E7")

    assert closing(journal) == {
        1: "250.00 AED",
        2: "-370.00 AED",  # acceptance criterion 1, and it is correct
        3: "30.00 AED",    # 5.00 once the Day 2 fee joins the fold
        4: "-155.00 AED",
        5: "-155.00 AED",
        6: "-155.00 AED",
    }


def test_every_day_from_the_value_date_onwards_moves_by_the_full_amount(
    journal_before_e7,
):
    """The effect does not stop at the value date -- that is where it starts."""
    journal = journal_before_e7
    before = {day: balance(journal, "ACC-001", day) for day in WINDOW}

    post(journal, booking_day=5, value_date=2, direction=Direction.DEBIT,
         amount=aed("620.00"), entry_type=EntryType.DEBIT, origin_ref="E7")

    after = {day: balance(journal, "ACC-001", day) for day in WINDOW}
    assert after[1] == before[1]  # Day 1 precedes the value date, untouched
    for day in (2, 3, 4, 5, 6):
        assert after[day] == before[day] - aed("620.00")


def test_the_two_bases_disagree_and_both_are_right(journal_before_e7):
    journal = journal_before_e7
    post(journal, booking_day=5, value_date=2, direction=Direction.DEBIT,
         amount=aed("620.00"), entry_type=EntryType.DEBIT, origin_ref="E7")

    # What we now understand Day 2 to have been:
    assert balance(journal, "ACC-001", 2, Basis.VALUE) == aed("-370.00")
    # What we believed on Day 4, and what the customer was told at the time:
    assert balance(journal, "ACC-001", 4, Basis.POSTING) == aed("465.00")
    # By Day 5 the posting basis has caught up, because E7 is now booked:
    assert balance(journal, "ACC-001", 5, Basis.POSTING) == aed("-155.00")


def test_reversal_restores_every_day_not_just_the_last(journal_before_e7):
    journal = journal_before_e7
    post(journal, booking_day=5, value_date=2, direction=Direction.DEBIT,
         amount=aed("620.00"), entry_type=EntryType.DEBIT, origin_ref="E7")
    # E9: booked Day 6, value-dated Day 2 -- the original's value date, not the
    # booking day (AMBIGUITIES item 15).
    post(journal, booking_day=6, value_date=2, direction=Direction.CREDIT,
         amount=aed("620.00"), entry_type=EntryType.REVERSAL, origin_ref="E7")

    assert closing(journal) == {
        1: "250.00 AED",
        2: "250.00 AED",
        3: "650.00 AED",
        4: "465.00 AED",
        5: "465.00 AED",
        6: "465.00 AED",
    }


def test_a_reversal_value_dated_to_its_booking_day_would_be_wrong(journal_before_e7):
    """The bug AMBIGUITIES item 15 exists to prevent, demonstrated."""
    journal = journal_before_e7
    post(journal, booking_day=5, value_date=2, direction=Direction.DEBIT,
         amount=aed("620.00"), entry_type=EntryType.DEBIT, origin_ref="E7")
    post(journal, booking_day=6, value_date=6, direction=Direction.CREDIT,
         amount=aed("620.00"), entry_type=EntryType.REVERSAL, origin_ref="E7")

    assert balance(journal, "ACC-001", 6) == aed("465.00")  # right on the last day
    assert balance(journal, "ACC-001", 2) == aed("-370.00")  # wrong on every other


def test_nothing_is_ever_mutated(journal_before_e7):
    journal = journal_before_e7
    before = journal.entries
    post(journal, booking_day=5, value_date=2, direction=Direction.DEBIT,
         amount=aed("620.00"), entry_type=EntryType.DEBIT, origin_ref="E7")
    after = journal.entries

    assert after[: len(before)] == before  # every prior entry, byte for byte
    assert len(after) == len(before) + 1
    assert [entry.sequence for entry in after] == [1, 2, 3, 4, 5]
