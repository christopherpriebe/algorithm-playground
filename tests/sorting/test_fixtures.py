"""Tests for the fixtures of the sorting problem."""

import itertools

import pytest

from algorithm_playground.core import (
    Fixture,
)
from algorithm_playground.problems.sorting import (
    I32_MAX,
    I32_MIN,
    SortingProblem,
)

SORTING_FIXTURES = list(SortingProblem().fixtures())


@pytest.fixture
def inputs_by_name(problem: SortingProblem) -> dict[str, list[int]]:
    """The input of every sorting fixture, keyed by the name of the fixture."""
    return {fixture.name: fixture.input_data for fixture in problem.fixtures()}


def test_the_fixtures_are_the_documented_ones_in_order(problem: SortingProblem) -> None:
    """Test the problem defines the documented fixtures in order."""
    names = [fixture.name for fixture in problem.fixtures()]

    assert names == [
        "empty",
        "single",
        "two_sorted",
        "two_unsorted",
        "two_equal",
        "three_123",
        "three_132",
        "three_213",
        "three_231",
        "three_312",
        "three_321",
        "already_sorted",
        "reverse_sorted",
        "duplicates",
        "all_equal",
        "alternating_two_values",
        "duplicated_extremes",
        "negatives_mixed",
        "i32_extremes",
        "length_15",
        "length_16",
        "length_17",
        "largest_first",
        "smallest_last",
    ]


@pytest.mark.parametrize(
    "fixture", SORTING_FIXTURES, ids=[fixture.name for fixture in SORTING_FIXTURES]
)
def test_every_fixture_has_a_description(fixture: Fixture[list[int]]) -> None:
    """Test every fixture has a description."""
    assert fixture.description


@pytest.mark.parametrize(
    "fixture", SORTING_FIXTURES, ids=[fixture.name for fixture in SORTING_FIXTURES]
)
def test_every_fixture_fits_in_i32(fixture: Fixture[list[int]]) -> None:
    """Test every value of every fixture fits in a 32-bit signed integer."""
    assert all(I32_MIN <= value <= I32_MAX for value in fixture.input_data)


def test_the_three_element_fixtures_are_all_six_permutations(
    problem: SortingProblem,
) -> None:
    """Test the three-element fixtures cover all six permutations of three values."""
    arrangements = [
        tuple(fixture.input_data)
        for fixture in problem.fixtures()
        if fixture.name.startswith("three_")
    ]

    assert sorted(arrangements) == sorted(itertools.permutations((1, 2, 3)))


@pytest.mark.parametrize("length", [15, 16, 17])
def test_the_boundary_lengths_surround_a_power_of_two_and_are_scrambled(
    inputs_by_name: dict[str, list[int]], length: int
) -> None:
    """Test a boundary-length fixture holds a scrambled permutation of its length."""
    values = inputs_by_name[f"length_{length}"]

    assert sorted(values) == list(range(length))
    assert values != sorted(values)
    assert values != sorted(values, reverse=True)


def test_alternating_values_alternate_between_zero_and_one(
    inputs_by_name: dict[str, list[int]],
) -> None:
    """Test the alternating fixture holds only zeros and ones, alternating."""
    values = inputs_by_name["alternating_two_values"]

    assert set(values) == {0, 1}
    assert values[:4] == [0, 1, 0, 1]


def test_duplicated_extremes_repeat_both_i32_extremes(
    inputs_by_name: dict[str, list[int]],
) -> None:
    """Test the duplicated extremes fixture repeats both i32 extremes at least four times."""
    extremes = inputs_by_name["duplicated_extremes"]

    assert set(extremes) == {I32_MIN, I32_MAX}
    assert extremes.count(I32_MIN) >= 4
    assert extremes.count(I32_MAX) >= 4


def test_the_largest_element_is_first_and_the_rest_sorted(
    inputs_by_name: dict[str, list[int]],
) -> None:
    """Test the largest-first fixture starts with its maximum followed by sorted values."""
    values = inputs_by_name["largest_first"]

    assert values[0] == max(values)
    assert values[1:] == sorted(values[1:])


def test_the_smallest_element_is_last_and_the_rest_sorted(
    inputs_by_name: dict[str, list[int]],
) -> None:
    """Test the smallest-last fixture ends with its minimum preceded by sorted values."""
    values = inputs_by_name["smallest_last"]

    assert values[-1] == min(values)
    assert values[:-1] == sorted(values[:-1])


@pytest.mark.parametrize(
    "fixture", SORTING_FIXTURES, ids=[fixture.name for fixture in SORTING_FIXTURES]
)
def test_a_correct_sort_passes_the_verifier_on_every_fixture(
    problem: SortingProblem, fixture: Fixture[list[int]]
) -> None:
    """Test the verifier accepts the sorted input of every fixture."""
    result = problem.verify(fixture.input_data, sorted(fixture.input_data))

    assert result.passed


@pytest.mark.parametrize(
    "fixture", SORTING_FIXTURES, ids=[fixture.name for fixture in SORTING_FIXTURES]
)
def test_the_expected_output_of_every_fixture_is_its_sorted_input(
    problem: SortingProblem, fixture: Fixture[list[int]]
) -> None:
    """Test the expected output of every fixture is its input in sorted order."""
    expected = problem.expected_output(fixture.input_data)

    assert expected == sorted(fixture.input_data)
