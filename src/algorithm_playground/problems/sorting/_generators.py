"""Seeded sorting input generators; each one is also a benchmark distribution.

Every generator takes a :class:`random.Random` and a size, draws all of its
randomness from that generator, accepts size 0, and returns values within the
i32 range. The first one, ``uniform``, is the default.
"""

import random
from math import isqrt

from algorithm_playground.core._cases import InputGenerator
from algorithm_playground.problems.sorting._codec import I32_MAX, I32_MIN

__all__ = [
    "FEW_UNIQUE_VALUE_COUNT",
    "NEARLY_SORTED_REACH",
    "SMALL_RANGE_BOUND",
    "build_sorting_generators",
    "compute_median_of_three_killer_ranks",
    "generate_all_equal",
    "generate_few_unique",
    "generate_median_of_three_killer",
    "generate_nearly_sorted",
    "generate_organ_pipe",
    "generate_reversed",
    "generate_sawtooth",
    "generate_small_range",
    "generate_sorted",
    "generate_uniform",
]

FEW_UNIQUE_VALUE_COUNT = 8
SMALL_RANGE_BOUND = 10
NEARLY_SORTED_REACH = 4
MINIMUM_SIZE_TO_SWAP = 2


def _list_close_positions(position: int, size: int) -> list[int]:
    """List the other positions at most ``NEARLY_SORTED_REACH`` away, within an array of ``size``.

    Returns:
        The positions near ``position``.
    """
    return [
        neighbor
        for neighbor in range(
            max(0, position - NEARLY_SORTED_REACH),
            min(size, position + NEARLY_SORTED_REACH + 1),
        )
        if neighbor != position
    ]


def _build_musser_sequence(size: int) -> list[int]:
    """Return Musser's sequence for a size that is a multiple of four (or zero)."""
    half = size // 2
    first_half = [
        position if position % 2 == 1 else half + position - 1
        for position in range(1, half + 1)
    ]
    return first_half + [2 * position for position in range(1, half + 1)]


def build_sorting_generators() -> tuple[InputGenerator[list[int]], ...]:
    """Return the sorting generators, the default first."""
    return (
        InputGenerator(
            "uniform",
            description="values drawn uniformly from the whole i32 range",
            generate=generate_uniform,
        ),
        InputGenerator(
            "sorted",
            description="uniform values in ascending order",
            generate=generate_sorted,
        ),
        InputGenerator(
            "reversed",
            description="uniform values in descending order",
            generate=generate_reversed,
        ),
        InputGenerator(
            "nearly_sorted",
            description="ascending order with about 1% of the elements swapped with a close neighbor",
            generate=generate_nearly_sorted,
        ),
        InputGenerator(
            "few_unique",
            description=f"values taken from a set of {FEW_UNIQUE_VALUE_COUNT} random values",
            generate=generate_few_unique,
        ),
        InputGenerator(
            "all_equal",
            description="one random value repeated",
            generate=generate_all_equal,
        ),
        InputGenerator(
            "sawtooth",
            description="the same ascending run repeated, about the square root of the size long",
            generate=generate_sawtooth,
        ),
        InputGenerator(
            "organ_pipe",
            description="ascending up to the middle, then descending",
            generate=generate_organ_pipe,
        ),
        InputGenerator(
            "median_of_three_killer",
            description="Musser's sequence that makes median-of-three quicksort take quadratic time",
            generate=generate_median_of_three_killer,
        ),
        InputGenerator(
            "small_range",
            description=f"values between {-SMALL_RANGE_BOUND} and {SMALL_RANGE_BOUND}, so many duplicates",
            generate=generate_small_range,
        ),
    )


def generate_uniform(random_generator: random.Random, size: int) -> list[int]:
    """Draw values uniformly from the whole i32 range.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` random values.
    """
    return [random_generator.randint(I32_MIN, I32_MAX) for _ in range(size)]


def generate_sorted(random_generator: random.Random, size: int) -> list[int]:
    """Draw uniform values and put them in ascending order.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` values in ascending order.
    """
    return sorted(generate_uniform(random_generator, size))


def generate_reversed(random_generator: random.Random, size: int) -> list[int]:
    """Draw uniform values and put them in descending order.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` values in descending order.
    """
    return sorted(generate_uniform(random_generator, size), reverse=True)


def generate_nearly_sorted(random_generator: random.Random, size: int) -> list[int]:
    """Draw ascending values, then swap about 1% of the positions with a close neighbor.

    There are ``size // 100`` swaps (at least one when ``size > 1``). Each
    swaps a random position with another one at most ``NEARLY_SORTED_REACH``
    positions away, so every element ends up near its place and insertion sort
    does about linear work on the result.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` values that are nearly in ascending order.
    """
    values = generate_sorted(random_generator, size)
    if size < MINIMUM_SIZE_TO_SWAP:
        return values
    for _ in range(max(1, size // 100)):
        first = random_generator.randrange(size)
        second = random_generator.choice(_list_close_positions(first, size))
        values[first], values[second] = values[second], values[first]
    return values


def generate_few_unique(random_generator: random.Random, size: int) -> list[int]:
    """Choose values at random from a pool of a few uniform values.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` values taken from ``FEW_UNIQUE_VALUE_COUNT`` distinct candidates.
    """
    pool = generate_uniform(random_generator, FEW_UNIQUE_VALUE_COUNT)
    return [random_generator.choice(pool) for _ in range(size)]


def generate_all_equal(random_generator: random.Random, size: int) -> list[int]:
    """Repeat one uniform value.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` copies of one value.
    """
    value = random_generator.randint(I32_MIN, I32_MAX)
    return [value] * size


def generate_sawtooth(random_generator: random.Random, size: int) -> list[int]:
    """Repeat one ascending run of about ``sqrt(size)`` uniform values.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` values made of the run repeated and cut off at ``size``.
    """
    run = generate_sorted(random_generator, max(1, isqrt(size)))
    return [run[index % len(run)] for index in range(size)]


def generate_organ_pipe(random_generator: random.Random, size: int) -> list[int]:
    """Draw ascending values up to the middle, followed by the same values descending.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` values that rise to the middle and fall again.
    """
    rising = generate_sorted(random_generator, (size + 1) // 2)
    return rising + rising[: size // 2][::-1]


def generate_small_range(random_generator: random.Random, size: int) -> list[int]:
    """Draw values between ``-SMALL_RANGE_BOUND`` and ``SMALL_RANGE_BOUND``.

    Args:
        random_generator: The source of all randomness.
        size: The number of values.

    Returns:
        ``size`` small values, so many of them are equal.
    """
    return [
        random_generator.randint(-SMALL_RANGE_BOUND, SMALL_RANGE_BOUND)
        for _ in range(size)
    ]


def generate_median_of_three_killer(
    random_generator: random.Random,  # noqa: ARG001  every generator takes the random source
    size: int,
) -> list[int]:
    """Spread the median-of-three killer evenly over the i32 range.

    The sequence is a permutation of ranks, so its values are evenly spaced
    i32 values in the order of :func:`compute_median_of_three_killer_ranks`.

    Args:
        random_generator: Not used: the sequence is fixed for a size.
        size: The number of values.

    Returns:
        ``size`` values that make median-of-three quicksort take quadratic time.
    """
    ranks = compute_median_of_three_killer_ranks(size)
    step = (I32_MAX - I32_MIN) // max(size - 1, 1)
    return [I32_MIN + (rank - 1) * step for rank in ranks]


def compute_median_of_three_killer_ranks(size: int) -> list[int]:
    """Build a permutation of ``1..size`` that makes median-of-three quicksort quadratic.

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
    for a Hoare partition that sweeps inwards from both ends, as in
    Musser's paper. The sequence is also quadratic against the median of the
    second, the middle and the second to last element (the variant of
    libstdc++'s ``std::sort``) and against a Lomuto partition, which has a
    smaller constant.

    Other sizes are derived from that one:

    * A size that is not a multiple of four takes the sequence of the next
      multiple of four and drops the values above ``size``.
    * An odd size appends ``size`` to the sequence of ``size - 1``. The extra
      largest element goes last, so the median of three keeps seeing the
      same first and middle elements.

    Args:
        size: The number of ranks.

    Returns:
        The ranks ``1..size`` in the order of the killer sequence.

    Raises:
        ValueError: If ``size`` is negative.
    """
    if size < 0:
        message = f"The size must not be negative, got {size}"
        raise ValueError(message)
    if size % 2 == 1:
        return [*compute_median_of_three_killer_ranks(size - 1), size]
    multiple = -(-size // 4) * 4
    return [rank for rank in _build_musser_sequence(multiple) if rank <= size]
