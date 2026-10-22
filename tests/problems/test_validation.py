"""Tests for the validation kit that checks a problem's hooks."""

import importlib.util
import random
from collections.abc import Iterator
from pathlib import Path

import pytest

from algorithm_playground.core import (
    Fixture,
    InputGenerator,
    Problem,
    VerificationResult,
    assert_valid_problem,
    validate_problem,
)
from algorithm_playground.problems.sorting import SortingProblem


def generate_values(random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` random values below ten."""
    return [random_generator.randrange(10) for _ in range(size)]


def build_sorting_variant(**members: object) -> SortingProblem:
    """Build the (valid) sorting problem with the given members replaced."""
    return type("Variant", (SortingProblem,), members)()


class NoReaderSortingProblem(SortingProblem):
    """The sorting problem without a way to read its inputs back."""

    deserialize_input = Problem.deserialize_input


def test_the_sorting_problem_has_no_findings() -> None:
    """Test validating the sorting problem reports nothing."""
    assert validate_problem(SortingProblem()) == []


def test_the_sorting_problem_passes_the_assertion() -> None:
    """Test asserting the sorting problem is valid does not raise."""
    assert_valid_problem(SortingProblem())


def test_the_distinct_count_example_is_valid(repository_root: Path) -> None:
    """Test the distinct-count example problem passes validation."""
    path = repository_root / "examples" / "distinct_count" / "distinct_count_problem.py"
    specification = importlib.util.spec_from_file_location(
        "distinct_count_for_test", path
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    assert_valid_problem(module.DistinctCountProblem())


def test_assert_valid_problem_lists_every_finding() -> None:
    """Test the assertion error names the problem and lists every finding."""

    def provide_no_fixtures(_: SortingProblem) -> Iterator[Fixture[list[int]]]:
        return iter(())

    def provide_no_generators(_: SortingProblem) -> tuple[()]:
        return ()

    problem = build_sorting_variant(
        fixtures=provide_no_fixtures, generators=provide_no_generators
    )

    with pytest.raises(
        AssertionError, match=r"^Problem 'sorting' is not valid:"
    ) as raised:
        assert_valid_problem(problem)

    message = str(raised.value)
    assert "  - fixtures() returned no fixtures" in message
    assert "  - generators() returned no generators" in message


@pytest.mark.parametrize("attribute", ["name", "description"])
def test_a_missing_name_or_description_is_reported(attribute: str) -> None:
    """Test an empty name or description is a finding."""
    problem = build_sorting_variant(**{attribute: ""})

    findings = validate_problem(problem)

    assert f"the class attribute '{attribute}' must be a non-empty string" in findings


def test_fixture_names_must_be_unique() -> None:
    """Test a fixture name used twice is a finding."""

    def provide_repeated_fixtures(
        _: SortingProblem,
    ) -> Iterator[Fixture[list[int]]]:
        yield Fixture("a", [])
        yield Fixture("a", [1])

    findings = validate_problem(
        build_sorting_variant(fixtures=provide_repeated_fixtures)
    )

    assert "the fixture name 'a' is used more than once" in findings


def test_fixtures_must_be_fixture_objects() -> None:
    """Test a fixtures hook that yields something other than fixtures is a finding."""

    def provide_tuples(_: SortingProblem) -> list[tuple[list[int], str]]:
        return [([1], "x")]

    findings = validate_problem(build_sorting_variant(fixtures=provide_tuples))

    assert "fixtures() must yield Fixture objects, got tuple" in findings


def test_a_fixture_that_does_not_serialize_is_named() -> None:
    """Test a fixture whose input cannot be serialized is a finding that names the fixture."""

    def provide_unserializable_fixture(
        _: SortingProblem,
    ) -> Iterator[Fixture[list[int]]]:
        yield Fixture("huge", [2**40])

    findings = validate_problem(
        build_sorting_variant(fixtures=provide_unserializable_fixture)
    )

    assert any(
        finding.startswith("fixture 'huge' does not serialize: ValueError")
        for finding in findings
    )


def test_generator_names_must_be_unique() -> None:
    """Test a generator name used twice is a finding."""

    def provide_repeated_generators(
        _: SortingProblem,
    ) -> tuple[InputGenerator[list[int]], InputGenerator[list[int]]]:
        return (
            InputGenerator("same", description="one", generate=generate_values),
            InputGenerator("same", description="two", generate=generate_values),
        )

    problem = build_sorting_variant(generators=provide_repeated_generators)

    findings = validate_problem(problem)

    assert "the generator name 'same' is used more than once" in findings


def test_a_generator_must_be_deterministic_for_a_fixed_seed() -> None:
    """Test a generator that ignores the seed is a finding."""

    def generate_unseeded(_random_generator: random.Random, size: int) -> list[int]:
        return [random.randrange(10**9)] * size  # noqa: S311  deliberately unseeded to test determinism detection

    def provide_unseeded_generator(
        _: SortingProblem,
    ) -> tuple[InputGenerator[list[int]]]:
        return (
            InputGenerator(
                "unseeded",
                description="uses global randomness",
                generate=generate_unseeded,
            ),
        )

    problem = build_sorting_variant(generators=provide_unseeded_generator)

    findings = validate_problem(problem)

    assert (
        "generator 'unseeded' at size 5 returned different inputs for the same seed"
        in (findings)
    )


def test_a_generator_must_accept_size_zero() -> None:
    """Test a generator that raises for size zero is a finding."""

    def generate_unless_empty(random_generator: random.Random, size: int) -> list[int]:
        if size == 0:
            message = "size zero is not supported"
            raise ValueError(message)
        return generate_values(random_generator, size)

    def provide_generator(_: SortingProblem) -> tuple[InputGenerator[list[int]]]:
        return (InputGenerator("g", description="g", generate=generate_unless_empty),)

    findings = validate_problem(build_sorting_variant(generators=provide_generator))

    assert (
        "generator 'g' at size 0 raised: ValueError: size zero is not supported"
        in findings
    )


def test_an_expected_output_that_does_not_verify_is_reported() -> None:
    """Test an expected output that the verifier rejects is a finding."""

    def expect_descending_output(_: SortingProblem, input_data: list[int]) -> list[int]:
        return sorted(input_data, reverse=True)

    problem = build_sorting_variant(expected_output=expect_descending_output)

    findings = validate_problem(problem)

    assert any(
        finding.startswith("verify() rejects expected_output() for fixture")
        for finding in findings
    )


def test_an_input_output_frame_that_raises_is_reported() -> None:
    """Test an input and output frame hook that raises is a finding that names the error."""

    def explode(_: SortingProblem, _input_data: list[int], _output: list[int]) -> None:
        message = "cannot draw"
        raise RuntimeError(message)

    findings = validate_problem(build_sorting_variant(input_output_frame=explode))

    assert any(
        finding.startswith("input_output_frame() raised for fixture")
        and "cannot draw" in finding
        for finding in findings
    )


def test_an_input_output_frame_that_is_not_a_frame_is_reported() -> None:
    """Test an input and output frame hook that returns text is a finding."""

    def draw_text(_: SortingProblem, _input_data: list[int], _output: list[int]) -> str:
        return "a picture"

    findings = validate_problem(build_sorting_variant(input_output_frame=draw_text))

    assert "input_output_frame() must return a Frame or None, got str" in findings


def test_no_expected_output_is_fine() -> None:
    """Test a problem that cannot tell the expected output has no findings."""

    def expect_nothing(_: SortingProblem, _input_data: list[int]) -> None:
        return None

    problem = build_sorting_variant(expected_output=expect_nothing)

    assert validate_problem(problem) == []


def test_shrink_candidates_must_serialize() -> None:
    """Test a shrink candidate that cannot be serialized is a finding."""

    def shrink_to_unserializable(
        _: SortingProblem, _input_data: list[int]
    ) -> Iterator[list[int]]:
        return iter([[2**40]])

    findings = validate_problem(build_sorting_variant(shrink=shrink_to_unserializable))

    assert any("a shrink candidate of fixture" in finding for finding in findings)


def test_a_shrink_hook_that_raises_is_reported() -> None:
    """Test a shrink hook that raises is a finding that names the error."""

    def shrink_by_raising(
        _: SortingProblem, _input_data: list[int]
    ) -> Iterator[list[int]]:
        message = "no shrinking today"
        raise RuntimeError(message)
        yield []

    findings = validate_problem(build_sorting_variant(shrink=shrink_by_raising))

    assert any(
        "shrink() raised for fixture" in finding and "no shrinking today" in finding
        for finding in findings
    )


def test_describe_hooks_must_return_text() -> None:
    """Test a description hook that returns a number is a finding."""

    def describe_as_number(
        _: SortingProblem,
        _input_data: list[int],
        *,
        limit: int,  # noqa: ARG001  the validator calls the hook with this keyword
    ) -> int:
        return 5

    problem = build_sorting_variant(describe_input=describe_as_number)

    findings = validate_problem(problem)

    assert "describe_input() must return text, got int" in findings


def test_generators_are_sampled_from_the_minimum_size_up() -> None:
    """Test generators are never asked for an input below the minimum size of the problem."""
    sizes: list[int] = []

    def generate_from_four(random_generator: random.Random, size: int) -> list[int]:
        sizes.append(size)
        if size < 4:
            message = "needs four values"
            raise ValueError(message)
        return generate_values(random_generator, size)

    def provide_generator(_: SortingProblem) -> tuple[InputGenerator[list[int]]]:
        return (InputGenerator("g", description="g", generate=generate_from_four),)

    problem = build_sorting_variant(
        minimum_size=4, debug_generator=None, generators=provide_generator
    )

    findings = validate_problem(problem)

    assert findings == []
    assert min(sizes) == 4


def test_a_generator_that_fails_below_the_minimum_size_is_reported_there() -> None:
    """Test a generator that cannot make small inputs is a finding at the failing size."""

    def generate_from_four(_random_generator: random.Random, size: int) -> list[int]:
        if size < 4:
            message = "needs four values"
            raise ValueError(message)
        return [0] * size

    def provide_generator(_: SortingProblem) -> tuple[InputGenerator[list[int]]]:
        return (InputGenerator("g", description="g", generate=generate_from_four),)

    findings = validate_problem(build_sorting_variant(generators=provide_generator))

    assert "generator 'g' at size 0 raised: ValueError: needs four values" in findings


@pytest.mark.parametrize(
    "value", [-1, "3", 1.5, True], ids=["negative", "text", "float", "boolean"]
)
def test_the_minimum_size_must_be_a_non_negative_integer(value: object) -> None:
    """Test a minimum size that is not a non-negative integer is a finding."""
    findings = validate_problem(build_sorting_variant(minimum_size=value))

    assert any(
        finding.startswith("the class attribute 'minimum_size' must be an integer")
        for finding in findings
    )


def test_the_debug_generator_may_name_a_generator() -> None:
    """Test a debug generator that names one of the generators has no findings."""
    assert validate_problem(build_sorting_variant(debug_generator="sorted")) == []


def test_the_debug_generator_must_name_a_generator() -> None:
    """Test a debug generator that names no generator is a finding."""
    findings = validate_problem(build_sorting_variant(debug_generator="nope"))

    assert (
        "debug_generator 'nope' does not name one of the problem's generators"
        in findings
    )


@pytest.mark.parametrize(
    "names",
    [["list"], ("a", "a"), ("",), (3,)],
    ids=["list", "duplicate", "empty-name", "not-text"],
)
def test_operation_names_must_be_unique_text_in_a_tuple(names: object) -> None:
    """Test operation names that are not a tuple of unique, non-empty text are a finding."""
    findings = validate_problem(build_sorting_variant(operation_names=names))

    assert any(
        finding.startswith("the class attribute 'operation_names' must be a tuple")
        for finding in findings
    )


def test_a_shrink_candidate_equal_to_its_input_is_reported() -> None:
    """Test a shrink candidate equal to the input is a finding."""

    def shrink_to_copy(_: SortingProblem, input_data: list[int]) -> Iterator[list[int]]:
        return iter([list(input_data)])

    findings = validate_problem(build_sorting_variant(shrink=shrink_to_copy))

    assert any(
        finding.startswith("shrink() yields a candidate equal to its input for fixture")
        for finding in findings
    )


def test_an_endless_shrink_hook_is_sampled_not_exhausted() -> None:
    """Test a shrink hook that never stops is only sampled, so validation finishes."""

    def shrink_endlessly(
        _: SortingProblem, input_data: list[int]
    ) -> Iterator[list[int]]:
        while True:
            yield [*input_data, 1]

    assert validate_problem(build_sorting_variant(shrink=shrink_endlessly)) == []


def test_a_hook_that_raises_does_not_stop_the_other_checks() -> None:
    """Test the findings of the other hooks are still reported when one hook raises."""

    def fail_to_provide_fixtures(
        _: SortingProblem,
    ) -> Iterator[Fixture[list[int]]]:
        message = "fixtures exploded"
        raise RuntimeError(message)
        yield Fixture("never", [])

    def provide_no_generators(_: SortingProblem) -> tuple[()]:
        return ()

    problem = build_sorting_variant(
        fixtures=fail_to_provide_fixtures, generators=provide_no_generators
    )

    findings = validate_problem(problem)

    assert "fixtures() raised: RuntimeError: fixtures exploded" in findings
    assert (
        "generators() returned no generators; provide at least one (the default)"
        in findings
    )


def test_verify_is_not_asked_about_wrong_answers() -> None:
    """Test the verifier is only shown outputs that are correctly sorted."""
    outputs: list[list[int]] = []

    def verify_and_record(
        _: SortingProblem, _input_data: list[int], output: list[int]
    ) -> VerificationResult:
        outputs.append(output)
        return VerificationResult(True)

    validate_problem(build_sorting_variant(verify=verify_and_record))

    assert all(output == sorted(output) for output in outputs)


def test_a_fixture_that_breaks_the_rule_is_named() -> None:
    """Test a fixture that the input rule rejects is a finding that names the fixture."""

    def reject_more_than_one_value(
        _: SortingProblem, input_data: list[int]
    ) -> str | None:
        return "must have at most one value" if len(input_data) > 1 else None

    findings = validate_problem(
        build_sorting_variant(check_input=reject_more_than_one_value)
    )

    assert any(
        finding.startswith(
            "check_input() rejects fixture 'duplicates': must have at most"
        )
        for finding in findings
    )


def test_a_generated_sample_that_breaks_the_rule_is_named() -> None:
    """Test a generated input that the input rule rejects is a finding that names the case."""

    def reject_empty_input(_: SortingProblem, input_data: list[int]) -> str | None:
        return "must not be empty" if not input_data else None

    findings = validate_problem(build_sorting_variant(check_input=reject_empty_input))

    assert (
        "check_input() rejects generator 'uniform' at size 0: must not be empty"
        in findings
    )
    assert "check_input() rejects fixture 'empty': must not be empty" in findings


def test_a_rule_that_raises_is_named() -> None:
    """Test an input rule that raises is a finding that names the error."""

    def explode(_: SortingProblem, _input_data: list[int]) -> str | None:
        message = "check exploded"
        raise RuntimeError(message)

    findings = validate_problem(build_sorting_variant(check_input=explode))

    assert any(
        finding.startswith(
            "check_input() raised for fixture 'empty': RuntimeError: check ex"
        )
        for finding in findings
    )


def test_a_rule_must_return_text_or_none() -> None:
    """Test an input rule that returns a boolean is a finding."""

    def return_false(_: SortingProblem, _input_data: list[int]) -> bool:
        return False

    findings = validate_problem(build_sorting_variant(check_input=return_false))

    assert "check_input() must return text or None, got bool" in findings


def test_shrink_candidates_the_rule_rejects_are_not_findings() -> None:
    """Test shrink candidates that the input rule rejects are never serialized or reported."""

    def require_three_values(_: SortingProblem, input_data: list[int]) -> str | None:
        return None if len(input_data) >= 3 or not input_data else "needs three values"

    # Candidates of fewer values would not serialize, but the shrinker never runs them.
    def shrink_to_unserializable(
        _: SortingProblem, _input_data: list[int]
    ) -> Iterator[list[int]]:
        yield [2**40]
        yield [2**40, 1]

    problem = build_sorting_variant(
        check_input=require_three_values, shrink=shrink_to_unserializable
    )

    findings = validate_problem(problem)

    assert not any("shrink candidate" in finding for finding in findings)


def test_shrink_candidates_the_rule_accepts_must_still_serialize() -> None:
    """Test a shrink candidate the input rule accepts but that cannot serialize is a finding."""

    def shrink_to_unserializable(
        _: SortingProblem, _input_data: list[int]
    ) -> Iterator[list[int]]:
        yield [2**40]

    findings = validate_problem(build_sorting_variant(shrink=shrink_to_unserializable))

    assert any(
        "a shrink candidate of" in finding and "does not serialize" in finding
        for finding in findings
    )


def test_a_problem_that_reads_back_what_it_wrote_is_valid() -> None:
    """Test a problem whose reader returns what its writer wrote has no findings."""
    assert validate_problem(SortingProblem()) == []


def test_an_input_that_comes_back_different_is_named() -> None:
    """Test a reader that returns another input is a finding that names the fixture."""

    def read_empty_input(_: SortingProblem, _path: Path) -> list[int]:
        return []

    findings = validate_problem(
        build_sorting_variant(deserialize_input=read_empty_input)
    )

    assert any(
        finding.startswith(
            "deserialize_input() does not return the input that serialize_input wrote for fixture"
        )
        for finding in findings
    )


def test_a_reader_that_raises_is_named() -> None:
    """Test a reader that raises is a finding that names the error."""

    def fail_to_read(_: SortingProblem, _path: Path) -> list[int]:
        message = "disk gone"
        raise OSError(message)

    findings = validate_problem(build_sorting_variant(deserialize_input=fail_to_read))

    assert any(
        finding.startswith(
            "deserialize_input() raised for fixture 'empty': OSError: disk gone"
        )
        for finding in findings
    )


def test_a_problem_without_a_reader_is_not_asked_for_one() -> None:
    """Test a problem that cannot read its inputs is not reported for it."""
    assert validate_problem(NoReaderSortingProblem()) == []
