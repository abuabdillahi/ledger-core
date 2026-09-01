"""Money: exactness, currency safety, and the single rounding point."""

from fractions import Fraction

import pytest

from ledger.money import (
    CurrencyMismatch,
    Money,
    RoundingMode,
    UnknownCurrency,
    currency_of,
    round_to_precision,
)


def test_minor_units_are_the_representation():
    assert Money.from_major("1200.00", "AED").minor_units == 120000
    assert Money.from_major("10.000", "BHD").minor_units == 10000


def test_bhd_is_three_decimal_places_not_two():
    # The whole point of a second currency in this brief. 10.000 BHD is ten
    # thousand minor units, not one thousand.
    assert Money.from_major("10.000", "BHD").minor_units == 10000
    assert str(Money(3334, "BHD")) == "3.334 BHD"


def test_float_is_refused_at_every_door():
    with pytest.raises(TypeError):
        Money(12.5, "AED")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.from_major(12.5, "AED")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        round_to_precision(0.186, "AED", RoundingMode.HALF_EVEN)  # type: ignore[arg-type]


def test_money_is_immutable():
    amount = Money(100, "AED")
    with pytest.raises(Exception):
        amount.minor_units = 200  # type: ignore[misc]


def test_arithmetic_across_currencies_raises():
    with pytest.raises(CurrencyMismatch):
        Money(100, "AED") + Money(100, "BHD")
    with pytest.raises(CurrencyMismatch):
        Money(100, "AED") - Money(100, "BHD")


def test_unknown_currency_is_rejected():
    with pytest.raises(UnknownCurrency):
        Money(100, "USD")
    with pytest.raises(UnknownCurrency):
        currency_of("ACC-999")


def test_half_even_rounding():
    # 3.3335 -> 3333.5 minor units; 3333 is odd so the tie rounds up.
    assert Money.from_major("3.3335", "BHD").minor_units == 3334
    # 3.3325 -> 3332.5 minor units; 3332 is even so the tie rounds down.
    assert Money.from_major("3.3325", "BHD").minor_units == 3332


def test_half_up_differs_only_on_exact_ties():
    assert Money.from_major("3.3325", "BHD", RoundingMode.HALF_UP).minor_units == 3333
    # ... and agrees everywhere else, which is why the mode does not bind on
    # this dataset (AMBIGUITIES item 17).
    daily_accrual = Fraction(465) * Fraction(4, 10000)  # exactly 0.186
    assert round_to_precision(daily_accrual, "AED", RoundingMode.HALF_EVEN) == Money(
        19, "AED"
    )
    assert round_to_precision(daily_accrual, "AED", RoundingMode.HALF_UP) == Money(
        19, "AED"
    )


def test_half_up_ties_go_away_from_zero():
    assert round_to_precision(
        Fraction(-3325, 1000), "BHD", RoundingMode.HALF_UP
    ) == Money(-3325, "BHD")
    assert round_to_precision(
        Fraction(-125, 1000), "AED", RoundingMode.HALF_UP
    ) == Money(-13, "AED")
    assert round_to_precision(
        Fraction(-125, 1000), "AED", RoundingMode.HALF_EVEN
    ) == Money(-12, "AED")


def test_exact_rational_input_is_not_pre_rounded():
    # 0.04% of 465.00 is exactly 0.186 and must reach the rounding point
    # undisturbed (AMBIGUITIES item 16).
    exact = Money.from_major("465.00", "AED").as_major() * Fraction(4, 10000)
    assert exact == Fraction(186, 1000)


def test_negative_amounts_format_and_compare():
    overdrawn = Money.from_major("1200.00", "AED") - Money.from_major(
        "950.00", "AED"
    ) - Money.from_major("620.00", "AED")
    assert overdrawn == Money(-37000, "AED")
    assert str(overdrawn) == "-370.00 AED"
    assert overdrawn.is_negative and not overdrawn.is_positive


def test_zero_is_neither_positive_nor_negative():
    # Strict inequality at the overdraft threshold (AMBIGUITIES item 12).
    flat = Money.zero("AED")
    assert not flat.is_negative
    assert not flat.is_positive
