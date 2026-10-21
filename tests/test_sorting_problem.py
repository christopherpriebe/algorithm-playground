"""Unit tests for the SortingProblem: format, verifier, fixtures, generators."""

from __future__ import annotations

import itertools
import struct
from pathlib import Path

import pytest

from algorithm_playground.core.binary_format import BinaryFormatError
from algorithm_playground.core.cases import (
    CaseError,
    default_generator,
    generate_case,
    startup_case,
)
from algorithm_playground.core.validation import assert_valid_problem
from algorithm_playground.problems.sorting import EventLog, SortingProblem, SortingTrace
from algorithm_playground.problems.sorting.codec import I32_MAX, I32_MIN


@pytest.fixture
def problem() -> SortingProblem:
    return SortingProblem()


class TestSerialization:
    def test_input_round_trips_through_disk(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "input.bin"
        problem.serialize_input([-3, 0, 7, I32_MAX, I32_MIN], path)
        raw = path.read_bytes()
        # u64 count = 5, then 5 i32 values
        assert raw[:8] == struct.pack("<Q", 5)
        values = list(struct.unpack_from("<5i", raw, 8))
        assert values == [-3, 0, 7, I32_MAX, I32_MIN]

    def test_input_rejects_value_outside_i32_range(
        self, problem: SortingProblem, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="out of i32 range"):
            problem.serialize_input([2**31], tmp_path / "input.bin")

    def test_output_round_trip(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "output.bin"
        path.write_bytes(struct.pack("<Q3i", 3, -1, 0, 5))
        assert problem.deserialize_output(path) == [-1, 0, 5]

    def test_input_is_read_back(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "input.bin"
        problem.serialize_input([5, -2, 9], path)
        assert problem.deserialize_input(path) == [5, -2, 9]

    def test_an_input_file_with_trailing_bytes_is_named_as_such(
        self, problem: SortingProblem, tmp_path: Path
    ) -> None:
        path = tmp_path / "input.bin"
        path.write_bytes(struct.pack("<Q1i", 1, 3) + b"\x00")
        with pytest.raises(BinaryFormatError, match="The input file has trailing bytes"):
            problem.deserialize_input(path)

    def test_the_error_for_a_value_out_of_range_names_its_index(
        self, problem: SortingProblem, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match=r"Value at index 1 is out of i32 range"):
            problem.serialize_input([1, 2**31, 3], tmp_path / "input.bin")

    def test_output_rejects_trailing_bytes(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "bad.bin"
        path.write_bytes(struct.pack("<Q3i", 3, 1, 2, 3) + b"\x00")
        with pytest.raises(BinaryFormatError, match="trailing bytes"):
            problem.deserialize_output(path)

    def test_output_rejects_a_count_larger_than_the_file(
        self, problem: SortingProblem, tmp_path: Path
    ) -> None:
        path = tmp_path / "huge.bin"
        path.write_bytes(struct.pack("<Q", 2**64 - 1))
        with pytest.raises(BinaryFormatError, match="Declared"):
            problem.deserialize_output(path)

    def test_output_rejects_a_missing_header(self, problem: SortingProblem, tmp_path: Path) -> None:
        path = tmp_path / "short.bin"
        path.write_bytes(b"\x01\x00")
        with pytest.raises(BinaryFormatError):
            problem.deserialize_output(path)


class TestVerification:
    def test_correct_output_passes(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 2, 3])
        assert result.passed
        assert result.message == ""

    def test_length_mismatch_fails(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 2])
        assert not result.passed
        assert "length" in result.message.lower()

    def test_unsorted_output_fails_with_index(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 3, 2])
        assert not result.passed
        assert "index 1" in result.message


class TestFixtures:
    def test_the_fixtures_are_the_documented_ones_in_order(self, problem: SortingProblem) -> None:
        assert [fixture.name for fixture in problem.fixtures()] == [
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

    def test_every_fixture_has_a_description_and_fits_in_i32(self, problem: SortingProblem) -> None:
        for fixture in problem.fixtures():
            assert fixture.description, fixture.name
            assert all(I32_MIN <= value <= I32_MAX for value in fixture.input_data), fixture.name

    def test_the_three_element_fixtures_are_all_six_permutations(
        self, problem: SortingProblem
    ) -> None:
        arrangements = [
            tuple(fixture.input_data)
            for fixture in problem.fixtures()
            if fixture.name.startswith("three_")
        ]
        assert sorted(arrangements) == sorted(itertools.permutations((1, 2, 3)))

    def test_the_boundary_lengths_surround_a_power_of_two_and_are_scrambled(
        self, problem: SortingProblem
    ) -> None:
        by_name = {fixture.name: fixture.input_data for fixture in problem.fixtures()}
        for length in (15, 16, 17):
            values = by_name[f"length_{length}"]
            assert sorted(values) == list(range(length))
            assert values != sorted(values)
            assert values != sorted(values, reverse=True)

    def test_duplicates_and_extremes_are_present_where_the_names_say(
        self, problem: SortingProblem
    ) -> None:
        by_name = {fixture.name: fixture.input_data for fixture in problem.fixtures()}
        assert set(by_name["alternating_two_values"]) == {0, 1}
        assert by_name["alternating_two_values"][:4] == [0, 1, 0, 1]
        extremes = by_name["duplicated_extremes"]
        assert set(extremes) == {I32_MIN, I32_MAX}
        assert extremes.count(I32_MIN) >= 4 and extremes.count(I32_MAX) >= 4

    def test_one_element_is_out_of_place_at_each_end(self, problem: SortingProblem) -> None:
        by_name = {fixture.name: fixture.input_data for fixture in problem.fixtures()}
        assert by_name["largest_first"][0] == max(by_name["largest_first"])
        assert by_name["largest_first"][1:] == sorted(by_name["largest_first"][1:])
        assert by_name["smallest_last"][-1] == min(by_name["smallest_last"])
        assert by_name["smallest_last"][:-1] == sorted(by_name["smallest_last"][:-1])

    def test_a_correct_sort_passes_the_verifier_on_every_fixture(
        self, problem: SortingProblem
    ) -> None:
        for fixture in problem.fixtures():
            assert problem.verify(fixture.input_data, sorted(fixture.input_data)).passed
            assert problem.expected_output(fixture.input_data) == sorted(fixture.input_data)


class TestCases:
    def test_the_default_generator_is_uniform(self, problem: SortingProblem) -> None:
        assert problem.generators()[0].name == "uniform"

    def test_generated_cases_are_deterministic(self, problem: SortingProblem) -> None:
        generator = default_generator(problem)
        first = generate_case(generator, size=64, seed=123)
        second = generate_case(generator, size=64, seed=123)
        assert first.input_data == second.input_data
        assert len(first.input_data) == 64
        assert all(I32_MIN <= value <= I32_MAX for value in first.input_data)

    def test_generated_cases_with_different_seeds_differ(self, problem: SortingProblem) -> None:
        generator = default_generator(problem)
        assert (
            generate_case(generator, size=64, seed=1).input_data
            != generate_case(generator, size=64, seed=2).input_data
        )

    def test_startup_case_is_empty(self, problem: SortingProblem) -> None:
        assert problem.minimum_size == 0
        assert startup_case(problem, seed=5).input_data == []

    def test_debug_pictures_draw_from_a_distribution_with_few_values(
        self, problem: SortingProblem
    ) -> None:
        assert problem.debug_generator == "small_range"
        assert problem.debug_generator in {generator.name for generator in problem.generators()}

    def test_the_operation_names_are_the_keys_of_the_counts(self, problem: SortingProblem) -> None:
        trace = SortingTrace((), EventLog.from_events([]))
        assert tuple(problem.operation_counts([], [], trace) or ()) == problem.operation_names

    def test_negative_size_rejected(self, problem: SortingProblem) -> None:
        with pytest.raises(CaseError):
            generate_case(default_generator(problem), size=-1, seed=0)

    def test_satisfies_the_problem_interface(self, problem: SortingProblem) -> None:
        assert_valid_problem(problem)


class TestVerificationDetails:
    def test_a_wrong_length_names_the_first_difference_and_its_category(
        self, problem: SortingProblem
    ) -> None:
        result = problem.verify([3, 1, 2], [1, 2])
        assert (result.focus, result.category) == (2, "wrong length")

    def test_a_wrong_order_names_the_first_difference_and_its_category(
        self, problem: SortingProblem
    ) -> None:
        result = problem.verify([3, 1, 2], [1, 3, 2])
        assert (result.focus, result.category) == (1, "not sorted")

    def test_a_length_difference_in_the_middle_is_found_there(
        self, problem: SortingProblem
    ) -> None:
        assert problem.verify([1, 2, 3, 4], [1, 5]).focus == 1

    def test_a_pass_names_neither(self, problem: SortingProblem) -> None:
        result = problem.verify([3, 1, 2], [1, 2, 3])
        assert (result.focus, result.category) == (None, "")


class TestFailureReportHooks:
    def test_expected_output_is_the_sorted_input(self, problem: SortingProblem) -> None:
        assert problem.expected_output([3, 1, 2]) == [1, 2, 3]

    def test_short_values_are_described_in_full(self, problem: SortingProblem) -> None:
        assert problem.describe_input([3, 1, 2], limit=100) == "[3, 1, 2]"
        assert problem.describe_output([1, 2, 3], limit=100) == "[1, 2, 3]"

    def test_long_values_are_cut_to_the_limit_with_their_count(
        self, problem: SortingProblem
    ) -> None:
        text = problem.describe_input(list(range(1000, 1100)), limit=40)
        assert text.startswith("[1000, 1001, ")
        assert text.endswith(", ...] (100 values)")
        assert len(text) <= 40

    def test_a_focus_shows_a_window_around_the_first_difference(
        self, problem: SortingProblem
    ) -> None:
        text = problem.describe_output(list(range(1000, 2000)), limit=60, focus=700)
        assert text.startswith("[..., ") and "1700" in text and text.endswith(" shown)")

    def test_the_input_is_described_from_its_start(self, problem: SortingProblem) -> None:
        assert problem.describe_input(list(range(100)), limit=30).startswith("[0, 1, 2, ")

    def test_a_limit_too_small_for_one_value_still_returns_text(
        self, problem: SortingProblem
    ) -> None:
        assert problem.describe_input([123456789], limit=3) == "[12"
        assert len(problem.describe_input(list(range(50)), limit=10)) <= 10


class TestShrink:
    def candidates(self, problem: SortingProblem, values: list[int]) -> list[list[int]]:
        return list(problem.shrink(values))

    def test_nothing_shrinks_an_empty_input(self, problem: SortingProblem) -> None:
        assert self.candidates(problem, []) == []

    def test_a_single_element_shrinks_to_empty_and_to_zero(self, problem: SortingProblem) -> None:
        assert self.candidates(problem, [8]) == [[], [0], [4]]

    def test_larger_chunks_are_dropped_before_single_elements(
        self, problem: SortingProblem
    ) -> None:
        candidates = self.candidates(problem, [5, 4, 3, 2])
        assert candidates[:2] == [[3, 2], [5, 4]]
        assert [4, 3, 2] in candidates

    def test_values_are_simplified_after_the_elements(self, problem: SortingProblem) -> None:
        candidates = self.candidates(problem, [5, 4, 3, 2])
        assert candidates.index([0, 0, 0, 0]) > candidates.index([4, 3, 2])
        assert [3, 2, 1, 0] in candidates

    def test_no_candidate_equals_the_input_and_all_are_valid(self, problem: SortingProblem) -> None:
        values = [I32_MAX, 0, I32_MIN, 7, 7]
        for candidate in problem.shrink(values):
            assert candidate != values
            assert all(I32_MIN <= value <= I32_MAX for value in candidate)
