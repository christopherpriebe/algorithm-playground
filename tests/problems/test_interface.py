"""Tests for the defaults of the Problem interface and for calling its hooks."""

import random
from pathlib import Path
from typing import cast

import pytest
from hypothesis import given, strategies
from typing_extensions import override

from algorithm_playground.core import (
    Fixture,
    GeneratedOrigin,
    HookError,
    InputGenerator,
    Problem,
    VerificationResult,
    assert_valid_problem,
    build_startup_case,
    call_hook,
    has_input_reader,
    has_trace_format,
    parse_case_identifier,
)


def generate_small_numbers(random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` random numbers below ten."""
    return [random_generator.randrange(10) for _ in range(size)]


class MinimalProblem(Problem[list[int], int, None]):
    """Only the required members: formats, fixtures, generators, and a verifier."""

    name = "minimal"
    description = "The smallest possible problem."

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        path.write_text(",".join(map(str, data)))

    @override
    def deserialize_output(self, path: Path) -> int:
        return int(path.read_text())

    @override
    def fixtures(self) -> list[Fixture[list[int]]]:
        return [Fixture("empty", [])]

    @override
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        return (
            InputGenerator(
                "small", description="small numbers", generate=generate_small_numbers
            ),
        )

    @override
    def verify(self, input_data: list[int], output: int) -> VerificationResult:
        return VerificationResult(output == len(input_data), message="wrong count")


class ReadingProblem(MinimalProblem):
    """A minimal problem that can read its inputs back from a file."""

    @override
    def deserialize_input(self, path: Path) -> list[int]:
        return []


class TracingProblem(MinimalProblem):
    """A minimal problem that reads traces."""

    @override
    def deserialize_trace(self, path: Path, input_data: list[int]) -> None:
        return None


@pytest.fixture
def problem() -> MinimalProblem:
    """A problem that defines only the required members."""
    return MinimalProblem()


def test_a_minimal_problem_is_valid(problem: MinimalProblem) -> None:
    """Test a problem with only the required members passes validation."""
    assert_valid_problem(problem)


def test_there_is_no_expected_output(problem: MinimalProblem) -> None:
    """Test the expected output of an input is unknown by default."""
    assert problem.expected_output([1, 2]) is None


def test_descriptions_default_to_the_cut_repr(problem: MinimalProblem) -> None:
    """Test inputs and outputs are described by their repr, cut to the limit."""
    assert problem.describe_input([1, 2], limit=100) == "[1, 2]"
    assert problem.describe_output(7, limit=100) == "7"
    assert problem.describe_input(list(range(100)), limit=20) == "[0, 1, 2, 3, 4, 5..."


def test_there_are_no_shrink_candidates(problem: MinimalProblem) -> None:
    """Test an input has no shrink candidates by default."""
    assert list(problem.shrink([1, 2, 3])) == []


def test_every_input_is_valid(problem: MinimalProblem) -> None:
    """Test every input is accepted by default."""
    assert problem.check_input([1, 2, 3]) is None


def test_the_problem_has_no_input_reader(problem: MinimalProblem) -> None:
    """Test a problem that does not define deserialize_input has no input reader."""
    assert not has_input_reader(problem)


def test_reading_an_input_file_is_not_implemented(
    problem: MinimalProblem, tmp_path: Path
) -> None:
    """Test reading an input file raises an error that names the missing method."""
    with pytest.raises(
        NotImplementedError, match="'minimal' does not implement deserialize_input"
    ):
        problem.deserialize_input(tmp_path / "input.bin")


def test_a_problem_that_reads_its_inputs_has_an_input_reader() -> None:
    """Test a problem that defines deserialize_input has an input reader."""
    assert has_input_reader(ReadingProblem())


def test_the_output_is_described_the_same_with_or_without_a_focus(
    problem: MinimalProblem,
) -> None:
    """Test a focus on an output does not change its default description."""
    assert problem.describe_output(7, limit=100, focus=0) == problem.describe_output(
        7, limit=100
    )


def test_a_verification_names_no_position_and_no_category_by_default() -> None:
    """Test a verification result has no focus and an empty category unless given."""
    result = VerificationResult(False, message="wrong")

    assert (result.focus, result.category) == (None, "")


def test_a_verification_can_name_a_position_and_a_category() -> None:
    """Test a verification result keeps the focus and category it is given."""
    result = VerificationResult(False, message="wrong", focus=3, category="short")

    assert (result.focus, result.category) == (3, "short")


def test_a_failed_verification_needs_a_message() -> None:
    """Test a failure without a message is rejected, since reports would say nothing."""
    with pytest.raises(ValueError, match="failed verification needs a message"):
        VerificationResult(False)


@pytest.mark.parametrize(
    ("focus", "category"), [(1, ""), (None, "short")], ids=["focus", "category"]
)
def test_a_passed_verification_has_no_focus_or_category(
    focus: int | None, category: str
) -> None:
    """Test a focus or a category, which only describe a failure, is rejected on a pass."""
    with pytest.raises(
        ValueError, match="passed verification cannot have a focus or a category"
    ):
        VerificationResult(True, focus=focus, category=category)


def test_a_passed_verification_may_carry_a_message() -> None:
    """Test ``VerificationResult(ok, message=...)`` works whichever way ``ok`` goes."""
    result = VerificationResult(True, message="expected 3, got 3")

    assert result.passed
    assert result.message == "expected 3, got 3"


def test_a_fixture_needs_a_name() -> None:
    """Test an empty fixture name is rejected, since its case could not be named."""
    with pytest.raises(ValueError, match="fixture needs a non-empty name"):
        Fixture("", [2])


NOT_TEXT = [5, None, b"bytes"]


@pytest.mark.parametrize("name", NOT_TEXT, ids=repr)
def test_a_fixture_name_that_is_not_text_is_rejected(name: object) -> None:
    """Test a problem without type checking that passes a non-string name gets a clear error."""
    with pytest.raises(ValueError, match="fixture needs a non-empty name"):
        Fixture(cast("str", name), [2])


@pytest.mark.parametrize("name", NOT_TEXT, ids=repr)
def test_a_generator_name_that_is_not_text_is_rejected(name: object) -> None:
    """Test a non-string generator name gets the naming error, not a TypeError."""
    with pytest.raises(
        ValueError, match="must be non-empty and contain no colon or whitespace"
    ):
        InputGenerator(
            cast("str", name), description="bad", generate=generate_small_numbers
        )


@pytest.mark.parametrize("name", ["", "has space", "has\ttab", "has:colon"], ids=repr)
def test_a_generator_name_must_be_usable_in_identifiers(name: str) -> None:
    """Test a generator name that is empty or has a colon or whitespace is rejected."""
    with pytest.raises(
        ValueError, match="must be non-empty and contain no colon or whitespace"
    ):
        InputGenerator(name, description="bad", generate=generate_small_numbers)


@given(
    strategies.text(min_size=1).filter(
        lambda name: (
            ":" not in name and not any(character.isspace() for character in name)
        )
    ),
    strategies.integers(min_value=0),
    strategies.integers(min_value=0),
)
def test_every_accepted_generator_name_round_trips_through_a_case_identifier(
    name: str, size: int, seed: int
) -> None:
    """Test a name the generator accepts can always be read back from its case identifier."""
    InputGenerator(name, description="any", generate=generate_small_numbers)
    origin = GeneratedOrigin(generator_name=name, seed=seed, size=size)

    assert parse_case_identifier(origin.identifier) == origin


def test_the_problem_has_no_trace_format(
    problem: MinimalProblem, tmp_path: Path
) -> None:
    """Test a trace file is not decoded by default."""
    trace = tmp_path / "trace.bin"
    trace.write_bytes(b"anything")

    assert problem.deserialize_trace(trace, [1]) is None


def test_the_smallest_size_is_zero(problem: MinimalProblem) -> None:
    """Test inputs may be empty by default."""
    assert problem.minimum_size == 0


def test_nothing_is_preferred_for_debugging(problem: MinimalProblem) -> None:
    """Test no generator is preferred for debugging by default."""
    assert problem.debug_generator is None


def test_no_operations_are_named(problem: MinimalProblem) -> None:
    """Test a problem names no operations by default."""
    assert problem.operation_names == ()


def test_the_startup_case_is_the_default_generator_at_the_minimum_size(
    problem: MinimalProblem,
) -> None:
    """Test the startup case is the first generator run at the smallest size."""
    case = build_startup_case(problem, seed=3)

    assert case.input_data == []
    assert case.identifier == "generated:small:size=0:seed=3"


def test_a_problem_without_a_trace_reader_has_no_trace_format(
    problem: MinimalProblem,
) -> None:
    """Test a problem that does not define deserialize_trace has no trace format."""
    assert not has_trace_format(problem)


def test_a_problem_has_a_trace_format_when_it_reads_traces() -> None:
    """Test a problem that defines deserialize_trace has a trace format."""
    assert has_trace_format(TracingProblem())


def test_a_trace_records_no_operations(problem: MinimalProblem) -> None:
    """Test a trace has no operation counts by default."""
    assert problem.operation_counts([1], 1, None) is None


def test_a_trace_has_no_warnings(problem: MinimalProblem) -> None:
    """Test a trace produces no warnings by default."""
    assert list(problem.trace_warnings([1], 1, None)) == []


def test_there_is_no_input_output_frame_to_show(problem: MinimalProblem) -> None:
    """Test a run has no input and output frame by default."""
    assert problem.input_output_frame([1], 1) is None


def test_there_are_no_trace_frames_to_show(problem: MinimalProblem) -> None:
    """Test a trace has no frames by default."""
    assert list(problem.trace_frames([1], 1, None)) == []


def test_the_required_members_are_abstract() -> None:
    """Test a subclass must define the formats, fixtures, generators and verifier."""
    assert Problem.__abstractmethods__ == frozenset(
        {
            "serialize_input",
            "deserialize_output",
            "fixtures",
            "generators",
            "verify",
        }
    )


def test_it_returns_what_the_call_returns() -> None:
    """Test the value the hook returns is passed on."""
    assert call_hook("fixtures", lambda: [1, 2]) == [1, 2]


def test_an_exception_becomes_an_error_that_names_the_hook_and_the_failure() -> None:
    """Test an exception from a hook is reported as an error naming the hook and the cause."""

    def explode() -> None:
        message = "out of fixtures"
        raise ValueError(message)

    with pytest.raises(
        HookError,
        match=r"^The problem's fixtures hook raised ValueError: out of fixtures\.$",
    ) as raised:
        call_hook("fixtures", explode)

    assert raised.value.hook == "fixtures"
    assert isinstance(raised.value.__cause__, ValueError)


def test_an_error_that_already_names_a_hook_is_not_wrapped_again() -> None:
    """Test an error that already names a hook keeps the name of that hook."""

    def inner() -> None:
        hook = "generators"
        message = "inner"
        raise HookError(hook, RuntimeError(message))

    with pytest.raises(
        HookError, match="generators hook raised RuntimeError: inner"
    ) as raised:
        call_hook("fixtures", inner)

    assert raised.value.hook == "generators"


def test_an_interrupt_is_not_swallowed() -> None:
    """Test a keyboard interrupt from a hook propagates unchanged."""

    def interrupt() -> None:
        message = "pressed during the hook"
        raise KeyboardInterrupt(message)

    with pytest.raises(KeyboardInterrupt, match=r"^pressed during the hook$"):
        call_hook("fixtures", interrupt)
