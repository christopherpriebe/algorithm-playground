"""Tests for the sorting generators: determinism, bounds, shapes, and the adversary."""

from __future__ import annotations

import random

import pytest

from algorithm_playground.core.cases import InputGenerator, generate_case
from algorithm_playground.problems.sorting import SortingProblem
from algorithm_playground.problems.sorting.codec import I32_MAX, I32_MIN
from algorithm_playground.problems.sorting.generators import (
    median_of_three_killer_ranks,
    sorting_generators,
)

GENERATORS = {generator.name: generator for generator in sorting_generators()}
SIZES = (0, 1, 2, 3, 4, 5, 10, 33, 100, 257)


def generate(name: str, size: int, seed: int = 0) -> list[int]:
    return generate_case(GENERATORS[name], size=size, seed=seed).input_data


def count_inversions(values: list[int]) -> int:
    return sum(
        1 for index, value in enumerate(values) for later in values[index + 1 :] if later < value
    )


def libstdcxx_comparisons(values: list[int]) -> int:
    """Count the comparisons of the quicksort variant of libstdc++ (cutoff 16, no final sort)."""
    array = list(values)
    comparisons = 0

    def less(first: int, second: int) -> bool:
        nonlocal comparisons
        comparisons += 1
        return array[first] < array[second]

    def move_median_to_first(result: int, first: int, second: int, third: int) -> None:
        if less(first, second):
            if less(second, third):
                chosen = second
            elif less(first, third):
                chosen = third
            else:
                chosen = first
        elif less(first, third):
            chosen = first
        elif less(second, third):
            chosen = third
        else:
            chosen = second
        array[result], array[chosen] = array[chosen], array[result]

    def partition(low: int, high: int, pivot: int) -> int:
        while True:
            while less(low, pivot):
                low += 1
            high -= 1
            while less(pivot, high):
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


def median_of_three_quicksort_comparisons(values: list[int]) -> int:
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
            first, middle, last = array[low], array[low + (high - low) // 2], array[high - 1]
            pivot = sorted((first, middle, last))[1]
            cut = partition(low, high, pivot)
            sort(cut, high)
            high = cut

    sort(0, len(array))
    return comparisons


class TestTheGeneratorList:
    def test_the_generators_are_the_documented_ones_with_uniform_first(self) -> None:
        assert [generator.name for generator in SortingProblem().generators()] == [
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

    def test_every_generator_has_a_one_line_description(self) -> None:
        for generator in sorting_generators():
            assert generator.description
            assert "\n" not in generator.description


@pytest.mark.parametrize("generator", sorting_generators(), ids=lambda generator: generator.name)
class TestEveryGenerator:
    def test_it_returns_exactly_size_values_within_the_i32_range(
        self, generator: InputGenerator[list[int]]
    ) -> None:
        for size in SIZES:
            values = generator.generate(random.Random(7), size)
            assert len(values) == size
            assert all(I32_MIN <= value <= I32_MAX for value in values)

    def test_it_returns_the_empty_list_for_size_zero(
        self, generator: InputGenerator[list[int]]
    ) -> None:
        assert generator.generate(random.Random(7), 0) == []

    def test_it_is_deterministic_for_a_seed(self, generator: InputGenerator[list[int]]) -> None:
        for size in SIZES:
            assert generator.generate(random.Random(11), size) == generator.generate(
                random.Random(11), size
            )

    def test_it_draws_all_of_its_randomness_from_the_generator_it_is_given(
        self, generator: InputGenerator[list[int]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*arguments: object, **keyword_arguments: object) -> None:
            raise AssertionError("used the global random generator")

        for function in (
            "random",
            "randint",
            "randrange",
            "choice",
            "choices",
            "shuffle",
            "sample",
        ):
            monkeypatch.setattr(random, function, forbidden)
        assert len(generator.generate(random.Random(3), 20)) == 20


@pytest.mark.parametrize("name", [name for name in GENERATORS if name != "median_of_three_killer"])
def test_the_seed_changes_the_values(name: str) -> None:
    assert generate(name, 64, seed=1) != generate(name, 64, seed=2)


class TestShapes:
    def test_sorted_is_ascending(self) -> None:
        values = generate("sorted", 200)
        assert values == sorted(values)

    def test_reversed_is_descending(self) -> None:
        values = generate("reversed", 200)
        assert values == sorted(values, reverse=True)
        assert values != sorted(values)

    def test_nearly_sorted_has_few_elements_out_of_place(self) -> None:
        values = generate("nearly_sorted", 1000)
        misplaced = sum(
            value != ordered for value, ordered in zip(values, sorted(values), strict=True)
        )
        assert 0 < misplaced <= 2 * (1000 // 100)

    @pytest.mark.parametrize("seed", range(5))
    def test_nearly_sorted_moves_every_element_only_a_few_positions(self, seed: int) -> None:
        values = generate("nearly_sorted", 1000, seed)
        position_in_order = {value: index for index, value in enumerate(sorted(values))}
        assert max(abs(position_in_order[value] - index) for index, value in enumerate(values)) <= 4

    @pytest.mark.parametrize("size", [100, 1000])
    def test_nearly_sorted_leaves_insertion_sort_about_linear_work(self, size: int) -> None:
        # The work of insertion sort is the number of inversions plus the length. Each swap
        # of neighbors at most four apart adds at most seven inversions.
        swaps = size // 100
        for seed in range(3):
            assert count_inversions(generate("nearly_sorted", size, seed)) <= 7 * swaps

    def test_nearly_sorted_is_not_sorted_at_small_sizes_either(self) -> None:
        for size in (2, 3, 4, 5, 8):
            assert any(
                generate("nearly_sorted", size, seed)
                != sorted(generate("nearly_sorted", size, seed))
                for seed in range(10)
            ), size

    def test_nearly_sorted_swaps_never_leave_the_array(self) -> None:
        for size in range(2, 40):
            for seed in range(5):
                values = generate("nearly_sorted", size, seed)
                assert sorted(values) == sorted(generate("sorted", size, seed))

    def test_nearly_sorted_swaps_at_least_once_for_small_sizes(self) -> None:
        assert any(
            generate("nearly_sorted", 10, seed) != sorted(generate("nearly_sorted", 10, seed))
            for seed in range(5)
        )

    def test_few_unique_draws_from_a_small_set(self) -> None:
        values = generate("few_unique", 500)
        assert 2 < len(set(values)) <= 8

    def test_all_equal_repeats_one_value(self) -> None:
        assert len(set(generate("all_equal", 50))) == 1

    def test_small_range_stays_between_minus_ten_and_ten(self) -> None:
        values = generate("small_range", 500)
        assert min(values) >= -10 and max(values) <= 10
        assert len(set(values)) > 5

    def test_sawtooth_repeats_one_ascending_run(self) -> None:
        values = generate("sawtooth", 100)
        run = values[:10]
        assert run == sorted(run)
        assert values == run * 10

    def test_sawtooth_with_a_size_that_is_not_a_multiple_of_the_run(self) -> None:
        values = generate("sawtooth", 23)
        assert len(values) == 23
        assert values[:4] == sorted(values[:4])
        assert values[4:8] == values[:4]

    def test_organ_pipe_rises_then_falls(self) -> None:
        for size in (7, 8):
            values = generate("organ_pipe", size)
            peak = values.index(max(values))
            assert values[: peak + 1] == sorted(values[: peak + 1])
            assert values[peak:] == sorted(values[peak:], reverse=True)
            assert peak in (size // 2 - 1, size // 2, size // 2 + 1)


class TestMedianOfThreeKiller:
    @pytest.mark.parametrize("size", range(0, 70))
    def test_the_ranks_are_a_permutation(self, size: int) -> None:
        assert sorted(median_of_three_killer_ranks(size)) == list(range(1, size + 1))

    @pytest.mark.parametrize("size", [100, 1000, 4097, 4098, 4099, 4100])
    def test_the_ranks_are_a_permutation_at_larger_sizes(self, size: int) -> None:
        assert sorted(median_of_three_killer_ranks(size)) == list(range(1, size + 1))

    def test_the_ranks_for_a_multiple_of_four_are_musser_sequence(self) -> None:
        assert median_of_three_killer_ranks(8) == [1, 5, 3, 7, 2, 4, 6, 8]
        assert median_of_three_killer_ranks(16) == [
            *(1, 9, 3, 11, 5, 13, 7, 15),
            *(2, 4, 6, 8, 10, 12, 14, 16),
        ]

    def test_other_sizes_are_derived_from_it(self) -> None:
        assert median_of_three_killer_ranks(6) == [1, 5, 3, 2, 4, 6]
        assert median_of_three_killer_ranks(9) == [*median_of_three_killer_ranks(8), 9]
        assert median_of_three_killer_ranks(1) == [1]
        assert median_of_three_killer_ranks(0) == []

    def test_a_negative_size_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            median_of_three_killer_ranks(-1)

    def test_it_is_deterministic_and_ignores_the_seed(self) -> None:
        assert generate("median_of_three_killer", 300, seed=1) == generate(
            "median_of_three_killer", 300, seed=1
        )
        assert generate("median_of_three_killer", 300, seed=1) == generate(
            "median_of_three_killer", 300, seed=2
        )

    @pytest.mark.parametrize("size", [1, 2, 3, 10, 301])
    def test_the_values_are_distinct_and_in_the_order_of_the_ranks(self, size: int) -> None:
        values = generate("median_of_three_killer", size)
        ranks = median_of_three_killer_ranks(size)
        assert len(set(values)) == size
        assert sorted(range(size), key=values.__getitem__) == sorted(
            range(size), key=ranks.__getitem__
        )

    def test_the_values_span_the_i32_range(self) -> None:
        values = generate("median_of_three_killer", 1000)
        assert min(values) == I32_MIN
        assert max(values) > I32_MAX - 2**22

    @pytest.mark.parametrize("size", [512, 513, 514, 515])
    def test_it_makes_median_of_three_quicksort_quadratic(self, size: int) -> None:
        killer = median_of_three_quicksort_comparisons(generate("median_of_three_killer", size))
        uniform = median_of_three_quicksort_comparisons(generate("uniform", size))
        assert killer > 4 * uniform
        assert killer > size * size // 8

    @pytest.mark.parametrize("size", [512, 1024])
    def test_it_is_also_quadratic_for_the_median_of_the_second_middle_and_second_to_last(
        self, size: int
    ) -> None:
        # The variant of libstdc++'s std::sort: that median is moved to the front and the
        # rest is partitioned from the second position. Its constant is smaller (n^2 / 14).
        killer = libstdcxx_comparisons(generate("median_of_three_killer", size))
        uniform = libstdcxx_comparisons(generate("uniform", size))
        assert killer > 3 * uniform
        assert killer > size * size // 16

    def test_that_variant_grows_about_fourfold_when_the_size_doubles(self) -> None:
        small = libstdcxx_comparisons(generate("median_of_three_killer", 512))
        large = libstdcxx_comparisons(generate("median_of_three_killer", 1024))
        assert large > 3.5 * small

    def test_the_cost_grows_quadratically_with_the_size(self) -> None:
        small = median_of_three_quicksort_comparisons(generate("median_of_three_killer", 400))
        large = median_of_three_quicksort_comparisons(generate("median_of_three_killer", 800))
        assert large > 3.5 * small

    def test_the_other_distributions_do_not_hurt_it(self) -> None:
        for name in ("uniform", "sorted", "reversed", "organ_pipe"):
            comparisons = median_of_three_quicksort_comparisons(generate(name, 512))
            assert comparisons < 512 * 512 // 8, name
