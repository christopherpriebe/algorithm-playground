"""Tests for the problem validation kit."""

import importlib.util
import random
from collections.abc import Iterator
from pathlib import Path

import pytest

from algorithm_playground.core.cases import Fixture, InputGenerator
from algorithm_playground.core.problem import Problem, VerificationResult
from algorithm_playground.core.validation import assert_valid_problem, validate_problem
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


class TestValidProblems:
    def test_the_sorting_problem_has_no_findings(self) -> None:
        """Test validating the sorting problem reports nothing."""
        assert validate_problem(SortingProblem()) == []

    def test_the_sorting_problem_passes_the_assertion(self) -> None:
        """Test asserting the sorting problem is valid does not raise."""
        assert_valid_problem(SortingProblem())

    def test_the_distinct_count_example_is_valid(self, repository_root: Path) -> None:
        """Test the distinct-count example problem passes validation."""
        path = repository_root / "examples" / "distinct_count" / "distinct_count_problem.py"
        specification = importlib.util.spec_from_file_location("distinct_count_for_test", path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)

        assert_valid_problem(module.DistinctCountProblem())


class TestFindings:
    def test_assert_valid_problem_lists_every_finding(self) -> None:
        """Test the assertion error names the problem and lists every finding."""

        def provide_no_fixtures(self: SortingProblem) -> Iterator[Fixture[list[int]]]:
            return iter(())

        def provide_no_generators(self: SortingProblem) -> tuple[()]:
            return ()

        problem = build_sorting_variant(
            fixtures=provide_no_fixtures, generators=provide_no_generators
        )

        with pytest.raises(AssertionError, match=r"^Problem 'sorting' is not valid:") as raised:
            assert_valid_problem(problem)

        message = str(raised.value)
        assert "  - fixtures() returned no fixtures" in message
        assert "  - generators() returned no generators" in message

    @pytest.mark.parametrize("attribute", ["name", "description"])
    def test_a_missing_name_or_description_is_reported(self, attribute: str) -> None:
        """Test an empty name or description is a finding."""
        problem = build_sorting_variant(**{attribute: ""})

        findings = validate_problem(problem)

        assert f"the class attribute '{attribute}' must be a non-empty string" in findings

    def test_fixture_names_must_be_unique(self) -> None:
        """Test a fixture name used twice is a finding."""

        def provide_repeated_fixtures(self: SortingProblem) -> Iterator[Fixture[list[int]]]:
            yield Fixture("a", [])
            yield Fixture("a", [1])

        findings = validate_problem(build_sorting_variant(fixtures=provide_repeated_fixtures))

        assert "the fixture name 'a' is used more than once" in findings

    def test_fixture_names_must_be_non_empty(self) -> None:
        """Test a fixture with an empty name is a finding."""

        def provide_unnamed_fixture(self: SortingProblem) -> Iterator[Fixture[list[int]]]:
            yield Fixture("", [2])

        findings = validate_problem(build_sorting_variant(fixtures=provide_unnamed_fixture))

        assert "a fixture has an empty name" in findings

    def test_fixtures_must_be_fixture_objects(self) -> None:
        """Test a fixtures hook that yields something other than fixtures is a finding."""

        def provide_tuples(self: SortingProblem) -> list[tuple[list[int], str]]:
            return [([1], "x")]

        findings = validate_problem(build_sorting_variant(fixtures=provide_tuples))

        assert "fixtures() must yield Fixture objects, got tuple" in findings

    def test_a_fixture_that_does_not_serialize_is_named(self) -> None:
        """Test a fixture whose input cannot be serialized is a finding that names the fixture."""

        def provide_unserializable_fixture(
            self: SortingProblem,
        ) -> Iterator[Fixture[list[int]]]:
            yield Fixture("huge", [2**40])

        findings = validate_problem(build_sorting_variant(fixtures=provide_unserializable_fixture))

        assert any(
            finding.startswith("fixture 'huge' does not serialize: ValueError")
            for finding in findings
        )

    @pytest.mark.parametrize(
        "name", ["", "has space", "has:colon"], ids=["empty", "whitespace", "colon"]
    )
    def test_generator_names_must_be_usable_in_identifiers(self, name: str) -> None:
        """Test a generator name that is empty or has a colon or whitespace is a finding."""

        def provide_badly_named_generator(
            self: SortingProblem,
        ) -> tuple[InputGenerator[list[int]]]:
            return (InputGenerator(name, "bad", generate_values),)

        problem = build_sorting_variant(generators=provide_badly_named_generator)

        findings = validate_problem(problem)

        assert (
            f"the generator name {name!r} must be non-empty and contain no colon or whitespace"
            in findings
        )

    def test_generator_names_must_be_unique(self) -> None:
        """Test a generator name used twice is a finding."""

        def provide_repeated_generators(
            self: SortingProblem,
        ) -> tuple[InputGenerator[list[int]], InputGenerator[list[int]]]:
            return (
                InputGenerator("same", "one", generate_values),
                InputGenerator("same", "two", generate_values),
            )

        problem = build_sorting_variant(generators=provide_repeated_generators)

        findings = validate_problem(problem)

        assert "the generator name 'same' is used more than once" in findings

    def test_a_generator_must_be_deterministic_for_a_fixed_seed(self) -> None:
        """Test a generator that ignores the seed is a finding."""

        def generate_unseeded(random_generator: random.Random, size: int) -> list[int]:
            return [random.randrange(10**9)] * size

        def provide_unseeded_generator(self: SortingProblem) -> tuple[InputGenerator[list[int]]]:
            return (InputGenerator("unseeded", "uses global randomness", generate_unseeded),)

        problem = build_sorting_variant(generators=provide_unseeded_generator)

        findings = validate_problem(problem)

        assert "generator 'unseeded' at size 5 returned different inputs for the same seed" in (
            findings
        )

    def test_a_generator_must_accept_size_zero(self) -> None:
        """Test a generator that raises for size zero is a finding."""

        def generate_unless_empty(random_generator: random.Random, size: int) -> list[int]:
            if size == 0:
                raise ValueError("size zero is not supported")
            return generate_values(random_generator, size)

        def provide_generator(self: SortingProblem) -> tuple[InputGenerator[list[int]]]:
            return (InputGenerator("g", "g", generate_unless_empty),)

        findings = validate_problem(build_sorting_variant(generators=provide_generator))

        assert "generator 'g' at size 0 raised: ValueError: size zero is not supported" in findings

    def test_an_expected_output_that_does_not_verify_is_reported(self) -> None:
        """Test an expected output that the verifier rejects is a finding."""

        def expect_descending_output(self: SortingProblem, input_data: list[int]) -> list[int]:
            return sorted(input_data, reverse=True)

        problem = build_sorting_variant(expected_output=expect_descending_output)

        findings = validate_problem(problem)

        assert any(
            finding.startswith("verify() rejects expected_output() for fixture")
            for finding in findings
        )

    def test_an_input_output_frame_that_raises_is_reported(self) -> None:
        """Test an input and output frame hook that raises is a finding that names the error."""

        def explode(self: SortingProblem, input_data: list[int], output: list[int]) -> None:
            raise RuntimeError("cannot draw")

        findings = validate_problem(build_sorting_variant(input_output_frame=explode))

        assert any(
            finding.startswith("input_output_frame() raised for fixture")
            and "cannot draw" in finding
            for finding in findings
        )

    def test_an_input_output_frame_that_is_not_a_frame_is_reported(self) -> None:
        """Test an input and output frame hook that returns text is a finding."""

        def draw_text(self: SortingProblem, input_data: list[int], output: list[int]) -> str:
            return "a picture"

        findings = validate_problem(build_sorting_variant(input_output_frame=draw_text))

        assert "input_output_frame() must return a Frame or None, got str" in findings

    def test_no_expected_output_is_fine(self) -> None:
        """Test a problem that cannot tell the expected output has no findings."""

        def expect_nothing(self: SortingProblem, input_data: list[int]) -> None:
            return None

        problem = build_sorting_variant(expected_output=expect_nothing)

        assert validate_problem(problem) == []

    def test_shrink_candidates_must_serialize(self) -> None:
        """Test a shrink candidate that cannot be serialized is a finding."""

        def shrink_to_unserializable(
            self: SortingProblem, input_data: list[int]
        ) -> Iterator[list[int]]:
            return iter([[2**40]])

        findings = validate_problem(build_sorting_variant(shrink=shrink_to_unserializable))

        assert any("a shrink candidate of fixture" in finding for finding in findings)

    def test_a_shrink_hook_that_raises_is_reported(self) -> None:
        """Test a shrink hook that raises is a finding that names the error."""

        def shrink_by_raising(self: SortingProblem, input_data: list[int]) -> Iterator[list[int]]:
            raise RuntimeError("no shrinking today")
            yield []

        findings = validate_problem(build_sorting_variant(shrink=shrink_by_raising))

        assert any(
            "shrink() raised for fixture" in finding and "no shrinking today" in finding
            for finding in findings
        )

    def test_describe_hooks_must_return_text(self) -> None:
        """Test a description hook that returns a number is a finding."""

        def describe_as_number(self: SortingProblem, input_data: list[int], *, limit: int) -> int:
            return 5

        problem = build_sorting_variant(describe_input=describe_as_number)

        findings = validate_problem(problem)

        assert "describe_input() must return text, got int" in findings

    def test_generators_are_sampled_from_the_minimum_size_up(self) -> None:
        """Test generators are never asked for an input below the minimum size of the problem."""
        sizes: list[int] = []

        def generate_from_four(random_generator: random.Random, size: int) -> list[int]:
            sizes.append(size)
            if size < 4:
                raise ValueError("needs four values")
            return generate_values(random_generator, size)

        def provide_generator(self: SortingProblem) -> tuple[InputGenerator[list[int]]]:
            return (InputGenerator("g", "g", generate_from_four),)

        problem = build_sorting_variant(
            minimum_size=4, debug_generator=None, generators=provide_generator
        )

        findings = validate_problem(problem)

        assert findings == []
        assert min(sizes) == 4

    def test_a_generator_that_fails_below_the_minimum_size_is_reported_there(self) -> None:
        """Test a generator that cannot make small inputs is a finding at the failing size."""

        def generate_from_four(random_generator: random.Random, size: int) -> list[int]:
            if size < 4:
                raise ValueError("needs four values")
            return [0] * size

        def provide_generator(self: SortingProblem) -> tuple[InputGenerator[list[int]]]:
            return (InputGenerator("g", "g", generate_from_four),)

        findings = validate_problem(build_sorting_variant(generators=provide_generator))

        assert "generator 'g' at size 0 raised: ValueError: needs four values" in findings

    @pytest.mark.parametrize(
        "value", [-1, "3", 1.5, True], ids=["negative", "text", "float", "boolean"]
    )
    def test_the_minimum_size_must_be_a_non_negative_integer(self, value: object) -> None:
        """Test a minimum size that is not a non-negative integer is a finding."""
        findings = validate_problem(build_sorting_variant(minimum_size=value))

        assert any(
            finding.startswith("the class attribute 'minimum_size' must be an integer")
            for finding in findings
        )

    def test_the_debug_generator_may_name_a_generator(self) -> None:
        """Test a debug generator that names one of the generators has no findings."""
        assert validate_problem(build_sorting_variant(debug_generator="sorted")) == []

    def test_the_debug_generator_must_name_a_generator(self) -> None:
        """Test a debug generator that names no generator is a finding."""
        findings = validate_problem(build_sorting_variant(debug_generator="nope"))

        assert "debug_generator 'nope' does not name one of the problem's generators" in findings

    @pytest.mark.parametrize(
        "names",
        [["list"], ("a", "a"), ("",), (3,)],
        ids=["list", "duplicate", "empty-name", "not-text"],
    )
    def test_operation_names_must_be_unique_text_in_a_tuple(self, names: object) -> None:
        """Test operation names that are not a tuple of unique, non-empty text are a finding."""
        findings = validate_problem(build_sorting_variant(operation_names=names))

        assert any(
            finding.startswith("the class attribute 'operation_names' must be a tuple")
            for finding in findings
        )

    def test_a_shrink_candidate_equal_to_its_input_is_reported(self) -> None:
        """Test a shrink candidate equal to the input is a finding."""

        def shrink_to_copy(self: SortingProblem, input_data: list[int]) -> Iterator[list[int]]:
            return iter([list(input_data)])

        findings = validate_problem(build_sorting_variant(shrink=shrink_to_copy))

        assert any(
            finding.startswith("shrink() yields a candidate equal to its input for fixture")
            for finding in findings
        )

    def test_an_endless_shrink_hook_is_sampled_not_exhausted(self) -> None:
        """Test a shrink hook that never stops is only sampled, so validation finishes."""

        def shrink_endlessly(self: SortingProblem, input_data: list[int]) -> Iterator[list[int]]:
            while True:
                yield [*input_data, 1]

        assert validate_problem(build_sorting_variant(shrink=shrink_endlessly)) == []

    def test_a_hook_that_raises_does_not_stop_the_other_checks(self) -> None:
        """Test the findings of the other hooks are still reported when one hook raises."""

        def fail_to_provide_fixtures(self: SortingProblem) -> Iterator[Fixture[list[int]]]:
            raise RuntimeError("fixtures exploded")
            yield Fixture("never", [])

        def provide_no_generators(self: SortingProblem) -> tuple[()]:
            return ()

        problem = build_sorting_variant(
            fixtures=fail_to_provide_fixtures, generators=provide_no_generators
        )

        findings = validate_problem(problem)

        assert "fixtures() raised: RuntimeError: fixtures exploded" in findings
        assert "generators() returned no generators; provide at least one (the default)" in findings

    def test_verify_is_not_asked_about_wrong_answers(self) -> None:
        """Test the verifier is only shown outputs that are correctly sorted."""
        outputs: list[list[int]] = []

        def verify_and_record(
            self: SortingProblem, input_data: list[int], output: list[int]
        ) -> VerificationResult:
            outputs.append(output)
            return VerificationResult(True)

        validate_problem(build_sorting_variant(verify=verify_and_record))

        assert all(output == sorted(output) for output in outputs)


class TestInputRules:
    def test_a_fixture_that_breaks_the_rule_is_named(self) -> None:
        """Test a fixture that the input rule rejects is a finding that names the fixture."""

        def reject_more_than_one_value(self: SortingProblem, input_data: list[int]) -> str | None:
            return "must have at most one value" if len(input_data) > 1 else None

        findings = validate_problem(build_sorting_variant(check_input=reject_more_than_one_value))

        assert any(
            finding.startswith("check_input() rejects fixture 'duplicates': must have at most")
            for finding in findings
        )

    def test_a_generated_sample_that_breaks_the_rule_is_named(self) -> None:
        """Test a generated input that the input rule rejects is a finding that names the case."""

        def reject_empty_input(self: SortingProblem, input_data: list[int]) -> str | None:
            return "must not be empty" if not input_data else None

        findings = validate_problem(build_sorting_variant(check_input=reject_empty_input))

        assert "check_input() rejects generator 'uniform' at size 0: must not be empty" in findings
        assert "check_input() rejects fixture 'empty': must not be empty" in findings

    def test_a_rule_that_raises_is_named(self) -> None:
        """Test an input rule that raises is a finding that names the error."""

        def explode(self: SortingProblem, input_data: list[int]) -> str | None:
            raise RuntimeError("check exploded")

        findings = validate_problem(build_sorting_variant(check_input=explode))

        assert any(
            finding.startswith("check_input() raised for fixture 'empty': RuntimeError: check ex")
            for finding in findings
        )

    def test_a_rule_must_return_text_or_none(self) -> None:
        """Test an input rule that returns a boolean is a finding."""

        def return_false(self: SortingProblem, input_data: list[int]) -> bool:
            return False

        findings = validate_problem(build_sorting_variant(check_input=return_false))

        assert "check_input() must return text or None, got bool" in findings

    def test_shrink_candidates_the_rule_rejects_are_not_findings(self) -> None:
        """Test shrink candidates that the input rule rejects are never serialized or reported."""

        def require_three_values(self: SortingProblem, input_data: list[int]) -> str | None:
            return None if len(input_data) >= 3 or not input_data else "needs three values"

        # Candidates of fewer values would not serialize, but the shrinker never runs them.
        def shrink_to_unserializable(
            self: SortingProblem, input_data: list[int]
        ) -> Iterator[list[int]]:
            yield [2**40]
            yield [2**40, 1]

        problem = build_sorting_variant(
            check_input=require_three_values, shrink=shrink_to_unserializable
        )

        findings = validate_problem(problem)

        assert not any("shrink candidate" in finding for finding in findings)

    def test_shrink_candidates_the_rule_accepts_must_still_serialize(self) -> None:
        """Test a shrink candidate the input rule accepts but that cannot serialize is a finding."""

        def shrink_to_unserializable(
            self: SortingProblem, input_data: list[int]
        ) -> Iterator[list[int]]:
            yield [2**40]

        findings = validate_problem(build_sorting_variant(shrink=shrink_to_unserializable))

        assert any(
            "a shrink candidate of" in finding and "does not serialize" in finding
            for finding in findings
        )


class TestInputReading:
    def test_a_problem_that_reads_back_what_it_wrote_is_valid(self) -> None:
        """Test a problem whose reader returns what its writer wrote has no findings."""
        assert validate_problem(SortingProblem()) == []

    def test_an_input_that_comes_back_different_is_named(self) -> None:
        """Test a reader that returns another input is a finding that names the fixture."""

        def read_empty_input(self: SortingProblem, path: Path) -> list[int]:
            return []

        findings = validate_problem(build_sorting_variant(deserialize_input=read_empty_input))

        assert any(
            finding.startswith(
                "deserialize_input() does not return the input that serialize_input wrote for fixture"
            )
            for finding in findings
        )

    def test_a_reader_that_raises_is_named(self) -> None:
        """Test a reader that raises is a finding that names the error."""

        def fail_to_read(self: SortingProblem, path: Path) -> list[int]:
            raise OSError("disk gone")

        findings = validate_problem(build_sorting_variant(deserialize_input=fail_to_read))

        assert any(
            finding.startswith("deserialize_input() raised for fixture 'empty': OSError: disk gone")
            for finding in findings
        )

    def test_a_problem_without_a_reader_is_not_asked_for_one(self) -> None:
        """Test a problem that cannot read its inputs is not reported for it."""
        assert validate_problem(NoReaderSortingProblem()) == []
