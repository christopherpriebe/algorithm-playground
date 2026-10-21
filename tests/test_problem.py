"""Tests for the Problem interface: what a minimal problem gets for free."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import algorithm_playground.core as core
from algorithm_playground.core import (
    Fixture,
    InputGenerator,
    Problem,
    VerificationResult,
    assert_valid_problem,
    has_input_reader,
    has_trace_format,
    startup_case,
    truncate_text,
)


class MinimalProblem(Problem[list[int], int, None]):
    """Only the required members: formats, fixtures, generators, and a verifier."""

    name = "minimal"
    description = "The smallest possible problem."

    def serialize_input(self, data: list[int], path: Path) -> None:
        path.write_text(",".join(map(str, data)))

    def deserialize_output(self, path: Path) -> int:
        return int(path.read_text())

    def fixtures(self) -> list[Fixture[list[int]]]:
        return [Fixture("empty", [])]

    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        return (InputGenerator("small", "small numbers", _small),)

    def verify(self, input_data: list[int], output: int) -> VerificationResult:
        return VerificationResult(output == len(input_data), "wrong count")


def _small(random_generator: random.Random, size: int) -> list[int]:
    return [random_generator.randrange(10) for _ in range(size)]


class TestDefaults:
    def test_a_minimal_problem_is_valid(self) -> None:
        assert_valid_problem(MinimalProblem())

    def test_there_is_no_expected_output(self) -> None:
        assert MinimalProblem().expected_output([1, 2]) is None

    def test_descriptions_default_to_the_cut_repr(self) -> None:
        problem = MinimalProblem()
        assert problem.describe_input([1, 2], limit=100) == "[1, 2]"
        assert problem.describe_output(7, limit=100) == "7"
        assert problem.describe_input(list(range(100)), limit=20) == "[0, 1, 2, 3, 4, 5..."

    def test_there_are_no_shrink_candidates(self) -> None:
        assert list(MinimalProblem().shrink([1, 2, 3])) == []

    def test_every_input_is_valid(self) -> None:
        assert MinimalProblem().check_input([1, 2, 3]) is None

    def test_the_problem_cannot_read_an_input_file(self, tmp_path: Path) -> None:
        problem = MinimalProblem()
        assert not has_input_reader(problem)
        with pytest.raises(
            NotImplementedError, match="'minimal' does not implement deserialize_input"
        ):
            problem.deserialize_input(tmp_path / "input.bin")

    def test_a_problem_that_reads_its_inputs_has_an_input_reader(self) -> None:
        class Reading(MinimalProblem):
            def deserialize_input(self, path: Path) -> list[int]:
                return []

        assert has_input_reader(Reading())

    def test_the_output_is_described_the_same_with_or_without_a_focus(self) -> None:
        problem = MinimalProblem()
        assert problem.describe_output(7, limit=100, focus=0) == problem.describe_output(
            7, limit=100
        )

    def test_a_verification_names_no_position_and_no_category_by_default(self) -> None:
        result = VerificationResult(False, "wrong")
        assert (result.focus, result.category) == (None, "")
        assert VerificationResult(False, "wrong", focus=3, category="short").focus == 3

    def test_the_problem_has_no_trace_format(self, tmp_path: Path) -> None:
        trace = tmp_path / "trace.bin"
        trace.write_bytes(b"anything")
        assert MinimalProblem().deserialize_trace(trace, [1]) is None

    def test_the_smallest_size_is_zero_and_nothing_is_preferred_for_debugging(self) -> None:
        problem = MinimalProblem()
        assert problem.minimum_size == 0
        assert problem.debug_generator is None
        assert problem.operation_names == ()

    def test_the_startup_case_is_the_default_generator_at_the_minimum_size(self) -> None:
        case = startup_case(MinimalProblem(), seed=3)
        assert case.input_data == []
        assert case.identifier == "generated:small:size=0:seed=3"

    def test_a_problem_has_a_trace_format_when_it_reads_traces(self) -> None:
        class Tracing(MinimalProblem):
            def deserialize_trace(self, path: Path, input_data: list[int]) -> None:
                return None

        assert not has_trace_format(MinimalProblem())
        assert has_trace_format(Tracing())

    def test_a_trace_records_no_operations_and_has_no_warnings(self) -> None:
        problem = MinimalProblem()
        assert problem.operation_counts([1], 1, None) is None
        assert list(problem.trace_warnings([1], 1, None)) == []

    def test_there_is_nothing_to_show(self) -> None:
        problem = MinimalProblem()
        assert problem.input_output_frame([1], 1) is None
        assert list(problem.trace_frames([1], 1, None)) == []

    def test_the_required_members_are_abstract(self) -> None:
        assert Problem.__abstractmethods__ == frozenset(
            {"serialize_input", "deserialize_output", "fixtures", "generators", "verify"}
        )


class TestTruncateText:
    @pytest.mark.parametrize(
        ("text", "limit", "expected"),
        [
            ("short", 10, "short"),
            ("exactly ten", 11, "exactly ten"),
            ("a longer text", 8, "a lon..."),
            ("abcdef", 3, "abc"),
            ("abcdef", 0, ""),
        ],
    )
    def test_cuts_to_the_limit_and_marks_the_cut(
        self, text: str, limit: int, expected: str
    ) -> None:
        assert truncate_text(text, limit) == expected


class TestPublicApi:
    def test_every_exported_name_exists(self) -> None:
        missing = [name for name in core.__all__ if not hasattr(core, name)]
        assert missing == []

    def test_a_problem_author_needs_only_the_core_package(self) -> None:
        for name in (
            "Problem",
            "Fixture",
            "InputGenerator",
            "Case",
            "CasePlan",
            "VerificationResult",
            "register_problem",
            "BinaryFormatError",
            "write_u64",
            "read_u64",
            "write_i32_array",
            "read_i32_array",
            "assert_valid_problem",
            "validate_problem",
        ):
            assert name in core.__all__
