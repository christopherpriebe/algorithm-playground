"""Tests for the generators of sorting inputs."""

import random

import pytest

from algorithm_playground.core import InputGenerator, generate_case
from algorithm_playground.problems.sorting import (
    I32_MAX,
    I32_MIN,
    SortingProblem,
    build_sorting_generators,
    compute_median_of_three_killer_ranks,
)

GENERATORS = {generator.name: generator for generator in build_sorting_generators()}


SIZES = (0, 1, 2, 3, 4, 5, 10, 33, 100, 257)


def generate_values(name: str, size: int, seed: int = 0) -> list[int]:
    """Generate the input of the named generator for a size and seed."""
    return generate_case(GENERATORS[name], size=size, seed=seed).input_data


def count_inversions(values: list[int]) -> int:
    """Count the pairs of values that are out of order."""
    return sum(
        1
        for index, value in enumerate(values)
        for later in values[index + 1 :]
        if later < value
    )


def count_libstdcxx_comparisons(values: list[int]) -> int:
    """Count the comparisons of the quicksort variant of libstdc++ (cutoff 16, no final sort)."""
    array = list(values)
    comparisons = 0

    def is_less(first: int, second: int) -> bool:
        nonlocal comparisons
        comparisons += 1
        return array[first] < array[second]

    def move_median_to_first(result: int, first: int, second: int, third: int) -> None:
        if is_less(first, second):
            if is_less(second, third):
                chosen = second
            elif is_less(first, third):
                chosen = third
            else:
                chosen = first
        elif is_less(first, third):
            chosen = first
        elif is_less(second, third):
            chosen = third
        else:
            chosen = second
        array[result], array[chosen] = array[chosen], array[result]

    def partition(low: int, high: int, pivot: int) -> int:
        while True:
            while is_less(low, pivot):
                low += 1
            high -= 1
            while is_less(pivot, high):
                high -= 1
            if low >= high:
                return low
            array[low], array[high] = array[high], array[low]
            low += 1

    pending = [(0, len(array))]
    while pending:
        low, high = pending.pop()
        while high - low > 16:
            move_median_to_first(low, low + 1, low + (high - low) // 2, high - 1)
            cut = partition(low + 1, high, low)
            pending.append((cut, high))
            high = cut
    return comparisons


def count_median_of_three_quicksort_comparisons(values: list[int]) -> int:
    """Count the comparisons of the quicksort Musser's sequence is built against.

    The pivot is the median of the first, middle, and last element, and the
    partition sweeps inwards from both ends (the C++ standard library's).
    """
    array = list(values)
    comparisons = 0

    def partition(low: int, high: int, pivot: int) -> int:
        nonlocal comparisons
        left, right = low, high
        while True:
            while True:
                comparisons += 1
                if array[left] >= pivot:
                    break
                left += 1
            right -= 1
            while True:
                comparisons += 1
                if pivot >= array[right]:
                    break
                right -= 1
            if left >= right:
                return left
            array[left], array[right] = array[right], array[left]
            left += 1

    def sort(low: int, high: int) -> None:
        while high - low > 1:
            first, middle, last = (
                array[low],
                array[low + (high - low) // 2],
                array[high - 1],
            )
            pivot = sorted((first, middle, last))[1]
            cut = partition(low, high, pivot)
            sort(cut, high)
            high = cut

    sort(0, len(array))
    return comparisons


def test_the_generators_are_the_documented_ones_with_uniform_first() -> None:
    """Test the problem defines the documented generators with the uniform one first."""
    names = [generator.name for generator in SortingProblem().generators()]

    assert names == [
        "uniform",
        "sorted",
        "reversed",
        "nearly_sorted",
        "few_unique",
        "all_equal",
        "sawtooth",
        "organ_pipe",
        "median_of_three_killer",
        "small_range",
    ]


@pytest.mark.parametrize(
    "generator", build_sorting_generators(), ids=lambda generator: generator.name
)
def test_every_generator_has_a_one_line_description(
    generator: InputGenerator[list[int]],
) -> None:
    """Test every generator has a description that fits on one line."""
    assert generator.description
    assert "\n" not in generator.description


@pytest.mark.parametrize(
    "generator", build_sorting_generators(), ids=lambda generator: generator.name
)
@pytest.mark.parametrize("size", SIZES)
def test_it_returns_exactly_size_values(
    generator: InputGenerator[list[int]], size: int
) -> None:
    """Test the generator returns exactly as many values as requested."""
    values = generator.generate(random.Random(7), size)  # noqa: S311  seeded generator for reproducible inputs, not cryptography

    assert len(values) == size


@pytest.mark.parametrize(
    "generator", build_sorting_generators(), ids=lambda generator: generator.name
)
@pytest.mark.parametrize("size", SIZES)
def test_it_returns_values_within_the_i32_range(
    generator: InputGenerator[list[int]], size: int
) -> None:
    """Test every generated value fits in a 32-bit signed integer."""
    values = generator.generate(random.Random(7), size)  # noqa: S311  seeded generator for reproducible inputs, not cryptography

    assert all(I32_MIN <= value <= I32_MAX for value in values)


@pytest.mark.parametrize(
    "generator", build_sorting_generators(), ids=lambda generator: generator.name
)
def test_it_returns_the_empty_list_for_size_zero(
    generator: InputGenerator[list[int]],
) -> None:
    """Test the generator returns the empty list for size zero."""
    assert generator.generate(random.Random(7), 0) == []  # noqa: S311  seeded generator for reproducible inputs, not cryptography


@pytest.mark.parametrize(
    "generator", build_sorting_generators(), ids=lambda generator: generator.name
)
@pytest.mark.parametrize("size", SIZES)
def test_it_is_deterministic_for_a_seed(
    generator: InputGenerator[list[int]], size: int
) -> None:
    """Test two generators seeded alike produce the same values."""
    first = generator.generate(random.Random(11), size)  # noqa: S311  seeded generator for reproducible inputs, not cryptography
    second = generator.generate(random.Random(11), size)  # noqa: S311  seeded generator for reproducible inputs, not cryptography

    assert first == second


@pytest.mark.parametrize(
    "generator", build_sorting_generators(), ids=lambda generator: generator.name
)
def test_it_draws_all_of_its_randomness_from_the_generator_it_is_given(
    generator: InputGenerator[list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test the generator never uses the global random number generator."""

    def fail_on_global_random(
        *_arguments: object, **_keyword_arguments: object
    ) -> None:
        message = "used the global random generator"
        raise AssertionError(message)

    for function in (
        "random",
        "randint",
        "randrange",
        "choice",
        "choices",
        "shuffle",
        "sample",
    ):
        monkeypatch.setattr(random, function, fail_on_global_random)

    values = generator.generate(random.Random(3), 20)  # noqa: S311  seeded generator for reproducible inputs, not cryptography

    assert len(values) == 20


@pytest.mark.parametrize(
    "name", [name for name in GENERATORS if name != "median_of_three_killer"]
)
def test_the_seed_changes_the_values(name: str) -> None:
    """Test generating with different seeds gives different values."""
    first = generate_values(name, 64, seed=1)
    second = generate_values(name, 64, seed=2)

    assert first != second


def test_sorted_is_ascending() -> None:
    """Test the sorted generator returns values in ascending order."""
    values = generate_values("sorted", 200)

    assert values == sorted(values)


def test_reversed_is_descending() -> None:
    """Test the reversed generator returns values in descending order."""
    values = generate_values("reversed", 200)

    assert values == sorted(values, reverse=True)
    assert values != sorted(values)


def test_nearly_sorted_has_few_elements_out_of_place() -> None:
    """Test the nearly sorted generator leaves only a few elements out of place."""
    values = generate_values("nearly_sorted", 1000)

    misplaced = sum(
        value != ordered for value, ordered in zip(values, sorted(values), strict=True)
    )

    assert 0 < misplaced <= 2 * (1000 // 100)


@pytest.mark.parametrize("seed", range(5))
def test_nearly_sorted_moves_every_element_only_a_few_positions(seed: int) -> None:
    """Test no element of the nearly sorted generator is more than four positions away."""
    values = generate_values("nearly_sorted", 1000, seed)
    position_in_order = {value: index for index, value in enumerate(sorted(values))}

    distances = [
        abs(position_in_order[value] - index) for index, value in enumerate(values)
    ]

    assert max(distances) <= 4


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("size", [100, 1000])
def test_nearly_sorted_leaves_insertion_sort_about_linear_work(
    size: int, seed: int
) -> None:
    """Test the nearly sorted generator has few inversions, so insertion sort is near linear."""
    # The work of insertion sort is the number of inversions plus the length. Each swap
    # of neighbors at most four apart adds at most seven inversions.
    swaps = size // 100

    inversions = count_inversions(generate_values("nearly_sorted", size, seed))

    assert inversions <= 7 * swaps


@pytest.mark.parametrize("size", [2, 3, 4, 5, 8])
def test_nearly_sorted_is_not_sorted_at_small_sizes_either(size: int) -> None:
    """Test the nearly sorted generator produces an unsorted array for some seed."""
    inputs = [generate_values("nearly_sorted", size, seed) for seed in range(10)]

    assert any(values != sorted(values) for values in inputs), size


@pytest.mark.parametrize("size", range(2, 40))
def test_nearly_sorted_swaps_never_leave_the_array(size: int) -> None:
    """Test the nearly sorted generator only permutes the values of the sorted array."""
    for seed in range(5):
        values = generate_values("nearly_sorted", size, seed)

        assert sorted(values) == sorted(generate_values("sorted", size, seed))


def test_nearly_sorted_swaps_at_least_once_for_small_sizes() -> None:
    """Test the nearly sorted generator swaps something for some seed at size ten."""
    inputs = [generate_values("nearly_sorted", 10, seed) for seed in range(5)]

    assert any(values != sorted(values) for values in inputs)


def test_few_unique_draws_from_a_small_set() -> None:
    """Test the few unique generator draws from a small set of values."""
    values = generate_values("few_unique", 500)

    assert 2 < len(set(values)) <= 8


def test_all_equal_repeats_one_value() -> None:
    """Test the all equal generator repeats a single value."""
    assert len(set(generate_values("all_equal", 50))) == 1


def test_small_range_stays_between_minus_ten_and_ten() -> None:
    """Test the small range generator stays between minus ten and ten."""
    values = generate_values("small_range", 500)

    assert min(values) >= -10
    assert max(values) <= 10


def test_small_range_uses_many_distinct_values() -> None:
    """Test the small range generator uses more than five distinct values."""
    values = generate_values("small_range", 500)

    assert len(set(values)) > 5


def test_sawtooth_repeats_one_ascending_run() -> None:
    """Test the sawtooth generator repeats one ascending run of ten values."""
    values = generate_values("sawtooth", 100)
    run = values[:10]

    assert run == sorted(run)
    assert values == run * 10


def test_sawtooth_with_a_size_that_is_not_a_multiple_of_the_run() -> None:
    """Test the sawtooth generator ends with a partial run for other sizes."""
    values = generate_values("sawtooth", 23)

    assert len(values) == 23
    assert values[:4] == sorted(values[:4])
    assert values[4:8] == values[:4]


@pytest.mark.parametrize("size", [7, 8])
def test_organ_pipe_rises_then_falls(size: int) -> None:
    """Test the organ pipe generator rises to a peak near the middle and then falls."""
    values = generate_values("organ_pipe", size)
    peak = values.index(max(values))

    assert values[: peak + 1] == sorted(values[: peak + 1])
    assert values[peak:] == sorted(values[peak:], reverse=True)
    assert peak in (size // 2 - 1, size // 2, size // 2 + 1)


@pytest.mark.parametrize("size", [*range(70), 100, 1000, 4097, 4098, 4099, 4100])
def test_the_ranks_are_a_permutation(size: int) -> None:
    """Test the ranks are a permutation of one to the size."""
    assert sorted(compute_median_of_three_killer_ranks(size)) == list(
        range(1, size + 1)
    )


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (8, [1, 5, 3, 7, 2, 4, 6, 8]),
        (16, [*(1, 9, 3, 11, 5, 13, 7, 15), *(2, 4, 6, 8, 10, 12, 14, 16)]),
    ],
    ids=["eight", "sixteen"],
)
def test_the_ranks_for_a_multiple_of_four_are_musser_sequence(
    size: int, expected: list[int]
) -> None:
    """Test the ranks for a multiple of four are the sequence of Musser."""
    assert compute_median_of_three_killer_ranks(size) == expected


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (6, [1, 5, 3, 2, 4, 6]),
        (9, [*compute_median_of_three_killer_ranks(8), 9]),
        (1, [1]),
        (0, []),
    ],
    ids=["six", "nine-extends-eight", "one", "zero"],
)
def test_other_sizes_are_derived_from_it(size: int, expected: list[int]) -> None:
    """Test the ranks for other sizes are derived from the sequence of Musser."""
    assert compute_median_of_three_killer_ranks(size) == expected


def test_a_negative_size_is_rejected() -> None:
    """Test a negative size is rejected."""
    with pytest.raises(ValueError, match="negative"):
        compute_median_of_three_killer_ranks(-1)


def test_it_is_deterministic() -> None:
    """Test the generator returns the same values for the same seed."""
    first = generate_values("median_of_three_killer", 300, seed=1)
    second = generate_values("median_of_three_killer", 300, seed=1)

    assert first == second


def test_it_ignores_the_seed() -> None:
    """Test the generator returns the same values for different seeds."""
    first = generate_values("median_of_three_killer", 300, seed=1)
    second = generate_values("median_of_three_killer", 300, seed=2)

    assert first == second


@pytest.mark.parametrize("size", [1, 2, 3, 10, 301])
def test_the_values_are_distinct(size: int) -> None:
    """Test the generated values are all different."""
    values = generate_values("median_of_three_killer", size)

    assert len(set(values)) == size


@pytest.mark.parametrize("size", [1, 2, 3, 10, 301])
def test_the_values_are_in_the_order_of_the_ranks(size: int) -> None:
    """Test the generated values order the positions as the ranks do."""
    values = generate_values("median_of_three_killer", size)
    ranks = compute_median_of_three_killer_ranks(size)

    assert sorted(range(size), key=values.__getitem__) == sorted(
        range(size), key=ranks.__getitem__
    )


def test_the_values_span_the_i32_range() -> None:
    """Test the generated values reach both ends of the 32-bit range."""
    values = generate_values("median_of_three_killer", 1000)

    assert min(values) == I32_MIN
    assert max(values) > I32_MAX - 2**22


@pytest.mark.parametrize("size", [512, 513, 514, 515])
def test_it_makes_median_of_three_quicksort_quadratic(size: int) -> None:
    """Test median of three quicksort needs quadratically many comparisons on the input."""
    killer = count_median_of_three_quicksort_comparisons(
        generate_values("median_of_three_killer", size)
    )
    uniform = count_median_of_three_quicksort_comparisons(
        generate_values("uniform", size)
    )

    assert killer > 4 * uniform
    assert killer > size * size // 8


@pytest.mark.parametrize("size", [512, 1024])
def test_it_is_also_quadratic_for_the_median_of_the_second_middle_and_second_to_last(
    size: int,
) -> None:
    """Test the libstdc++ quicksort variant also needs quadratically many comparisons."""
    # The variant of libstdc++'s std::sort: that median is moved to the front and the
    # rest is partitioned from the second position. Its constant is smaller (n^2 / 14).
    killer = count_libstdcxx_comparisons(
        generate_values("median_of_three_killer", size)
    )
    uniform = count_libstdcxx_comparisons(generate_values("uniform", size))

    assert killer > 3 * uniform
    assert killer > size * size // 16


def test_that_variant_grows_about_fourfold_when_the_size_doubles() -> None:
    """Test the comparisons of the libstdc++ variant about quadruple when the size doubles."""
    small = count_libstdcxx_comparisons(generate_values("median_of_three_killer", 512))
    large = count_libstdcxx_comparisons(generate_values("median_of_three_killer", 1024))

    assert large > 3.5 * small


def test_the_cost_grows_quadratically_with_the_size() -> None:
    """Test the comparisons of median of three quicksort quadruple when the size doubles."""
    small = count_median_of_three_quicksort_comparisons(
        generate_values("median_of_three_killer", 400)
    )
    large = count_median_of_three_quicksort_comparisons(
        generate_values("median_of_three_killer", 800)
    )

    assert large > 3.5 * small


@pytest.mark.parametrize("name", ["uniform", "sorted", "reversed", "organ_pipe"])
def test_the_other_distributions_do_not_hurt_it(name: str) -> None:
    """Test median of three quicksort stays well below quadratic on the other distributions."""
    comparisons = count_median_of_three_quicksort_comparisons(
        generate_values(name, 512)
    )

    assert comparisons < 512 * 512 // 8
