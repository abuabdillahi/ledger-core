"""Daily accrual, the rounding divergence, and capitalisation."""

from fractions import Fraction

from ledger.entries import Direction, EntryType
from ledger.fees import reconcile
from ledger.interest import DAILY_RATE, accrue, capitalise
from ledger.journal import Journal
from ledger.money import Money
from ledger.projections import balance

WINDOW = range(1, 7)


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


def bhd(literal: str) -> Money:
    return Money.from_major(literal, "BHD")


def acc_001_final() -> Journal:
    """ACC-001's final entry set: E1, E2, E4, E5, and E7 cancelled by E9."""
    journal = Journal()
    for day, direction, amount, origin, value_date in (
        (1, Direction.CREDIT, "1200.00", "E1", 1),
        (1, Direction.DEBIT, "950.00", "E2", 1),
        (3, Direction.CREDIT, "400.00", "E4", 3),
        (4, Direction.DEBIT, "185.00", "E5", 4),
        (5, Direction.DEBIT, "620.00", "E7", 2),
    ):
        journal.append(
            booking_day=day, value_date=value_date, account_id="ACC-001",
            direction=direction, amount=aed(amount),
            entry_type=EntryType.CREDIT if direction is Direction.CREDIT
            else EntryType.DEBIT,
            origin_ref=origin,
        )
    reconcile(journal, "ACC-001", 5)
    journal.append(
        booking_day=6, value_date=2, account_id="ACC-001",
        direction=Direction.CREDIT, amount=aed("620.00"),
        entry_type=EntryType.REVERSAL, origin_ref="E7",
    )
    reconcile(journal, "ACC-001", 6)
    return journal


def test_the_rate_is_an_exact_rational():
    assert DAILY_RATE == Fraction(1, 2500)
    assert not isinstance(DAILY_RATE, float)


def test_acc_001_daily_accrual_table():
    accruals = accrue(acc_001_final(), "ACC-001", WINDOW)

    assert [str(a.basis) for a in accruals] == [
        "250.00 AED", "250.00 AED", "650.00 AED",
        "465.00 AED", "465.00 AED", "465.00 AED",
    ]
    assert [str(a.rounded) for a in accruals] == [
        "0.10 AED", "0.10 AED", "0.26 AED",
        "0.19 AED", "0.19 AED", "0.19 AED",
    ]
    # 465.00 x 0.04% is exactly 0.186 -- not 0.18600000000000003.
    assert accruals[3].exact == Fraction(186, 1000)


def test_the_rounding_divergence_is_real_not_theoretical():
    """REJECTED criterion 8: there is a remainder, and it cannot be discarded."""
    result = capitalise(acc_001_final(), "ACC-001", WINDOW, booking_day=6)

    assert result.exact_total == Fraction(1018, 1000)  # 1.018
    assert result.total == aed("1.03")
    assert result.total.as_major() != result.exact_total


def test_rounded_dailies_sum_exactly_to_the_capitalised_total():
    """The brief's non-negotiable rule, satisfied by construction."""
    result = capitalise(acc_001_final(), "ACC-001", WINDOW, booking_day=6)
    assert sum(a.rounded.minor_units for a in result.accruals) == result.total.minor_units
    assert result.total == aed("1.03")


def test_capitalisation_posts_one_credit_at_the_end_of_the_window():
    journal = acc_001_final()
    before = balance(journal, "ACC-001", 6)
    result = capitalise(journal, "ACC-001", WINDOW, booking_day=6)

    assert before == aed("465.00")  # reported separately from the credit
    assert result.entry is not None
    assert result.entry.entry_type is EntryType.INTEREST_CAPITALISATION
    assert result.entry.direction is Direction.CREDIT
    assert result.entry.value_date == 6
    assert balance(journal, "ACC-001", 6) == aed("466.03")


def test_the_capitalisation_credit_does_not_accrue_on_itself():
    journal = acc_001_final()
    result = capitalise(journal, "ACC-001", WINDOW, booking_day=6)
    # Day 6 accrued on 465.00, the pre-capitalisation balance, even though the
    # journal now closes Day 6 at 466.03 (AMBIGUITIES item 13).
    assert result.accruals[-1].basis == aed("465.00")
    assert balance(journal, "ACC-001", 6) == aed("466.03")


def test_the_capitalisation_credit_warrants_no_fee():
    journal = acc_001_final()
    capitalise(journal, "ACC-001", WINDOW, booking_day=6)
    assert reconcile(journal, "ACC-001", 6) == []


def test_acc_002_accrues_only_on_the_days_it_holds_a_balance():
    journal = Journal()
    for amount in ("3.334", "3.333", "3.333"):
        journal.append(
            booking_day=5, value_date=5, account_id="ACC-002",
            direction=Direction.CREDIT, amount=bhd(amount),
            entry_type=EntryType.CREDIT, origin_ref="E10",
        )
    result = capitalise(journal, "ACC-002", WINDOW, booking_day=6)

    assert [str(a.rounded) for a in result.accruals] == [
        "0.000 BHD", "0.000 BHD", "0.000 BHD",
        "0.000 BHD", "0.004 BHD", "0.004 BHD",
    ]
    assert result.total == bhd("0.008")
    # 10.000 x 0.0004 = 0.004 is exact at three decimal places, so unlike
    # ACC-001 there is no divergence to resolve here at all.
    assert result.exact_total == result.total.as_major()
    assert balance(journal, "ACC-002", 6) == bhd("10.008")


def test_a_zero_balance_earns_nothing():
    journal = Journal()
    result = capitalise(journal, "ACC-001", WINDOW, booking_day=6)
    assert result.total == aed("0.00")
    assert result.entry is None  # no zero-value posting clutters the journal


def test_a_negative_balance_earns_nothing_rather_than_being_charged():
    journal = Journal()
    journal.append(
        booking_day=1, value_date=1, account_id="ACC-001",
        direction=Direction.DEBIT, amount=aed("100.00"),
        entry_type=EntryType.DEBIT, origin_ref="setup",
    )
    accruals = accrue(journal, "ACC-001", WINDOW)
    assert all(a.rounded == aed("0.00") for a in accruals)
    assert all(a.exact == 0 for a in accruals)
