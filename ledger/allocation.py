"""Largest-remainder allocation of an integer total across integer weights.

Used twice: to split E10's BHD 10.000 credit into three instalments, and to
allocate an interest total across the days that produced it. Implemented once
and called twice, because two implementations of the same rule is two chances
to break double-entry in different ways.

The contract that matters is not fairness but *determinism*: the same inputs
must always produce the same output, in the same order, on any machine and any
interpreter run. Replaying a log through a non-deterministic allocator produces
different balances than the original run, silently. Ties therefore go to the
lowest index (AMBIGUITIES item 17).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence


def largest_remainder(total: int, weights: Sequence[int]) -> list[int]:
    """Split ``total`` across ``weights`` so that the parts sum to the total.

    Each part is the floor of its exact share; the shortfall is then handed out
    one unit at a time, largest fractional remainder first, lowest index
    winning any tie.
    """
    if not isinstance(total, int):
        raise TypeError("total must be an integer count of minor units")
    if total < 0:
        raise ValueError("total must not be negative")
    if not weights:
        raise ValueError("at least one weight is required")
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must not be negative")

    weight_total = sum(weights)
    if weight_total == 0:
        raise ValueError("weights must not sum to zero")

    exact = [Fraction(total * weight, weight_total) for weight in weights]
    parts = [share.numerator // share.denominator for share in exact]

    shortfall = total - sum(parts)
    remainders = [share - part for share, part in zip(exact, parts)]
    # Sort by descending remainder, then ascending index. Both keys are exact:
    # no float comparison decides where a minor unit lands.
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for index in order[:shortfall]:
        parts[index] += 1

    assert sum(parts) == total, "allocation must be exact"
    return parts
