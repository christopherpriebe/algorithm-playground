"""Seeded sorting input generators; each one is also a benchmark distribution.

Every generator takes a :class:`random.Random` and a size, draws all of its
randomness from that generator, accepts size 0, and returns values within the
i32 range. The first one, ``uniform``, is the default.
"""

from __future__ import annotations

import random
from math import isqrt

from algorithm_playground.core.cases import InputGenerator
from algorithm_playground.problems.sorting.codec import I32_MAX, I32_MIN

FEW_UNIQUE_VALUE_COUNT = 8
SMALL_RANGE_BOUND = 10
NEARLY_SORTED_REACH = 4


def sorting_generators() -> tuple[InputGenerator[list[int]], ...]:
    """Return the sorting generators, the default first."""
    return (
        InputGenerator(
            "uniform", "values drawn uniformly from the whole i32 range", generate_uniform
        ),
        InputGenerator("sorted", "uniform values in ascending order", generate_sorted),
        InputGenerator("reversed", "uniform values in descending order", generate_reversed),
        InputGenerator(
            "nearly_sorted",
            "ascending order with about 1% of the elements swapped with a close neighbor",
            generate_nearly_sorted,
        ),
        InputGenerator(
            "few_unique",
            f"values taken from a set of {FEW_UNIQUE_VALUE_COUNT} random values",
            generate_few_unique,
        ),
        InputGenerator("all_equal", "one random value repeated", generate_all_equal),
        InputGenerator(
            "sawtooth",
            "the same ascending run repeated, about the square root of the size long",
            generate_sawtooth,
        ),
        InputGenerator(
            "organ_pipe", "ascending up to the middle, then descending", generate_organ_pipe
        ),
        InputGenerator(
            "median_of_three_killer",
            "Musser's sequence that makes median-of-three quicksort take quadratic time",
            generate_median_of_three_killer,
        ),
        InputGenerator(
            "small_range",
            f"values between {-SMALL_RANGE_BOUND} and {SMALL_RANGE_BOUND}, so many duplicates",
            generate_small_range,
        ),
    )


def generate_uniform(random_generator: random.Random, size: int) -> list[int]:
    """Draw ``size`` values uniformly from the whole i32 range."""
    return [random_generator.randint(I32_MIN, I32_MAX) for _ in range(size)]


def generate_sorted(random_generator: random.Random, size: int) -> list[int]:
    """Return uniform values in ascending order."""
    return sorted(generate_uniform(random_generator, size))


def generate_reversed(random_generator: random.Random, size: int) -> list[int]:
    """Return uniform values in descending order."""
    return sorted(generate_uniform(random_generator, size), reverse=True)


def generate_nearly_sorted(random_generator: random.Random, size: int) -> list[int]:
    """Return ascending values after about 1% of the positions swapped with a close neighbor.

    There are ``size // 100`` swaps (at least one when ``size > 1``). Each
    swaps a random position with another one at most ``NEARLY_SORTED_REACH``
    positions away, so every element ends up near its place and insertion sort
    does about linear work on the result.
    """
    values = generate_sorted(random_generator, size)
    if size < 2:
        return values
    for _ in range(max(1, size // 100)):
        first = random_generator.randrange(size)
        neighbors = [
            position
            for position in range(
                max(0, first - NEARLY_SORTED_REACH), min(size, first + NEARLY_SORTED_REACH + 1)
            )
            if position != first
        ]
        second = random_generator.choice(neighbors)
        values[first], values[second] = values[second], values[first]
    return values


def generate_few_unique(random_generator: random.Random, size: int) -> list[int]:
    """Return values chosen at random from a pool of a few uniform values."""
    pool = generate_uniform(random_generator, FEW_UNIQUE_VALUE_COUNT)
    return [random_generator.choice(pool) for _ in range(size)]


def generate_all_equal(random_generator: random.Random, size: int) -> list[int]:
    """Return one uniform value repeated ``size`` times."""
    value = random_generator.randint(I32_MIN, I32_MAX)
    return [value] * size


def generate_sawtooth(random_generator: random.Random, size: int) -> list[int]:
    """Return one ascending run of about ``sqrt(size)`` uniform values, repeated to ``size``."""
    run = generate_sorted(random_generator, max(1, isqrt(size)))
    return [run[index % len(run)] for index in range(size)]


def generate_organ_pipe(random_generator: random.Random, size: int) -> list[int]:
    """Return ascending values up to the middle followed by the same values descending."""
    rising = generate_sorted(random_generator, (size + 1) // 2)
    return rising + rising[: size // 2][::-1]


def generate_small_range(random_generator: random.Random, size: int) -> list[int]:
    """Draw ``size`` values between ``-10`` and ``10``."""
    return [random_generator.randint(-SMALL_RANGE_BOUND, SMALL_RANGE_BOUND) for _ in range(size)]


def generate_median_of_three_killer(random_generator: random.Random, size: int) -> list[int]:
    """Return the median-of-three killer of ``size`` elements, spread evenly over the i32 range.

    The sequence is a permutation of ranks, so its values are evenly spaced
    i32 values in the order of :func:`median_of_three_killer_ranks`. The seed
    is not used: the sequence is fixed for a size.
    """
    ranks = median_of_three_killer_ranks(size)
    step = (I32_MAX - I32_MIN) // max(size - 1, 1)
    return [I32_MIN + (rank - 1) * step for rank in ranks]


def median_of_three_killer_ranks(size: int) -> list[int]:
    """Return a permutation of ``1..size`` that makes median-of-three quicksort quadratic.

    The construction is Musser's (*Introspective Sorting and Selection
    Algorithms*, 1997). For a size ``2k`` with ``k`` even it is::

        1, k+1, 3, k+3, 5, k+5, ..., k-1, 2k-1, 2, 4, 6, ..., 2k

    that is, the odd numbers below ``k`` alternate with the odd numbers above
    ``k`` in the first half, and the second half lists the even numbers. The
    pivot rule it defeats is the median of the first element, the middle
    element (at ``first + (last - first) // 2``) and the last element of the
    range: it finds ``1``, ``2``, and ``2k`` there, so the pivot is ``2`` and
    the smallest element is split off together with the pivot. The partition
    step leaves the rest in the same shape, so each of the ``k`` rounds
    removes only two elements and the total work is quadratic. That is exact
    for a Hoare partition that sweeps inwards from both ends, as in the
    original SGI standard template library and Musser's paper. The sequence
    is also quadratic against the variant that libstdc++'s ``std::sort`` has
    used for years, the median of the second, the middle and the second to
    last element moved to the front before a Hoare partition of the rest: in
    a measurement of both with insertion sort cut off at 16 elements, the
    number of comparisons grew about fourfold for every doubling of the size
    between 2000 and 8000 elements, against slightly more than twofold
    for random input. A Lomuto partition with the pivot moved to the end also degrades
    to quadratic time, with a smaller constant.

    Other sizes are derived from that one:

    * A size that is not a multiple of four takes the sequence of the next
      multiple of four and drops the values above ``size``.
    * An odd size appends ``size`` to the sequence of ``size - 1``. The extra
      largest element goes last, so the median of three keeps seeing the
      same first and middle elements.
    """
    if size < 0:
        raise ValueError(f"The size must not be negative, got {size}")
    if size % 2 == 1:
        return [*median_of_three_killer_ranks(size - 1), size]
    multiple = -(-size // 4) * 4
    return [rank for rank in _musser_sequence(multiple) if rank <= size]


def _musser_sequence(size: int) -> list[int]:
    """Return Musser's sequence for a size that is a multiple of four (or zero)."""
    half = size // 2
    first_half = [
        position if position % 2 == 1 else half + position - 1 for position in range(1, half + 1)
    ]
    return first_half + [2 * position for position in range(1, half + 1)]
