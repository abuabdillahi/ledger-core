"""Daily interest accrual and end-of-window capitalisation.

Runs once, after every event has been replayed, over the *final* value-dated
closing balances -- so the corrected history is the history, and the transient
negative balances that existed between E7 and E9 never earn or lose anything
(AMBIGUITIES item 5).

The rate is an exact rational, ``Fraction(4, 10000)``, and each day's accrual is
computed exactly and rounded once. 465.00 x 0.04% is exactly 0.186; rounding
that to 0.19 and carrying the rounded figure forward would bake in 0.004 per day
and compound it (AMBIGUITIES item 16).

The capitalised total is *defined* as the sum of the rounded daily accruals,
which satisfies the brief's rule by construction rather than by a reconciliation
step that could itself fail. On ACC-001 the exact accrual total is 1.018 and the
sum of the rounded dailies is 1.03; the alternative -- round the exact total to
1.02 and allocate it back across the days -- is set out in AMBIGUITIES item 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ledger.entries import Direction, Entry, EntryType
from ledger.journal import Journal
from ledger.money import Money, RoundingMode, currency_of, round_to_precision
from ledger.projections import Basis, balance

#: 0.04% per day, exactly. Never 0.0004 as a float.
DAILY_RATE = Fraction(4, 10_000)

ROUNDING_MODE = RoundingMode.HALF_EVEN


@dataclass(frozen=True, slots=True)
class DailyAccrual:
    day: int
    basis: Money
    exact: Fraction  # major units, exact
    rounded: Money


@dataclass(frozen=True, slots=True)
class Capitalisation:
    account_id: str
    accruals: tuple[DailyAccrual, ...]
    total: Money
    entry: Entry | None

    @property
    def exact_total(self) -> Fraction:
        """What the accruals came to before each was rounded."""
        return sum((accrual.exact for accrual in self.accruals), Fraction(0))


def accrue(journal: Journal, account_id: str, days: range) -> tuple[DailyAccrual, ...]:
    """Accrue on each day's closing balance. Positive balances only."""
    currency = currency_of(account_id)
    accruals: list[DailyAccrual] = []
    for day in days:
        basis = balance(journal, account_id, day, Basis.VALUE)
        # Zero is not positive, and a negative balance does not earn interest.
        exact = basis.as_major() * DAILY_RATE if basis.is_positive else Fraction(0)
        accruals.append(
            DailyAccrual(
                day=day,
                basis=basis,
                exact=exact,
                rounded=round_to_precision(exact, currency, ROUNDING_MODE),
            )
        )
    return tuple(accruals)


def capitalise(
    journal: Journal, account_id: str, days: range, booking_day: int
) -> Capitalisation:
    """Accrue over ``days`` and post a single capitalisation credit.

    The credit is value-dated to the last day of the window and posted *after*
    the accrual is computed, so it does not accrue on itself. Being a credit it
    cannot make a balance negative, so it warrants no fee reassessment
    (AMBIGUITIES item 13).
    """
    currency = currency_of(account_id)
    accruals = accrue(journal, account_id, days)

    total = Money.zero(currency)
    for accrual in accruals:
        total = total + accrual.rounded

    # The brief's rule, satisfied by construction rather than by adjustment.
    assert total.minor_units == sum(a.rounded.minor_units for a in accruals)

    entry = None
    if total.is_positive:
        entry = journal.append(
            booking_day=booking_day,
            value_date=days[-1],
            account_id=account_id,
            direction=Direction.CREDIT,
            amount=total,
            entry_type=EntryType.INTEREST_CAPITALISATION,
            origin_ref=f"interest:{account_id}:days-{days[0]}-{days[-1]}",
        )
    return Capitalisation(
        account_id=account_id, accruals=accruals, total=total, entry=entry
    )
