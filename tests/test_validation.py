"""Tests for the problem validation kit."""

from __future__ import annotations

import importlib.util
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from algorithm_playground.core.cases import Fixture, InputGenerator
from algorithm_playground.core.problem import Problem, VerificationResult
from algorithm_playground.core.validation import assert_valid_problem, validate_problem
from algorithm_playground.problems.sorting import SortingProblem


def generate_values(random_generator: random.Random, size: int) -> list[int]:
    return [random_generator.randrange(10) for _ in range(size)]


def variant(**members: Any) -> SortingProblem:
    """Return the (valid) sorting problem with the given members replaced."""
    return type("Variant", (SortingProblem,), members)()


class TestValidProblems:
    def test_the_sorting_problem_is_valid(self) -> None:
        assert validate_problem(SortingProblem()) == []
        assert_valid_problem(SortingProblem())

    def test_the_distinct_count_example_is_valid(self, repository_root: Path) -> None:
        path = repository_root / "examples" / "distinct_count" / "distinct_count_problem.py"
        specification = importlib.util.spec_from_file_location("distinct_count_for_test", path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        assert_valid_problem(module.DistinctCountProblem())


class TestFindings:
    def test_assert_valid_problem_lists_every_finding(self) -> None:
        problem = variant(fixtures=lambda self: iter(()), generators=lambda self: ())
        with pytest.raises(AssertionError) as raised:
            assert_valid_problem(problem)
        message = str(raised.value)
        assert message.startswith("Problem 'sorting' is not valid:")
        assert "  - fixtures() returned no fixtures" in message
        assert "  - generators() returned no generators" in message

    def test_missing_name_and_description(self) -> None:
        problem = variant(name="", description="")
        findings = validate_problem(problem)
        assert "the class attribute 'name' must be a non-empty string" in findings
        assert "the class attribute 'description' must be a non-empty string" in findings

    def test_fixture_names_must_be_non_empty_and_unique(self) -> None:
        def fixtures(self: Any) -> Iterator[Fixture[list[int]]]:
            yield Fixture("a", [])
            yield Fixture("a", [1])
            yield Fixture("", [2])

        findings = validate_problem(variant(fixtures=fixtures))
        assert "the fixture name 'a' is used more than once" in findings
        assert "a fixture has an empty name" in findings

    def test_fixtures_must_be_fixture_objects(self) -> None:
        findings = validate_problem(variant(fixtures=lambda self: [([1], "x")]))
        assert "fixtures() must yield Fixture objects, got tuple" in findings

    def test_a_fixture_that_does_not_serialize_is_named(self) -> None:
        def fixtures(self: Any) -> Iterator[Fixture[list[int]]]:
            yield Fixture("huge", [2**40])

        findings = validate_problem(variant(fixtures=fixtures))
        assert any(
            finding.startswith("fixture 'huge' does not serialize: ValueError")
            for finding in findings
        )

    @pytest.mark.parametrize("name", ["", "has space", "has:colon"])
    def test_generator_names_must_be_usable_in_identifiers(self, name: str) -> None:
        generators = lambda self: (InputGenerator(name, "bad", generate_values),)  # noqa: E731
        findings = validate_problem(variant(generators=generators))
        assert (
            f"the generator name {name!r} must be non-empty and contain no colon or whitespace"
            in (findings)
        )

    def test_generator_names_must_be_unique(self) -> None:
        generators = lambda self: (  # noqa: E731
            InputGenerator("same", "one", generate_values),
            InputGenerator("same", "two", generate_values),
        )
        findings = validate_problem(variant(generators=generators))
        assert "the generator name 'same' is used more than once" in findings

    def test_a_generator_must_be_deterministic_for_a_fixed_seed(self) -> None:
        generators = lambda self: (  # noqa: E731
            InputGenerator(
                "unseeded",
                "uses global randomness",
                lambda random_generator, size: [random.random()] * size,
            ),
        )
        findings = validate_problem(variant(generators=generators))
        assert "generator 'unseeded' at size 5 returned different inputs for the same seed" in (
            findings
        )

    def test_a_generator_must_accept_size_zero(self) -> None:
        def generate(random_generator: random.Random, size: int) -> list[int]:
            if size == 0:
                raise ValueError("size zero is not supported")
            return [random_generator.randrange(10) for _ in range(size)]

        findings = validate_problem(
            variant(generators=lambda self: (InputGenerator("g", "g", generate),))
        )
        assert "generator 'g' at size 0 raised: ValueError: size zero is not supported" in findings

    def test_an_expected_output_that_does_not_verify_is_reported(self) -> None:
        problem = variant(expected_output=lambda self, input_data: sorted(input_data, reverse=True))
        findings = validate_problem(problem)
        assert any(
            finding.startswith("verify() rejects expected_output() for fixture")
            for finding in findings
        )

    def test_an_input_output_frame_that_raises_is_reported(self) -> None:
        def explode(self: Any, input_data: list[int], output: list[int]) -> None:
            raise RuntimeError("cannot draw")

        findings = validate_problem(variant(input_output_frame=explode))
        assert any(
            finding.startswith("input_output_frame() raised for fixture")
            and "cannot draw" in finding
            for finding in findings
        )

    def test_an_input_output_frame_that_is_not_a_frame_is_reported(self) -> None:
        problem = variant(input_output_frame=lambda self, input_data, output: "a picture")
        assert "input_output_frame() must return a Frame or None, got str" in validate_problem(
            problem
        )

    def test_no_expected_output_is_fine(self) -> None:
        assert validate_problem(variant(expected_output=lambda self, input_data: None)) == []

    def test_shrink_candidates_must_serialize(self) -> None:
        problem = variant(shrink=lambda self, input_data: iter([[2**40]]))
        findings = validate_problem(problem)
        assert any("a shrink candidate of fixture" in finding for finding in findings)

    def test_a_shrink_hook_that_raises_is_reported(self) -> None:
        def shrink(self: Any, input_data: list[int]) -> Iterator[list[int]]:
            raise RuntimeError("no shrinking today")
            yield []

        findings = validate_problem(variant(shrink=shrink))
        assert any(
            "shrink() raised for fixture" in finding and "no shrinking today" in finding
            for finding in findings
        )

    def test_describe_hooks_must_return_text(self) -> None:
        problem = variant(describe_input=lambda self, input_data, *, limit: 5)
        findings = validate_problem(problem)
        assert "describe_input() must return text, got int" in findings

    def test_generators_are_sampled_from_the_minimum_size_up(self) -> None:
        sizes: list[int] = []

        def generate(random_generator: random.Random, size: int) -> list[int]:
            sizes.append(size)
            if size < 4:
                raise ValueError("needs four values")
            return [random_generator.randrange(10) for _ in range(size)]

        problem = variant(
            minimum_size=4,
            debug_generator=None,
            generators=lambda self: (InputGenerator("g", "g", generate),),
        )
        assert validate_problem(problem) == []
        assert min(sizes) == 4

    def test_a_generator_that_fails_below_the_minimum_size_is_reported_there(self) -> None:
        def generate(random_generator: random.Random, size: int) -> list[int]:
            if size < 4:
                raise ValueError("needs four values")
            return [0] * size

        findings = validate_problem(
            variant(generators=lambda self: (InputGenerator("g", "g", generate),))
        )
        assert "generator 'g' at size 0 raised: ValueError: needs four values" in findings

    @pytest.mark.parametrize("value", [-1, "3", 1.5, True])
    def test_the_minimum_size_must_be_a_non_negative_integer(self, value: Any) -> None:
        findings = validate_problem(variant(minimum_size=value))
        assert any(
            finding.startswith("the class attribute 'minimum_size' must be an integer")
            for finding in findings
        )

    def test_the_debug_generator_must_name_a_generator(self) -> None:
        assert validate_problem(variant(debug_generator="sorted")) == []
        assert "debug_generator 'nope' does not name one of the problem's generators" in (
            validate_problem(variant(debug_generator="nope"))
        )

    @pytest.mark.parametrize("names", [["list"], ("a", "a"), ("",), (3,)])
    def test_operation_names_must_be_unique_text_in_a_tuple(self, names: Any) -> None:
        findings = validate_problem(variant(operation_names=names))
        assert any(
            finding.startswith("the class attribute 'operation_names' must be a tuple")
            for finding in findings
        )

    def test_a_shrink_candidate_equal_to_its_input_is_reported(self) -> None:
        problem = variant(shrink=lambda self, input_data: iter([list(input_data)]))
        findings = validate_problem(problem)
        assert any(
            finding.startswith("shrink() yields a candidate equal to its input for fixture")
            for finding in findings
        )

    def test_an_endless_shrink_hook_is_sampled_not_exhausted(self) -> None:
        def shrink(self: Any, input_data: list[int]) -> Iterator[list[int]]:
            while True:
                yield [*input_data, 1]

        assert validate_problem(variant(shrink=shrink)) == []

    def test_a_hook_that_raises_does_not_stop_the_other_checks(self) -> None:
        def fixtures(self: Any) -> Iterator[Fixture[list[int]]]:
            raise RuntimeError("fixtures exploded")
            yield Fixture("never", [])

        findings = validate_problem(variant(fixtures=fixtures, generators=lambda self: ()))
        assert "fixtures() raised: RuntimeError: fixtures exploded" in findings
        assert "generators() returned no generators; provide at least one (the default)" in findings

    def test_verify_is_not_asked_about_wrong_answers(self) -> None:
        calls: list[Any] = []

        def verify(self: Any, input_data: list[int], output: list[int]) -> VerificationResult:
            calls.append(output)
            return VerificationResult(True)

        validate_problem(variant(verify=verify))
        assert all(output == sorted(output) for output in calls)


class TestInputRules:
    def test_a_fixture_that_breaks_the_rule_is_named(self) -> None:
        def check_input(self: Any, input_data: list[int]) -> str | None:
            return "must have at most one value" if len(input_data) > 1 else None

        findings = validate_problem(variant(check_input=check_input))
        assert any(
            finding.startswith("check_input() rejects fixture 'duplicates': must have at most")
            for finding in findings
        )

    def test_a_generated_sample_that_breaks_the_rule_is_named(self) -> None:
        def check_input(self: Any, input_data: list[int]) -> str | None:
            return "must not be empty" if not input_data else None

        findings = validate_problem(variant(check_input=check_input))
        assert "check_input() rejects generator 'uniform' at size 0: must not be empty" in findings
        assert "check_input() rejects fixture 'empty': must not be empty" in findings

    def test_a_rule_that_raises_is_named(self) -> None:
        def check_input(self: Any, input_data: list[int]) -> str | None:
            raise RuntimeError("check exploded")

        findings = validate_problem(variant(check_input=check_input))
        assert any(
            finding.startswith("check_input() raised for fixture 'empty': RuntimeError: check ex")
            for finding in findings
        )

    def test_a_rule_must_return_text_or_none(self) -> None:
        findings = validate_problem(variant(check_input=lambda self, input_data: False))
        assert "check_input() must return text or None, got bool" in findings

    def test_shrink_candidates_the_rule_rejects_are_not_findings(self) -> None:
        def check_input(self: Any, input_data: list[int]) -> str | None:
            return None if len(input_data) >= 3 or not input_data else "needs three values"

        # Candidates of fewer values would not serialize, but the shrinker never runs them.
        def shrink(self: Any, input_data: list[int]) -> Iterator[list[int]]:
            yield [2**40]
            yield [2**40, 1]

        findings = validate_problem(variant(check_input=check_input, shrink=shrink))
        assert not any("shrink candidate" in finding for finding in findings)

    def test_shrink_candidates_the_rule_accepts_must_still_serialize(self) -> None:
        def shrink(self: Any, input_data: list[int]) -> Iterator[list[int]]:
            yield [2**40]

        findings = validate_problem(variant(shrink=shrink))
        assert any(
            "a shrink candidate of" in finding and "does not serialize" in finding
            for finding in findings
        )


class TestInputReading:
    def test_a_problem_that_reads_back_what_it_wrote_is_valid(self) -> None:
        assert validate_problem(SortingProblem()) == []

    def test_an_input_that_comes_back_different_is_named(self) -> None:
        def deserialize_input(self: Any, path: Path) -> list[int]:
            return []

        findings = validate_problem(variant(deserialize_input=deserialize_input))
        assert any(
            finding.startswith(
                "deserialize_input() does not return the input that serialize_input wrote for fixture"
            )
            for finding in findings
        )

    def test_a_reader_that_raises_is_named(self) -> None:
        def deserialize_input(self: Any, path: Path) -> list[int]:
            raise OSError("disk gone")

        findings = validate_problem(variant(deserialize_input=deserialize_input))
        assert any(
            finding.startswith("deserialize_input() raised for fixture 'empty': OSError: disk gone")
            for finding in findings
        )

    def test_a_problem_without_a_reader_is_not_asked_for_one(self) -> None:
        class NoReader(SortingProblem):
            deserialize_input = Problem.deserialize_input

        assert validate_problem(NoReader()) == []
