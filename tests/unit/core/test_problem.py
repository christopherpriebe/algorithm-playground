"""Tests for the Problem interface: what a minimal problem gets for free."""

import random
from pathlib import Path

import pytest

from algorithm_playground.core import (
    Fixture,
    InputGenerator,
    Problem,
    VerificationResult,
    assert_valid_problem,
    has_input_reader,
    has_trace_format,
    startup_case,
)


def generate_small_numbers(random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` random numbers below ten."""
    return [random_generator.randrange(10) for _ in range(size)]


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
        return (InputGenerator("small", "small numbers", generate_small_numbers),)

    def verify(self, input_data: list[int], output: int) -> VerificationResult:
        return VerificationResult(output == len(input_data), "wrong count")


class ReadingProblem(MinimalProblem):
    """A minimal problem that can read its inputs back from a file."""

    def deserialize_input(self, path: Path) -> list[int]:
        return []


class TracingProblem(MinimalProblem):
    """A minimal problem that reads traces."""

    def deserialize_trace(self, path: Path, input_data: list[int]) -> None:
        return None


@pytest.fixture
def problem() -> MinimalProblem:
    """A problem that defines only the required members."""
    return MinimalProblem()


class TestDefaults:
    def test_a_minimal_problem_is_valid(self, problem: MinimalProblem) -> None:
        """Test a problem with only the required members passes validation."""
        assert_valid_problem(problem)

    def test_there_is_no_expected_output(self, problem: MinimalProblem) -> None:
        """Test the expected output of an input is unknown by default."""
        assert problem.expected_output([1, 2]) is None

    def test_descriptions_default_to_the_cut_repr(self, problem: MinimalProblem) -> None:
        """Test inputs and outputs are described by their repr, cut to the limit."""
        assert problem.describe_input([1, 2], limit=100) == "[1, 2]"
        assert problem.describe_output(7, limit=100) == "7"
        assert problem.describe_input(list(range(100)), limit=20) == "[0, 1, 2, 3, 4, 5..."

    def test_there_are_no_shrink_candidates(self, problem: MinimalProblem) -> None:
        """Test an input has no shrink candidates by default."""
        assert list(problem.shrink([1, 2, 3])) == []

    def test_every_input_is_valid(self, problem: MinimalProblem) -> None:
        """Test every input is accepted by default."""
        assert problem.check_input([1, 2, 3]) is None

    def test_the_problem_has_no_input_reader(self, problem: MinimalProblem) -> None:
        """Test a problem that does not define deserialize_input has no input reader."""
        assert not has_input_reader(problem)

    def test_reading_an_input_file_is_not_implemented(
        self, problem: MinimalProblem, tmp_path: Path
    ) -> None:
        """Test reading an input file raises an error that names the missing method."""
        with pytest.raises(
            NotImplementedError, match="'minimal' does not implement deserialize_input"
        ):
            problem.deserialize_input(tmp_path / "input.bin")

    def test_a_problem_that_reads_its_inputs_has_an_input_reader(self) -> None:
        """Test a problem that defines deserialize_input has an input reader."""
        assert has_input_reader(ReadingProblem())

    def test_the_output_is_described_the_same_with_or_without_a_focus(
        self, problem: MinimalProblem
    ) -> None:
        """Test a focus on an output does not change its default description."""
        assert problem.describe_output(7, limit=100, focus=0) == problem.describe_output(
            7, limit=100
        )

    def test_a_verification_names_no_position_and_no_category_by_default(self) -> None:
        """Test a verification result has no focus and an empty category unless given."""
        result = VerificationResult(False, "wrong")

        assert (result.focus, result.category) == (None, "")

    def test_a_verification_can_name_a_position_and_a_category(self) -> None:
        """Test a verification result keeps the focus and category it is given."""
        result = VerificationResult(False, "wrong", focus=3, category="short")

        assert (result.focus, result.category) == (3, "short")

    def test_the_problem_has_no_trace_format(self, problem: MinimalProblem, tmp_path: Path) -> None:
        """Test a trace file is not decoded by default."""
        trace = tmp_path / "trace.bin"
        trace.write_bytes(b"anything")

        assert problem.deserialize_trace(trace, [1]) is None

    def test_the_smallest_size_is_zero(self, problem: MinimalProblem) -> None:
        """Test inputs may be empty by default."""
        assert problem.minimum_size == 0

    def test_nothing_is_preferred_for_debugging(self, problem: MinimalProblem) -> None:
        """Test no generator is preferred for debugging by default."""
        assert problem.debug_generator is None

    def test_no_operations_are_named(self, problem: MinimalProblem) -> None:
        """Test a problem names no operations by default."""
        assert problem.operation_names == ()

    def test_the_startup_case_is_the_default_generator_at_the_minimum_size(
        self, problem: MinimalProblem
    ) -> None:
        """Test the startup case is the first generator run at the smallest size."""
        case = startup_case(problem, seed=3)

        assert case.input_data == []
        assert case.identifier == "generated:small:size=0:seed=3"

    def test_a_problem_without_a_trace_reader_has_no_trace_format(
        self, problem: MinimalProblem
    ) -> None:
        """Test a problem that does not define deserialize_trace has no trace format."""
        assert not has_trace_format(problem)

    def test_a_problem_has_a_trace_format_when_it_reads_traces(self) -> None:
        """Test a problem that defines deserialize_trace has a trace format."""
        assert has_trace_format(TracingProblem())

    def test_a_trace_records_no_operations(self, problem: MinimalProblem) -> None:
        """Test a trace has no operation counts by default."""
        assert problem.operation_counts([1], 1, None) is None

    def test_a_trace_has_no_warnings(self, problem: MinimalProblem) -> None:
        """Test a trace produces no warnings by default."""
        assert list(problem.trace_warnings([1], 1, None)) == []

    def test_there_is_no_input_output_frame_to_show(self, problem: MinimalProblem) -> None:
        """Test a run has no input and output frame by default."""
        assert problem.input_output_frame([1], 1) is None

    def test_there_are_no_trace_frames_to_show(self, problem: MinimalProblem) -> None:
        """Test a trace has no frames by default."""
        assert list(problem.trace_frames([1], 1, None)) == []

    def test_the_required_members_are_abstract(self) -> None:
        """Test a subclass must define the formats, fixtures, generators and verifier."""
        assert Problem.__abstractmethods__ == frozenset(
            {"serialize_input", "deserialize_output", "fixtures", "generators", "verify"}
        )
