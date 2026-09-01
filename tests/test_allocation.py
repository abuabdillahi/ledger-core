"""Largest-remainder allocation: exactness and deterministic tie-breaking."""

import pytest

from ledger.allocation import largest_remainder


def test_e10_instalment_split():
    # The acceptance criterion says 3.334 three times. That sums to 10.002 and
    # breaks double-entry (REJECTED criterion 7).
    parts = largest_remainder(10_000, [1, 1, 1])
    assert parts == [3334, 3333, 3333]
    assert sum(parts) == 10_000


def test_parts_always_sum_to_the_total():
    for total in range(0, 60):
        for count in range(1, 8):
            parts = largest_remainder(total, [1] * count)
            assert sum(parts) == total


def test_ties_go_to_the_lowest_index():
    # All three shares are 3333 + 1/3, so the single spare unit is contested by
    # a three-way tie. Lowest index takes it, every time.
    assert largest_remainder(10_000, [1, 1, 1])[0] == 3334
    assert largest_remainder(5, [1, 1, 1, 1]) == [2, 1, 1, 1]


def test_allocation_is_repeatable():
    # Replay determinism: the same call is the same answer, always. If this
    # ever fails, log replay silently diverges from the original run.
    first = largest_remainder(101, [7, 7, 7, 7, 7, 7])
    for _ in range(50):
        assert largest_remainder(101, [7, 7, 7, 7, 7, 7]) == first


def test_unequal_weights_follow_the_weights():
    assert largest_remainder(100, [1, 3]) == [25, 75]
    # 100 split 1:1:1 -> 33.33 each, shortfall of one unit to the lowest index.
    assert largest_remainder(100, [1, 1, 1]) == [34, 33, 33]


def test_alternative_interest_allocation_from_ambiguities_item_6():
    # The rejected alternative policy: round the exact total (1.018 -> 1.02),
    # then allocate 102 minor units across the six days in proportion to their
    # exact accruals of 0.10 / 0.10 / 0.26 / 0.186 / 0.186 / 0.186, scaled to
    # integers. Three days tie at a remainder of .639, so the tie-break decides
    # which two of Days 4, 5 and 6 round up.
    weights = [50, 50, 130, 93, 93, 93]  # exact accruals x 500
    assert largest_remainder(102, weights) == [10, 10, 26, 19, 19, 18]


def test_zero_total_allocates_nothing():
    assert largest_remainder(0, [1, 2, 3]) == [0, 0, 0]


def test_invalid_inputs_are_refused():
    with pytest.raises(ValueError):
        largest_remainder(-1, [1])
    with pytest.raises(ValueError):
        largest_remainder(10, [])
    with pytest.raises(ValueError):
        largest_remainder(10, [0, 0])
    with pytest.raises(ValueError):
        largest_remainder(10, [1, -1])
    with pytest.raises(TypeError):
        largest_remainder(10.0, [1])  # type: ignore[arg-type]
