"""Hand-written sorting inputs: small cases where a failure is easy to understand."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import permutations

from algorithm_playground.core.cases import Fixture
from algorithm_playground.problems.sorting.codec import I32_MAX, I32_MIN

BOUNDARY_LENGTHS = (15, 16, 17)
BOUNDARY_STRIDE = 7  # coprime to every boundary length, so i * stride mod length is a permutation


def sorting_fixtures() -> Iterator[Fixture[list[int]]]:
    """Yield the sorting fixtures: tiny, structured, duplicated, extreme, and boundary inputs."""
    yield Fixture("empty", [], "no elements")
    yield Fixture("single", [42], "one element")
    yield Fixture("two_sorted", [1, 2], "two elements already in order")
    yield Fixture("two_unsorted", [2, 1], "two elements out of order")
    yield Fixture("two_equal", [5, 5], "two equal elements")
    for arrangement in permutations((1, 2, 3)):
        label = "".join(str(value) for value in arrangement)
        yield Fixture(f"three_{label}", list(arrangement), f"the permutation {label} of three")
    yield Fixture("already_sorted", list(range(10)), "ascending input")
    yield Fixture("reverse_sorted", list(range(9, -1, -1)), "descending input")
    yield Fixture("duplicates", [3, 1, 4, 1, 5, 9, 2, 6, 5, 3], "repeated values")
    yield Fixture("all_equal", [7] * 8, "every element equal")
    yield Fixture("alternating_two_values", [0, 1] * 5, "two values taking turns")
    yield Fixture(
        "duplicated_extremes",
        [I32_MAX, I32_MIN, I32_MAX, I32_MAX, I32_MIN, I32_MIN, I32_MAX, I32_MIN, I32_MIN, I32_MAX],
        "many copies of the smallest and largest i32 values",
    )
    yield Fixture("negatives_mixed", [-1, -5, 3, 0, -10, 7, -3, 8], "negative and positive")
    yield Fixture(
        "i32_extremes",
        [I32_MAX, I32_MIN, 0, I32_MAX - 1, I32_MIN + 1, -1, 1],
        "the smallest and largest i32 values and their neighbors",
    )
    for length in BOUNDARY_LENGTHS:
        yield Fixture(
            f"length_{length}",
            [(index * BOUNDARY_STRIDE) % length for index in range(length)],
            f"a scrambled permutation of length {length}, next to a power of two",
        )
    yield Fixture(
        "largest_first", [9, *range(9)], "sorted except that the largest element is first"
    )
    yield Fixture(
        "smallest_last", [*range(1, 10), 0], "sorted except that the smallest element is last"
    )
