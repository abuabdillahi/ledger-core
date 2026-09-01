"""Money as integer minor units, and the currency registry.

Two rules are enforced here and nowhere else.

*No floating point.* Money is an integer count of minor units (fils, and the
thousandth-of-a-dinar also called a fils in Bahrain). Anything that needs a
fractional value on the way to becoming money uses :class:`fractions.Fraction`,
which is exact. ``float`` is rejected at construction rather than tolerated.

*One rounding point.* This is the only module permitted to round, via
:func:`round_to_precision`, which takes an explicit named mode. Everything
upstream carries exact rationals and rounds exactly once, at the moment a
ledger entry is created (AMBIGUITIES item 15).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import assert_never

#: Currency -> number of decimal places. AED is a 2dp currency, BHD a 3dp one;
#: treating BHD as 2dp silently loses a factor of ten on every posting.
CURRENCY_EXPONENTS: dict[str, int] = {"AED": 2, "BHD": 3}

#: Account -> currency. The two accounts are fixed by the brief. An account's
#: currency never changes, so this is a registry rather than ledger state.
ACCOUNT_CURRENCIES: dict[str, str] = {"ACC-001": "AED", "ACC-002": "BHD"}


class CurrencyMismatch(Exception):
    """Arithmetic was attempted between two different currencies."""


class UnknownCurrency(Exception):
    """A currency outside the registry was used."""


class RoundingMode(StrEnum):
    """Named rounding modes. There is no default; callers must choose.

    Half-even is the house choice (AMBIGUITIES item 16). Half-up is present so
    that the claim "the mode does not change the output on this dataset" is
    testable rather than asserted.
    """

    HALF_EVEN = "HALF_EVEN"
    HALF_UP = "HALF_UP"


def exponent_of(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError:
        raise UnknownCurrency(currency) from None


def currency_of(account_id: str) -> str:
    try:
        return ACCOUNT_CURRENCIES[account_id]
    except KeyError:
        raise UnknownCurrency(f"no currency registered for {account_id}") from None


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount of one currency, held as signed minor units."""

    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if self.currency not in CURRENCY_EXPONENTS:
            raise UnknownCurrency(self.currency)
        if not isinstance(self.minor_units, int):
            raise TypeError(
                f"minor_units must be int, got {type(self.minor_units).__name__}"
            )

    # -- construction ----------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def from_major(
        cls,
        amount: str | int | Fraction,
        currency: str,
        mode: RoundingMode = RoundingMode.HALF_EVEN,
    ) -> Money:
        """Build from a major-unit literal, e.g. ``"1200.00"``.

        ``str`` is the intended form: ``Fraction("0.186")`` is exact where
        ``float("0.186")`` is not. ``float`` is refused outright.
        """
        if isinstance(amount, float):
            raise TypeError("float is not an acceptable money literal; use a string")
        return round_to_precision(Fraction(amount), currency, mode)

    # -- arithmetic ------------------------------------------------------

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(f"{self.currency} and {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor_units, self.currency)

    # -- inspection ------------------------------------------------------

    @property
    def is_negative(self) -> bool:
        return self.minor_units < 0

    @property
    def is_positive(self) -> bool:
        return self.minor_units > 0

    def as_major(self) -> Fraction:
        """The amount in major units, exactly."""
        return Fraction(self.minor_units, 10 ** exponent_of(self.currency))

    def __str__(self) -> str:
        exponent = exponent_of(self.currency)
        sign = "-" if self.minor_units < 0 else ""
        units = abs(self.minor_units)
        whole, fraction = divmod(units, 10**exponent)
        return f"{sign}{whole}.{fraction:0{exponent}d} {self.currency}"


def round_to_precision(
    amount: Fraction, currency: str, mode: RoundingMode
) -> Money:
    """Round an exact major-unit amount to a currency's precision.

    The single rounding point in the system.
    """
    if isinstance(amount, float):
        raise TypeError("float cannot be rounded exactly; pass a Fraction")
    scaled = Fraction(amount) * 10 ** exponent_of(currency)
    match mode:
        case RoundingMode.HALF_EVEN:
            return Money(_round_half_even(scaled), currency)
        case RoundingMode.HALF_UP:
            return Money(_round_half_up(scaled), currency)
        case _:
            assert_never(mode)


def _round_half_even(value: Fraction) -> int:
    floor = value.numerator // value.denominator
    remainder = value - floor
    if remainder < Fraction(1, 2):
        return floor
    if remainder > Fraction(1, 2):
        return floor + 1
    return floor if floor % 2 == 0 else floor + 1


def _round_half_up(value: Fraction) -> int:
    """Half-up in the arithmetic sense: ties go away from zero."""
    floor = value.numerator // value.denominator
    remainder = value - floor
    if remainder < Fraction(1, 2):
        return floor
    if remainder > Fraction(1, 2):
        return floor + 1
    return floor + 1 if value > 0 else floor
