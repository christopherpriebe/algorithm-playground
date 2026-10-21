"""Tests for the test engine.

Engine logic runs in-process against fake runners. A few tests use real
subprocesses to cover the integration with the runner.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeRunners, crash, drop_last_above_five, named, sort_correctly

from algorithm_playground.core.cases import Case, FixtureOrigin, ShrunkOrigin, resolve_case
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.runner import RunnerError
from algorithm_playground.core.testing import (
    CaseOutcome,
    CasePhase,
    CaseProgress,
    CaseStatus,
    TestReport,
    run_tests,
)
from algorithm_playground.problems.sorting import SortingProblem

LARGE_GENERATED = "generated:uniform:size=12:seed=5"
SMALL_GENERATED = "generated:uniform:size=4:seed=6"


def cases_of(*identifiers: str) -> list[Case[Any]]:
    problem = SortingProblem()
    return [resolve_case(problem, identifier) for identifier in identifiers]


def run_fake(
    behaviors: dict[str, Any], identifiers: list[str], **options: Any
) -> tuple[TestReport, FakeRunners]:
    runners = FakeRunners(behaviors)
    report = run_tests(
        SortingProblem(),
        named(*behaviors),
        cases_of(*identifiers),
        runner_factory=runners,
        **options,
    )
    return report, runners


class UnknownExpectedProblem(SortingProblem):
    """Sorting without an expected output, as for a problem with many valid answers."""

    def expected_output(self, input_data: list[int]) -> list[int] | None:  # ty: ignore[invalid-method-override]
        return None


class ExplodingHooksProblem(SortingProblem):
    def describe_input(self, input_data: list[int], *, limit: int) -> str:
        raise RuntimeError("cannot describe")

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        raise RuntimeError("shrink exploded")


class RepeatingShrinkProblem(SortingProblem):
    """A shrink hook that never offers anything but a copy of its input."""

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        while True:
            yield list(input_data)


class CountingShrinkProblem(SortingProblem):
    """A problem whose shrink hook offers an unrunnable candidate before the useful ones."""

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        yield [2**40]
        yield from super().shrink(input_data)


class ShortInputsInvalidProblem(SortingProblem):
    """Sorting where an input needs at least three values, as a rule of the problem."""

    def check_input(self, input_data: list[int]) -> str | None:
        return None if len(input_data) >= 3 else "needs at least three values"


class RejectingEverythingProblem(SortingProblem):
    """A problem whose shrink hook offers endless candidates that are all invalid inputs."""

    def check_input(self, input_data: list[int]) -> str | None:
        return "invalid" if len(input_data) < 100 else None

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        for length in range(10**9):
            yield [length]


class ExplodingCheckProblem(SortingProblem):
    def check_input(self, input_data: list[int]) -> str | None:
        raise RuntimeError("check exploded")


class RecordingDescriptionsProblem(SortingProblem):
    """Sorting that records the focus each describe_output call received."""

    def __init__(self) -> None:
        self.focuses: list[int | None] = []

    def describe_output(self, output: list[int], *, limit: int, focus: int | None = None) -> str:
        self.focuses.append(focus)
        return super().describe_output(output, limit=limit, focus=focus)


class TestOutcomes:
    def test_correct_implementation_passes_every_case(self) -> None:
        report, _ = run_fake({"a": sort_correctly}, ["fixture:empty", LARGE_GENERATED])
        assert report.passed
        assert report.failures() == ()
        assert report.problem_name == "sorting"
        assert report.implementation_names == ("a",)
        assert report.case_identifiers == ("fixture:empty", LARGE_GENERATED)
        assert all(outcome.status is CaseStatus.PASSED for outcome in report.outcomes)
        assert all(outcome.message == "" and outcome.detail is None for outcome in report.outcomes)

    def test_a_wrong_implementation_fails_without_affecting_the_correct_one(self) -> None:
        report, _ = run_fake(
            {"good": sort_correctly, "bad": drop_last_above_five},
            ["fixture:empty", SMALL_GENERATED, LARGE_GENERATED],
        )
        assert not report.passed
        assert [outcome.status for outcome in report.outcomes_for("good")] == [
            CaseStatus.PASSED
        ] * 3
        assert [outcome.status for outcome in report.outcomes_for("bad")] == [
            CaseStatus.PASSED,
            CaseStatus.PASSED,
            CaseStatus.FAILED,
        ]
        failed = report.outcome(LARGE_GENERATED, "bad")
        assert "Output length 11 does not match input length 12" in failed.message

    def test_outcomes_are_ordered_by_case_then_implementation(self) -> None:
        report, _ = run_fake(
            {"a": sort_correctly, "b": sort_correctly}, ["fixture:single", SMALL_GENERATED]
        )
        pairs = [
            (outcome.case_identifier, outcome.implementation_name) for outcome in report.outcomes
        ]
        assert pairs == [
            ("fixture:single", "a"),
            ("fixture:single", "b"),
            (SMALL_GENERATED, "a"),
            (SMALL_GENERATED, "b"),
        ]

    def test_failures_lists_only_non_passing_outcomes(self) -> None:
        report, _ = run_fake(
            {"good": sort_correctly, "bad": drop_last_above_five},
            ["fixture:empty", LARGE_GENERATED],
        )
        assert [
            (outcome.implementation_name, outcome.case_identifier) for outcome in report.failures()
        ] == [("bad", LARGE_GENERATED)]

    def test_a_runner_error_is_an_error_outcome_with_the_full_message(self) -> None:
        report, _ = run_fake({"crash": crash}, ["fixture:single"])
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert "exited with code 3" in outcome.message
        assert "kaboom" in outcome.message

    def test_an_exception_in_verification_is_an_error_outcome(
        self, exploding_problem: SortingProblem
    ) -> None:
        report = run_tests(
            exploding_problem,
            named("a"),
            cases_of("fixture:single"),
            runner_factory=FakeRunners({"a": sort_correctly}),
        )
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert outcome.message == "Verification raised RuntimeError: verifier exploded"
        assert outcome.detail is not None
        assert outcome.detail.actual_text == "[42]"

    def test_the_factory_receives_the_problem_and_each_implementation(self) -> None:
        received: list[tuple[str, str]] = []
        runners = FakeRunners({"a": sort_correctly})

        def factory(problem: Any, implementation: Implementation) -> Any:
            received.append((problem.name, implementation.name))
            return runners(problem, implementation)

        run_tests(SortingProblem(), named("a"), cases_of("fixture:empty"), runner_factory=factory)
        assert received == [("sorting", "a")]

    def test_rejects_duplicate_case_identifiers(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            run_fake({"a": sort_correctly}, ["fixture:empty", "fixture:empty"])

    def test_rejects_no_cases(self) -> None:
        with pytest.raises(ValueError, match="At least one case"):
            run_fake({"a": sort_correctly}, [])

    def test_rejects_duplicate_implementation_names(self) -> None:
        with pytest.raises(ValueError, match="Duplicate implementation name"):
            run_tests(SortingProblem(), named("a", "a"), cases_of("fixture:empty"))

    def test_rejects_an_empty_implementation_list(self) -> None:
        with pytest.raises(ValueError, match="At least one implementation"):
            run_tests(SortingProblem(), [], cases_of("fixture:empty"))


class TestFailureDetails:
    def test_a_failure_carries_the_input_the_expected_and_the_actual_output(self) -> None:
        report, _ = run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED], shrink=False)
        detail = report.outcomes[0].detail
        assert detail is not None
        problem = SortingProblem()
        data = resolve_case(problem, LARGE_GENERATED).input_data
        assert detail.input_text == problem.describe_input(data, limit=300)
        assert detail.expected_text == problem.describe_output(sorted(data), limit=300)
        assert detail.actual_text == problem.describe_output(sorted(data)[:-1], limit=300)

    def test_descriptions_are_shortened_to_the_limit(self) -> None:
        report, _ = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], shrink=False, description_limit=40
        )
        detail = report.outcomes[0].detail
        assert detail is not None
        assert "(12 values)" in detail.input_text
        assert len(detail.input_text) <= 40

    def test_a_runner_error_has_no_actual_output(self) -> None:
        report, _ = run_fake({"crash": crash}, ["fixture:two_unsorted"])
        detail = report.outcomes[0].detail
        assert detail is not None
        assert detail.input_text == "[2, 1]"
        assert detail.expected_text == "[1, 2]"
        assert detail.actual_text is None

    def test_a_problem_without_expected_output_reports_none(self) -> None:
        report = run_tests(
            UnknownExpectedProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
            shrink=False,
        )
        detail = report.outcomes[0].detail
        assert detail is not None
        assert detail.expected_text is None
        assert detail.actual_text is not None

    def test_a_describe_hook_that_raises_does_not_break_the_report(self) -> None:
        report = run_tests(
            ExplodingHooksProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        detail = report.outcomes[0].detail
        assert detail is not None
        assert detail.input_text == "(could not describe: RuntimeError: cannot describe)"
        assert detail.actual_text is not None


class TestShrinking:
    def test_a_failing_generated_case_is_shrunk_to_the_smallest_failing_input(self) -> None:
        report, _ = run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED])
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 6
        assert shrunk.case.identifier == f"shrunk:{LARGE_GENERATED}"
        assert shrunk.case.origin == ShrunkOrigin(LARGE_GENERATED)
        assert shrunk.message == "Output length 5 does not match input length 6"
        assert shrunk.detail.input_text == "[0, 0, 0, 0, 0, 0]"
        assert shrunk.detail.expected_text == "[0, 0, 0, 0, 0, 0]"
        assert shrunk.detail.actual_text == "[0, 0, 0, 0, 0]"

    def test_shrinking_only_runs_the_implementation_that_failed(self) -> None:
        _, runners = run_fake(
            {"good": sort_correctly, "bad": drop_last_above_five}, [LARGE_GENERATED]
        )
        assert len(runners.inputs_of("good")) == 1
        assert len(runners.inputs_of("bad")) > 1

    def test_fixtures_are_not_shrunk(self) -> None:
        report, runners = run_fake({"bad": drop_last_above_five}, ["fixture:already_sorted"])
        assert report.outcomes[0].status is CaseStatus.FAILED
        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_no_shrink_turns_it_off(self) -> None:
        report, runners = run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED], shrink=False)
        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_a_passing_case_is_not_shrunk(self) -> None:
        _, runners = run_fake({"good": sort_correctly}, [LARGE_GENERATED])
        assert len(runners.calls) == 1

    def test_an_error_is_shrunk_too(self) -> None:
        def crash_above_three(values: list[int]) -> list[int]:
            if len(values) > 3:
                return crash(values)
            return sorted(values)

        report, _ = run_fake({"bad": crash_above_three}, [LARGE_GENERATED])
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert outcome.shrunk is not None
        assert outcome.shrunk.case.input_data == [0] * 4

    def test_a_problem_without_a_shrink_hook_reports_no_shrunk_input(self) -> None:
        class NoShrinkProblem(SortingProblem):
            def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
                return iter(())

        report = run_tests(
            NoShrinkProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        assert report.outcomes[0].status is CaseStatus.FAILED
        assert report.outcomes[0].shrunk is None

    def test_the_run_cap_limits_one_shrink(self) -> None:
        _, runners = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], maximum_shrink_runs=3
        )
        assert len(runners.calls) == 1 + 3

    def test_the_cap_still_keeps_the_best_input_found_so_far(self) -> None:
        report, _ = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], maximum_shrink_runs=3
        )
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert 6 <= len(shrunk.case.input_data) < 12

    def test_a_spent_time_budget_means_no_shrinking(self) -> None:
        report, runners = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], shrink_time_budget_seconds=0.0
        )
        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_only_a_limited_number_of_cases_is_shrunk_per_implementation(self) -> None:
        identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9, 10)]
        report, _ = run_fake({"bad": drop_last_above_five}, identifiers, maximum_shrunk_cases=2)
        assert [outcome.shrunk is not None for outcome in report.outcomes] == [True, True, False]

    def test_a_candidate_that_cannot_be_run_is_skipped(self) -> None:
        def refuse_huge_values(values: list[int]) -> list[int]:
            if any(value > 2**31 for value in values):
                raise ValueError("value out of range")
            return drop_last_above_five(values)

        report = run_tests(
            CountingShrinkProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": refuse_huge_values}),
        )
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 6

    def test_a_shrink_hook_that_raises_is_reported_in_a_note(self) -> None:
        report = run_tests(
            ExplodingHooksProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.FAILED
        assert outcome.shrunk is None
        assert (
            outcome.shrink_note == "the problem's shrink hook raised RuntimeError: shrink exploded"
        )

    def test_a_shrink_hook_that_raises_part_way_keeps_what_was_found(self) -> None:
        class RaisesLate(SortingProblem):
            def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
                if len(input_data) <= 6:
                    raise RuntimeError("no more ideas")
                yield input_data[: len(input_data) // 2]
                yield input_data[:6]

        report = run_tests(
            RaisesLate(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        outcome = report.outcomes[0]
        assert outcome.shrunk is not None and len(outcome.shrunk.case.input_data) == 6
        assert outcome.shrink_note is not None and "no more ideas" in outcome.shrink_note

    def test_a_clean_shrink_has_no_note(self) -> None:
        report, _ = run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED])
        assert report.outcomes[0].shrink_note is None

    def test_a_hook_that_only_yields_copies_of_the_input_cannot_keep_a_shrink_going(self) -> None:
        started = time.monotonic()
        report = run_tests(
            RepeatingShrinkProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            maximum_shrink_runs=50,
            runner_factory=(runners := FakeRunners({"bad": drop_last_above_five})),
        )
        assert time.monotonic() - started < 5
        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_the_time_budget_stops_a_hook_that_never_stops_yielding_copies(self) -> None:
        started = time.monotonic()
        run_tests(
            RepeatingShrinkProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            maximum_shrink_runs=10**12,
            shrink_time_budget_seconds=0.2,
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        assert time.monotonic() - started < 5

    def test_the_deadline_can_pass_part_way_and_the_best_input_so_far_is_kept(self) -> None:
        def slow_drop_last(values: list[int]) -> list[int]:
            time.sleep(0.03)
            return drop_last_above_five(values)

        started = time.monotonic()
        report, runners = run_fake(
            {"bad": slow_drop_last},
            [LARGE_GENERATED],
            maximum_shrink_runs=10**6,
            shrink_time_budget_seconds=0.25,
        )
        assert time.monotonic() - started < 5
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None and len(shrunk.case.input_data) < 12
        assert len(runners.calls) < 40

    def test_every_candidate_runs_with_a_timeout_the_budget_still_allows(self) -> None:
        _, runners = run_fake(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            timeout_seconds=100.0,
            shrink_time_budget_seconds=5.0,
        )
        original, *candidates = runners.timeouts
        assert original is None
        assert candidates and all(timeout is not None and timeout <= 5.0 for timeout in candidates)

    def test_the_timeout_of_an_implementation_bounds_a_candidate_too(self) -> None:
        implementation = Implementation(name="bad", command=("fake",), timeout_seconds=2.0)
        runners = FakeRunners({"bad": drop_last_above_five})
        run_tests(
            SortingProblem(),
            [implementation],
            cases_of(LARGE_GENERATED),
            timeout_seconds=100.0,
            runner_factory=runners,
        )
        assert all(timeout is not None and timeout <= 2.0 for timeout in runners.timeouts[1:])

    def test_a_candidate_that_times_out_under_a_shortened_limit_proves_nothing(self) -> None:
        def time_out_above_three(values: list[int]) -> list[int]:
            if len(values) > 3:
                raise RunnerError("timed out after 1.000s", category="timeout")
            return sorted(values)

        report, _ = run_fake(
            {"slow": time_out_above_three},
            [LARGE_GENERATED],
            timeout_seconds=1000.0,
            shrink_time_budget_seconds=30.0,
        )
        assert report.outcomes[0].status is CaseStatus.ERROR
        assert report.outcomes[0].shrunk is None

    def test_a_failure_does_not_drift_into_an_unrelated_error_while_shrinking(self) -> None:
        def wrong_when_large_crashing_when_tiny(values: list[int]) -> list[int]:
            if len(values) <= 2:
                raise RunnerError("exited with code 7", category="exit code 7")
            return drop_last_above_five(values)

        report, _ = run_fake({"bad": wrong_when_large_crashing_when_tiny}, [LARGE_GENERATED])
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.FAILED
        assert outcome.shrunk is not None
        assert outcome.shrunk.case.input_data == [0] * 6
        assert "does not match input length" in outcome.shrunk.message

    def test_an_error_does_not_drift_into_a_failure_while_shrinking(self) -> None:
        def crash_when_large_wrong_when_medium(values: list[int]) -> list[int]:
            if len(values) > 8:
                raise RunnerError("exited with code 7", category="exit code 7")
            return drop_last_above_five(values)

        report, _ = run_fake({"bad": crash_when_large_wrong_when_medium}, [LARGE_GENERATED])
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert outcome.shrunk is not None
        assert outcome.shrunk.case.input_data == [0] * 9

    def test_an_error_keeps_its_kind_while_shrinking(self) -> None:
        def exit_code_depends_on_size(values: list[int]) -> list[int]:
            if len(values) > 8:
                raise RunnerError("exited with code 7", category="exit code 7")
            if len(values) > 3:
                raise RunnerError("exited with code 9", category="exit code 9")
            return sorted(values)

        report, _ = run_fake({"bad": exit_code_depends_on_size}, [LARGE_GENERATED])
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 9
        assert "code 7" in shrunk.message


class TestShrinkNotes:
    def test_the_candidate_limit_is_named_when_it_ends_a_shrink(self) -> None:
        report, _ = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], maximum_shrink_runs=3
        )
        assert report.outcomes[0].shrink_note == (
            "shrinking stopped after 3 candidates, its limit; a smaller failing input may exist"
        )

    def test_the_time_budget_is_named_when_it_ends_a_shrink(self) -> None:
        def slow_drop_last(values: list[int]) -> list[int]:
            time.sleep(0.03)
            return drop_last_above_five(values)

        report, _ = run_fake(
            {"bad": slow_drop_last},
            [LARGE_GENERATED],
            maximum_shrink_runs=10**6,
            shrink_time_budget_seconds=0.25,
        )
        note = report.outcomes[0].shrink_note
        assert note is not None
        assert note.startswith("shrinking stopped when its time budget (0.25 seconds per ")
        assert "a smaller failing input may exist" in note

    def test_a_case_left_unshrunk_by_the_case_limit_says_so(self) -> None:
        identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9, 10)]
        report, _ = run_fake({"bad": drop_last_above_five}, identifiers, maximum_shrunk_cases=2)
        assert [outcome.shrink_note for outcome in report.outcomes] == [
            None,
            None,
            "not shrunk: the limit of 2 shrunk cases per implementation was reached",
        ]

    def test_a_case_left_unshrunk_by_a_spent_time_budget_says_so(self) -> None:
        report, _ = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], shrink_time_budget_seconds=0.0
        )
        assert report.outcomes[0].shrink_note == (
            "not shrunk: the time budget for shrinking (0 seconds per implementation) was used up"
        )

    def test_a_fixture_and_a_passing_case_have_no_note(self) -> None:
        report, _ = run_fake({"bad": drop_last_above_five}, ["fixture:duplicates", SMALL_GENERATED])
        assert [outcome.shrink_note for outcome in report.outcomes] == [None, None]

    def test_no_shrink_leaves_no_note(self) -> None:
        report, _ = run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED], shrink=False)
        assert report.outcomes[0].shrink_note is None


class TestFailuresThatAreNotShrunk:
    def test_a_verification_that_raises_is_not_shrunk(
        self, exploding_problem: SortingProblem
    ) -> None:
        runners = FakeRunners({"good": sort_correctly})
        report = run_tests(
            exploding_problem,
            named("good"),
            cases_of(LARGE_GENERATED),
            runner_factory=runners,
        )
        outcome = report.outcomes[0]
        assert outcome.category == "verification error"
        assert outcome.shrunk is None
        assert outcome.shrink_note == (
            "not shrunk: the verification error failure comes from the problem's own hooks, "
            "not from the implementation"
        )
        assert len(runners.calls) == 1

    def test_an_input_that_cannot_be_serialized_is_not_shrunk(self) -> None:
        def cannot_serialize(values: list[int]) -> list[int]:
            raise RunnerError("serialize_input raised", category="serialization")

        report, runners = run_fake({"bad": cannot_serialize}, [LARGE_GENERATED])
        outcome = report.outcomes[0]
        assert outcome.shrunk is None
        assert outcome.shrink_note is not None
        assert outcome.shrink_note.startswith("not shrunk: the serialization failure comes from")
        assert len(runners.calls) == 1

    def test_a_failure_of_the_implementation_is_still_shrunk(self) -> None:
        report, _ = run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED])
        assert report.outcomes[0].shrunk is not None

    @staticmethod
    def time_out_above_three(values: list[int]) -> list[int]:
        if len(values) > 3:
            raise RunnerError("timed out after 1.000s", category="timeout")
        return sorted(values)

    def test_a_timeout_longer_than_the_shrink_budget_is_not_shrunk(self) -> None:
        report, runners = run_fake(
            {"slow": self.time_out_above_three},
            [LARGE_GENERATED],
            timeout_seconds=60.0,
            shrink_time_budget_seconds=30.0,
        )
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert outcome.shrunk is None
        assert outcome.shrink_note == "not shrunk: the timeout is longer than the shrink budget"
        assert len(runners.calls) == 1

    def test_a_timeout_the_shrink_budget_covers_is_shrunk(self) -> None:
        report, _ = run_fake(
            {"slow": self.time_out_above_three},
            [LARGE_GENERATED],
            timeout_seconds=1.0,
            shrink_time_budget_seconds=30.0,
        )
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 4
        assert report.outcomes[0].shrink_note is None

    def test_a_spent_budget_is_named_before_a_timeout_that_is_longer_than_it(self) -> None:
        identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9)]
        report, _ = run_fake(
            {"slow": self.time_out_above_three},
            identifiers,
            timeout_seconds=1.0,
            shrink_time_budget_seconds=0.0,
        )
        assert [outcome.shrink_note for outcome in report.outcomes] == [
            "not shrunk: the time budget for shrinking (0 seconds per implementation) was used up"
        ] * 2


class TestShrinkingAndTheValidityOfInputs:
    def test_candidates_that_are_not_valid_inputs_are_skipped_and_never_run(self) -> None:
        report = run_tests(
            ShortInputsInvalidProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=(runners := FakeRunners({"bad": drop_last_above_five})),
        )
        # Without the rule the failure shrinks to six values; the rule changes nothing here,
        # but no candidate of fewer than three values was ever run.
        assert all(len(values) >= 3 for values in runners.inputs_of("bad"))
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None and len(shrunk.case.input_data) == 6

    def test_a_rule_can_force_a_larger_shrunk_input(self) -> None:
        class NeedsEightValues(SortingProblem):
            def check_input(self, input_data: list[int]) -> str | None:
                return None if len(input_data) >= 8 else "too short"

        report = run_tests(
            NeedsEightValues(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None and len(shrunk.case.input_data) == 8

    def test_rejected_candidates_count_against_the_budget(self) -> None:
        started = time.monotonic()
        report = run_tests(
            RejectingEverythingProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            maximum_shrink_runs=25,
            runner_factory=(runners := FakeRunners({"bad": drop_last_above_five})),
        )
        assert time.monotonic() - started < 5
        assert len(runners.calls) == 1
        assert report.outcomes[0].shrunk is None
        assert report.outcomes[0].shrink_note is not None
        assert "after 25 candidates" in report.outcomes[0].shrink_note

    def test_a_check_that_raises_is_reported_in_a_note_naming_the_hook(self) -> None:
        report = run_tests(
            ExplodingCheckProblem(),
            named("bad"),
            cases_of(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        assert report.outcomes[0].shrunk is None
        assert report.outcomes[0].shrink_note == (
            "the problem's check_input hook raised RuntimeError: check exploded"
        )


class TestFocusAndCategory:
    def test_the_position_the_verifier_names_is_passed_to_the_describe_hook(self) -> None:
        problem = RecordingDescriptionsProblem()
        run_tests(
            problem,
            named("bad"),
            cases_of(LARGE_GENERATED),
            shrink=False,
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        # The expected output and the actual output of the one failure, both at the
        # first difference (the missing last element).
        assert problem.focuses == [11, 11]

    def test_a_failure_without_a_position_describes_the_outputs_without_one(self) -> None:
        problem = RecordingDescriptionsProblem()
        run_tests(
            problem,
            named("crash"),
            cases_of("fixture:two_unsorted"),
            runner_factory=FakeRunners({"crash": crash}),
        )
        assert problem.focuses == [None]

    def test_the_window_around_the_difference_is_in_the_description(self) -> None:
        report, _ = run_fake(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], shrink=False, description_limit=45
        )
        detail = report.outcomes[0].detail
        assert detail is not None
        assert detail.expected_text is not None and detail.actual_text is not None
        assert (
            detail.expected_text.startswith("[..., ") and "index 11 shown" in detail.expected_text
        )
        assert detail.actual_text.startswith("[..., ") and "index 10 shown" in detail.actual_text

    def test_a_failure_records_its_category(self) -> None:
        report, _ = run_fake(
            {"bad": drop_last_above_five, "crashing": crash}, ["fixture:duplicates"]
        )
        assert report.outcome("fixture:duplicates", "bad").category == "wrong length"
        assert report.outcome("fixture:duplicates", "crashing").category == "error"
        assert report.outcome("fixture:duplicates", "bad").status is CaseStatus.FAILED

    def test_a_passing_outcome_has_no_category(self) -> None:
        report, _ = run_fake({"a": sort_correctly}, ["fixture:empty"])
        assert report.outcomes[0].category == ""

    def test_shrinking_keeps_the_category_the_verifier_named(self) -> None:
        def short_when_long_else_unsorted(values: list[int]) -> list[int]:
            return values[:-1] if len(values) > 5 else sorted(values, reverse=True)

        report, _ = run_fake({"mixed": short_when_long_else_unsorted}, [LARGE_GENERATED])
        outcome = report.outcomes[0]
        assert outcome.category == "wrong length"
        # Inputs of five values or fewer fail too, as "not sorted": not the same way.
        assert outcome.shrunk is not None and len(outcome.shrunk.case.input_data) == 6


class TestProgress:
    def test_events_follow_each_run_and_end_with_the_completed_outcome(self) -> None:
        events: list[CaseProgress] = []
        report, _ = run_fake(
            {"a": sort_correctly, "b": sort_correctly},
            ["fixture:empty"],
            on_progress=events.append,
        )
        assert [(event.implementation_name, event.phase) for event in events] == [
            ("a", CasePhase.RUNNING),
            ("a", CasePhase.COMPLETED),
            ("b", CasePhase.RUNNING),
            ("b", CasePhase.COMPLETED),
        ]
        assert {event.case_identifier for event in events} == {"fixture:empty"}
        assert [event.outcome for event in events if event.phase is CasePhase.COMPLETED] == list(
            report.outcomes
        )
        assert all(
            event.outcome is None for event in events if event.phase is not CasePhase.COMPLETED
        )

    def test_shrinking_is_announced_before_the_outcome_completes(self) -> None:
        events: list[CaseProgress] = []
        run_fake({"bad": drop_last_above_five}, [LARGE_GENERATED], on_progress=events.append)
        assert [event.phase for event in events] == [
            CasePhase.RUNNING,
            CasePhase.SHRINKING,
            CasePhase.COMPLETED,
        ]
        completed = events[-1].outcome
        assert completed is not None
        assert completed.shrunk is not None


class TestRealProcesses:
    """The engine against real subprocesses, with as few runs as possible."""

    def test_a_correct_and_a_wrong_implementation(
        self, python_sort_executable: Path, unsorted_output_executable: Path
    ) -> None:
        implementations = [
            Implementation.from_executable(python_sort_executable, name="correct"),
            Implementation.from_executable(unsorted_output_executable, name="unsorted"),
        ]
        report = run_tests(
            SortingProblem(),
            implementations,
            cases_of("fixture:single", "fixture:two_unsorted"),
        )
        assert [outcome.status for outcome in report.outcomes_for("correct")] == [
            CaseStatus.PASSED
        ] * 2
        assert [outcome.status for outcome in report.outcomes_for("unsorted")] == [
            CaseStatus.PASSED,
            CaseStatus.FAILED,
        ]
        failed = report.outcome("fixture:two_unsorted", "unsorted")
        assert "not sorted ascending" in failed.message
        assert failed.detail is not None
        assert failed.detail.actual_text == "[2, 1]"

    def test_shrinking_runs_the_real_implementation(self, unsorted_output_executable: Path) -> None:
        unsorted = Implementation.from_executable(unsorted_output_executable, name="unsorted")
        report = run_tests(
            SortingProblem(), [unsorted], cases_of("generated:uniform:size=4:seed=3")
        )
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert len(shrunk.case.input_data) == 2

    def test_a_crash_is_an_error_with_the_standard_error(self, crashing_executable: Path) -> None:
        crashing = Implementation.from_executable(crashing_executable, name="crashing")
        report = run_tests(SortingProblem(), [crashing], cases_of("fixture:single"))
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert "exited with code 3" in outcome.message
        assert "kaboom" in outcome.message

    def test_a_missing_command_is_an_error_not_an_exception(self) -> None:
        ghost = Implementation(name="ghost", command=("algorithm-playground-no-such-command",))
        report = run_tests(SortingProblem(), [ghost], cases_of("fixture:single"))
        assert report.outcomes[0].status is CaseStatus.ERROR

    @pytest.mark.usefixtures("scratch_root")
    def test_kept_temporary_files_are_named_in_error_messages(
        self, crashing_executable: Path
    ) -> None:
        crashing = Implementation.from_executable(crashing_executable, name="crashing")
        report = run_tests(
            SortingProblem(), [crashing], cases_of("fixture:single"), keep_temporary_files=True
        )
        assert "Temporary files were kept in " in report.outcomes[0].message

    @pytest.mark.usefixtures("scratch_root")
    def test_kept_temporary_files_are_named_in_failure_messages(
        self, unsorted_output_executable: Path
    ) -> None:
        unsorted = Implementation.from_executable(unsorted_output_executable, name="unsorted")
        report = run_tests(
            SortingProblem(),
            [unsorted],
            cases_of("fixture:reverse_sorted"),
            keep_temporary_files=True,
        )
        message = report.outcomes[0].message
        assert "not sorted ascending" in message
        assert message.splitlines()[-1].startswith("Temporary files were kept in ")

    def test_messages_do_not_mention_temporary_files_that_were_deleted(
        self, crashing_executable: Path
    ) -> None:
        crashing = Implementation.from_executable(crashing_executable, name="crashing")
        report = run_tests(SortingProblem(), [crashing], cases_of("fixture:single"))
        assert "Temporary files" not in report.outcomes[0].message


class TestHooksThatRaiseInTheRealRunner:
    def test_a_problem_that_cannot_write_an_input_gives_an_error_naming_the_hook(
        self, python_sort_executable: Path
    ) -> None:
        class CannotWrite(SortingProblem):
            def serialize_input(self, data: list[int], path: Path) -> None:
                raise RuntimeError("disk on fire")

        implementation = Implementation.from_executable(python_sort_executable, name="sorter")
        report = run_tests(CannotWrite(), [implementation], cases_of("fixture:single"))
        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert "serialize_input" in outcome.message
        assert "RuntimeError: disk on fire" in outcome.message
        assert outcome.shrunk is None


class TestTestReport:
    def _report(self) -> TestReport:
        case = Case(FixtureOrigin("case"), [])
        outcomes = (
            CaseOutcome(case, "a", CaseStatus.PASSED, ""),
            CaseOutcome(case, "b", CaseStatus.FAILED, "wrong"),
        )
        return TestReport("sorting", ("a", "b"), (case,), outcomes)

    def test_outcome_lookup(self) -> None:
        report = self._report()
        assert report.outcome("fixture:case", "b").message == "wrong"

    def test_lookups_do_not_scan_the_outcomes(self) -> None:
        class CountingTuple(tuple[CaseOutcome, ...]):
            iterations = 0

            def __iter__(self) -> Iterator[CaseOutcome]:
                CountingTuple.iterations += 1
                return super().__iter__()

        case = Case(FixtureOrigin("case"), [])
        outcomes = CountingTuple(
            CaseOutcome(case, name, CaseStatus.PASSED, "") for name in ("a", "b", "c")
        )
        CountingTuple.iterations = 0
        report = TestReport("sorting", ("a", "b", "c"), (case,), outcomes)
        for _ in range(100):
            assert report.outcome("fixture:case", "c").implementation_name == "c"
        assert CountingTuple.iterations <= 1

    def test_the_settings_of_a_run_are_recorded(self) -> None:
        report, _ = run_fake(
            {"a": sort_correctly},
            ["fixture:single"],
            timeout_seconds=12.5,
            shrink=False,
            maximum_shrunk_cases=4,
            maximum_shrink_runs=30,
            shrink_time_budget_seconds=7.0,
        )
        settings = report.settings
        assert (settings.timeout_seconds, settings.shrink, settings.maximum_shrunk_cases) == (
            12.5,
            False,
            4,
        )
        assert (settings.maximum_shrink_runs, settings.shrink_time_budget_seconds) == (30, 7.0)

    def test_outcome_lookup_of_unknown_pair_raises(self) -> None:
        with pytest.raises(KeyError):
            self._report().outcome("fixture:case", "c")

    def test_outcomes_for_one_implementation(self) -> None:
        outcomes = self._report().outcomes_for("a")
        assert [outcome.status for outcome in outcomes] == [CaseStatus.PASSED]

    def test_case_identifiers_follow_the_cases(self) -> None:
        assert self._report().case_identifiers == ("fixture:case",)

    def test_pytest_does_not_collect_the_report_class(self) -> None:
        assert TestReport.__test__ is False
