"""Tests for the test engine.

Engine logic runs in-process against fake runners. A few tests use real
subprocesses to cover the integration with the runner.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)

from algorithm_playground.core.cases import Case, FixtureOrigin, ShrunkOrigin, resolve_case
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.runner import RunnerError, TemporaryFilePolicy
from algorithm_playground.core.testing import (
    CaseOutcome,
    CasePhase,
    CaseProgress,
    CaseStatus,
    ShrinkOptions,
    ShrunkFailure,
    TestReport,
    TestRunOptions,
    run_tests,
)
from algorithm_playground.problems.sorting import SortingProblem

LARGE_GENERATED = "generated:uniform:size=12:seed=5"
SMALL_GENERATED = "generated:uniform:size=4:seed=6"
NO_SHRINKING = TestRunOptions(shrinking=None)


class ManualClock:
    """A clock that only moves when a test advances it."""

    def __init__(self) -> None:
        self._seconds = 0.0

    def __call__(self) -> float:
        return self._seconds

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self._seconds += seconds


class TickingClock:
    """A clock that moves forward by a fixed step every time it is read."""

    def __init__(self, step_seconds: float) -> None:
        self._step_seconds = step_seconds
        self._seconds = 0.0

    def __call__(self) -> float:
        self._seconds += self._step_seconds
        return self._seconds


class UnknownExpectedProblem(SortingProblem):
    """Sorting without an expected output, as for a problem with many valid answers."""

    def expected_output(self, input_data: list[int]) -> list[int] | None:  # ty: ignore[invalid-method-override]
        return None


class ExplodingHooksProblem(SortingProblem):
    """Sorting whose describe and shrink hooks raise."""

    def describe_input(self, input_data: list[int], *, limit: int) -> str:
        raise RuntimeError("cannot describe")

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        raise RuntimeError("shrink exploded")


class NoShrinkProblem(SortingProblem):
    """Sorting whose shrink hook offers no candidates."""

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        return iter(())


class RaisesLateProblem(SortingProblem):
    """Sorting whose shrink hook offers two candidates and then raises."""

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        if len(input_data) <= 6:
            raise RuntimeError("no more ideas")
        yield input_data[: len(input_data) // 2]
        yield input_data[:6]


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


class NeedsEightValuesProblem(SortingProblem):
    """Sorting where an input needs at least eight values, as a rule of the problem."""

    def check_input(self, input_data: list[int]) -> str | None:
        return None if len(input_data) >= 8 else "too short"


class RejectingEverythingProblem(SortingProblem):
    """A problem whose shrink hook offers endless candidates that are all invalid inputs."""

    def check_input(self, input_data: list[int]) -> str | None:
        return "invalid" if len(input_data) < 100 else None

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        for length in range(10**9):
            yield [length]


class ExplodingCheckProblem(SortingProblem):
    """Sorting whose input check raises."""

    def check_input(self, input_data: list[int]) -> str | None:
        raise RuntimeError("check exploded")


class RecordingDescriptionsProblem(SortingProblem):
    """Sorting that records the focus each describe_output call received."""

    def __init__(self) -> None:
        self.focuses: list[int | None] = []

    def describe_output(self, output: list[int], *, limit: int, focus: int | None = None) -> str:
        self.focuses.append(focus)
        return super().describe_output(output, limit=limit, focus=focus)


class UnwritableInputProblem(SortingProblem):
    """Sorting whose input hook raises."""

    def serialize_input(self, data: list[int], path: Path) -> None:
        raise RuntimeError("disk on fire")


class IterationCountingTuple(tuple[CaseOutcome, ...]):
    """A tuple of outcomes that counts how often it is iterated."""

    iterations: ClassVar[int] = 0

    def __iter__(self) -> Iterator[CaseOutcome]:
        IterationCountingTuple.iterations += 1
        return super().__iter__()


def resolve_cases(*identifiers: str) -> list[Case[Any]]:
    """Resolve case identifiers of the sorting problem into cases."""
    problem = SortingProblem()
    return [resolve_case(problem, identifier) for identifier in identifiers]


def run_with_fake_runners(
    behaviors: dict[str, Any],
    identifiers: list[str],
    *,
    options: TestRunOptions | None = None,
    on_progress: Callable[[CaseProgress], None] | None = None,
) -> tuple[TestReport, FakeRunners]:
    """Test fake implementations on cases and return the report with the runners it used."""
    runners = FakeRunners(behaviors)
    report = run_tests(
        SortingProblem(),
        build_named_implementations(*behaviors),
        resolve_cases(*identifiers),
        options=options,
        runner_factory=runners,
        on_progress=on_progress,
    )
    return report, runners


def time_out_above_three(values: list[int]) -> list[int]:
    """Fail with a timeout when there are more than three values, as a slow sorter does."""
    if len(values) > 3:
        raise RunnerError("timed out after 1.000s", category="timeout")
    return sorted(values)


def build_slow_drop_last(clock: ManualClock) -> Callable[[list[int]], list[int]]:
    """Build a behavior that drops the last value and takes 0.03 seconds of the clock per run."""

    def slow_drop_last(values: list[int]) -> list[int]:
        clock.advance(0.03)
        return drop_last_above_five(values)

    return slow_drop_last


class TestOutcomes:
    @pytest.fixture
    def mixed_report(self) -> TestReport:
        """The report of a correct and a wrong implementation on three cases."""
        report, _ = run_with_fake_runners(
            {"good": sort_correctly, "bad": drop_last_above_five},
            ["fixture:empty", SMALL_GENERATED, LARGE_GENERATED],
        )
        return report

    def test_correct_implementation_passes_every_case(self) -> None:
        """Test a correct implementation passes every case with no message and no detail."""
        report, _ = run_with_fake_runners({"a": sort_correctly}, ["fixture:empty", LARGE_GENERATED])

        assert report.has_passed
        assert report.failures() == ()
        assert all(outcome.status is CaseStatus.PASSED for outcome in report.outcomes)
        assert all(outcome.message == "" and outcome.detail is None for outcome in report.outcomes)

    def test_the_report_names_the_problem_the_implementations_and_the_cases(self) -> None:
        """Test the report records the problem, the implementation names and the case identifiers."""
        report, _ = run_with_fake_runners({"a": sort_correctly}, ["fixture:empty", LARGE_GENERATED])

        assert report.problem_name == "sorting"
        assert report.implementation_names == ("a",)
        assert report.case_identifiers == ("fixture:empty", LARGE_GENERATED)

    def test_a_wrong_implementation_does_not_make_the_report_pass(
        self, mixed_report: TestReport
    ) -> None:
        """Test a report with a failing outcome has not passed."""
        assert not mixed_report.has_passed

    def test_a_wrong_implementation_does_not_affect_the_correct_one(
        self, mixed_report: TestReport
    ) -> None:
        """Test the correct implementation passes every case next to a wrong one."""
        statuses = [outcome.status for outcome in mixed_report.outcomes_for("good")]

        assert statuses == [CaseStatus.PASSED] * 3

    def test_a_wrong_implementation_fails_only_the_cases_it_gets_wrong(
        self, mixed_report: TestReport
    ) -> None:
        """Test the wrong implementation fails only the case that has more than five values."""
        statuses = [outcome.status for outcome in mixed_report.outcomes_for("bad")]

        assert statuses == [CaseStatus.PASSED, CaseStatus.PASSED, CaseStatus.FAILED]

    def test_a_failed_outcome_carries_the_message_of_the_verifier(
        self, mixed_report: TestReport
    ) -> None:
        """Test a failed outcome holds the message of the verifier."""
        failed = mixed_report.outcome(LARGE_GENERATED, "bad")

        assert "Output length 11 does not match input length 12" in failed.message

    def test_outcomes_are_ordered_by_case_then_implementation(self) -> None:
        """Test outcomes list every implementation for one case before the next case."""
        report, _ = run_with_fake_runners(
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
        """Test the failures of a report are exactly the outcomes that did not pass."""
        report, _ = run_with_fake_runners(
            {"good": sort_correctly, "bad": drop_last_above_five},
            ["fixture:empty", LARGE_GENERATED],
        )

        failures = [
            (outcome.implementation_name, outcome.case_identifier) for outcome in report.failures()
        ]

        assert failures == [("bad", LARGE_GENERATED)]

    def test_a_runner_error_is_an_error_outcome_with_the_full_message(self) -> None:
        """Test a runner error gives an error outcome that holds the whole error message."""
        report, _ = run_with_fake_runners({"crash": crash}, ["fixture:single"])

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.ERROR
        assert "exited with code 3" in outcome.message
        assert "kaboom" in outcome.message

    def test_an_exception_in_verification_is_an_error_outcome(
        self, exploding_problem: SortingProblem
    ) -> None:
        """Test a verifier that raises gives an error outcome with the exception and the output."""
        report = run_tests(
            exploding_problem,
            build_named_implementations("a"),
            resolve_cases("fixture:single"),
            runner_factory=FakeRunners({"a": sort_correctly}),
        )

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.ERROR
        assert outcome.message == "Verification raised RuntimeError: verifier exploded"
        assert outcome.detail is not None
        assert outcome.detail.actual_text == "[42]"

    def test_the_factory_receives_the_problem_and_each_implementation(self) -> None:
        """Test the runner factory is called once per implementation with the problem."""
        received: list[tuple[str, str]] = []
        runners = FakeRunners({"a": sort_correctly})

        def factory(problem: Any, implementation: Implementation) -> Any:
            received.append((problem.name, implementation.name))
            return runners(problem, implementation)

        run_tests(
            SortingProblem(),
            build_named_implementations("a"),
            resolve_cases("fixture:empty"),
            runner_factory=factory,
        )

        assert received == [("sorting", "a")]

    def test_rejects_duplicate_case_identifiers(self) -> None:
        """Test two cases with the same identifier raise a ValueError."""
        with pytest.raises(ValueError, match="unique"):
            run_with_fake_runners({"a": sort_correctly}, ["fixture:empty", "fixture:empty"])

    def test_rejects_no_cases(self) -> None:
        """Test an empty list of cases raises a ValueError."""
        with pytest.raises(ValueError, match="At least one case"):
            run_with_fake_runners({"a": sort_correctly}, [])

    def test_rejects_duplicate_implementation_names(self) -> None:
        """Test two implementations with the same name raise a ValueError."""
        with pytest.raises(ValueError, match="Duplicate implementation name"):
            run_tests(
                SortingProblem(),
                build_named_implementations("a", "a"),
                resolve_cases("fixture:empty"),
            )

    def test_rejects_an_empty_implementation_list(self) -> None:
        """Test an empty list of implementations raises a ValueError."""
        with pytest.raises(ValueError, match="At least one implementation"):
            run_tests(SortingProblem(), [], resolve_cases("fixture:empty"))


class TestFailureDetails:
    def test_a_failure_carries_the_input_the_expected_and_the_actual_output(self) -> None:
        """Test a failure holds the description of the input, the expected and the actual output."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], options=NO_SHRINKING
        )
        problem = SortingProblem()
        data = resolve_case(problem, LARGE_GENERATED).input_data

        detail = report.outcomes[0].detail

        assert detail is not None
        assert detail.input_text == problem.describe_input(data, limit=300)
        assert detail.expected_text == problem.describe_output(sorted(data), limit=300)
        assert detail.actual_text == problem.describe_output(sorted(data)[:-1], limit=300)

    def test_descriptions_are_shortened_to_the_limit(self) -> None:
        """Test a long input description is cut to the description limit."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=None, description_limit=40),
        )

        detail = report.outcomes[0].detail

        assert detail is not None
        assert "(12 values)" in detail.input_text
        assert len(detail.input_text) <= 40

    def test_a_runner_error_has_no_actual_output(self) -> None:
        """Test a run that crashed has the input and the expected output but no actual output."""
        report, _ = run_with_fake_runners({"crash": crash}, ["fixture:two_unsorted"])

        detail = report.outcomes[0].detail

        assert detail is not None
        assert detail.input_text == "[2, 1]"
        assert detail.expected_text == "[1, 2]"
        assert detail.actual_text is None

    def test_a_problem_without_expected_output_reports_none(self) -> None:
        """Test a problem that cannot name the expected output leaves it out of the detail."""
        report = run_tests(
            UnknownExpectedProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
            options=NO_SHRINKING,
        )

        detail = report.outcomes[0].detail

        assert detail is not None
        assert detail.expected_text is None
        assert detail.actual_text is not None

    def test_a_describe_hook_that_raises_does_not_break_the_report(self) -> None:
        """Test a describe hook that raises is replaced by a description of the error."""
        report = run_tests(
            ExplodingHooksProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        detail = report.outcomes[0].detail

        assert detail is not None
        assert detail.input_text == "(could not describe: RuntimeError: cannot describe)"
        assert detail.actual_text is not None


class TestShrinking:
    @pytest.fixture
    def shrunk_failure(self) -> ShrunkFailure:
        """The shrunk failure of the wrong implementation on the large generated case."""
        report, _ = run_with_fake_runners({"bad": drop_last_above_five}, [LARGE_GENERATED])
        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        return shrunk

    def test_a_failing_generated_case_is_shrunk_to_the_smallest_failing_input(
        self, shrunk_failure: ShrunkFailure
    ) -> None:
        """Test a failing generated case is shrunk to the smallest input that still fails."""
        assert shrunk_failure.case.input_data == [0] * 6
        assert shrunk_failure.case.identifier == f"shrunk:{LARGE_GENERATED}"
        assert shrunk_failure.case.origin == ShrunkOrigin(LARGE_GENERATED)

    def test_a_shrunk_failure_describes_its_own_failure(
        self, shrunk_failure: ShrunkFailure
    ) -> None:
        """Test the shrunk failure holds the message and the detail of the shrunk input."""
        assert shrunk_failure.message == "Output length 5 does not match input length 6"
        assert shrunk_failure.detail.input_text == "[0, 0, 0, 0, 0, 0]"
        assert shrunk_failure.detail.expected_text == "[0, 0, 0, 0, 0, 0]"
        assert shrunk_failure.detail.actual_text == "[0, 0, 0, 0, 0]"

    def test_shrinking_only_runs_the_implementation_that_failed(self) -> None:
        """Test only the failing implementation runs again while shrinking."""
        _, runners = run_with_fake_runners(
            {"good": sort_correctly, "bad": drop_last_above_five}, [LARGE_GENERATED]
        )

        assert len(runners.collect_inputs_of("good")) == 1
        assert len(runners.collect_inputs_of("bad")) > 1

    def test_fixtures_are_not_shrunk(self) -> None:
        """Test a failing fixture is neither shrunk nor run again."""
        report, runners = run_with_fake_runners(
            {"bad": drop_last_above_five}, ["fixture:already_sorted"]
        )

        assert report.outcomes[0].status is CaseStatus.FAILED
        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_no_shrink_turns_it_off(self) -> None:
        """Test a failing generated case is not shrunk when shrinking is off."""
        report, runners = run_with_fake_runners(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], options=NO_SHRINKING
        )

        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_a_passing_case_is_not_shrunk(self) -> None:
        """Test a passing generated case is run once."""
        _, runners = run_with_fake_runners({"good": sort_correctly}, [LARGE_GENERATED])

        assert len(runners.calls) == 1

    def test_an_error_is_shrunk_too(self) -> None:
        """Test a generated case that crashes the implementation is shrunk like a failure."""

        def crash_above_three(values: list[int]) -> list[int]:
            if len(values) > 3:
                return crash(values)
            return sorted(values)

        report, _ = run_with_fake_runners({"bad": crash_above_three}, [LARGE_GENERATED])

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.ERROR
        assert outcome.shrunk is not None
        assert outcome.shrunk.case.input_data == [0] * 4

    def test_a_problem_without_a_shrink_hook_reports_no_shrunk_input(self) -> None:
        """Test a problem whose shrink hook offers nothing leaves the failure unshrunk."""
        report = run_tests(
            NoShrinkProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        assert report.outcomes[0].status is CaseStatus.FAILED
        assert report.outcomes[0].shrunk is None

    def test_the_run_cap_limits_one_shrink(self) -> None:
        """Test one shrink runs the implementation at most the maximum number of times."""
        _, runners = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=3)),
        )

        assert len(runners.calls) == 1 + 3

    def test_the_cap_still_keeps_the_best_input_found_so_far(self) -> None:
        """Test a shrink stopped by the run cap keeps the smallest failing input it found."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=3)),
        )

        shrunk = report.outcomes[0].shrunk

        assert shrunk is not None
        assert 6 <= len(shrunk.case.input_data) < 12

    def test_a_spent_time_budget_means_no_shrinking(self) -> None:
        """Test a time budget of zero seconds leaves the failure unshrunk and unrun."""
        report, runners = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=ShrinkOptions(time_budget_seconds=0.0)),
        )

        assert report.outcomes[0].shrunk is None
        assert len(runners.calls) == 1

    def test_only_a_limited_number_of_cases_is_shrunk_per_implementation(self) -> None:
        """Test an implementation has at most the maximum number of cases shrunk."""
        identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9, 10)]

        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            identifiers,
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_shrunk_cases=2)),
        )

        assert [outcome.shrunk is not None for outcome in report.outcomes] == [True, True, False]

    def test_a_candidate_that_cannot_be_run_is_skipped(self) -> None:
        """Test a candidate that the implementation cannot run is skipped and shrinking goes on."""

        def refuse_huge_values(values: list[int]) -> list[int]:
            if any(value > 2**31 for value in values):
                raise ValueError("value out of range")
            return drop_last_above_five(values)

        report = run_tests(
            CountingShrinkProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": refuse_huge_values}),
        )

        shrunk = report.outcomes[0].shrunk

        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 6

    def test_a_shrink_hook_that_raises_is_reported_in_a_note(self) -> None:
        """Test a shrink hook that raises leaves the failure unshrunk and explains why in a note."""
        report = run_tests(
            ExplodingHooksProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.FAILED
        assert outcome.shrunk is None
        assert (
            outcome.shrink_note == "the problem's shrink hook raised RuntimeError: shrink exploded"
        )

    @pytest.fixture
    def late_raising_outcome(self) -> CaseOutcome:
        """The outcome of shrinking with a hook that raises after offering two candidates."""
        report = run_tests(
            RaisesLateProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )
        return report.outcomes[0]

    def test_a_shrink_hook_that_raises_part_way_keeps_what_was_found(
        self, late_raising_outcome: CaseOutcome
    ) -> None:
        """Test a shrink hook that raises part way leaves the smallest input found so far."""
        assert late_raising_outcome.shrunk is not None
        assert len(late_raising_outcome.shrunk.case.input_data) == 6

    def test_a_shrink_hook_that_raises_part_way_leaves_a_note_with_the_reason(
        self, late_raising_outcome: CaseOutcome
    ) -> None:
        """Test the note of a shrink that ended in an exception names the exception."""
        assert late_raising_outcome.shrink_note is not None
        assert "no more ideas" in late_raising_outcome.shrink_note

    def test_a_clean_shrink_has_no_note(self) -> None:
        """Test a shrink that finishes without hitting a limit leaves no note."""
        report, _ = run_with_fake_runners({"bad": drop_last_above_five}, [LARGE_GENERATED])

        assert report.outcomes[0].shrink_note is None

    def test_a_hook_that_only_yields_copies_of_the_input_cannot_keep_a_shrink_going(self) -> None:
        """Test the candidate cap ends a shrink whose hook only yields copies of the input."""
        runners = FakeRunners({"bad": drop_last_above_five})

        report = run_tests(
            RepeatingShrinkProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=50, clock=ManualClock())),
            runner_factory=runners,
        )

        assert report.outcomes[0].shrunk is None
        assert report.outcomes[0].shrink_note is not None
        assert "after 50 candidates" in report.outcomes[0].shrink_note
        assert len(runners.calls) == 1

    def test_the_time_budget_stops_a_hook_that_never_stops_yielding_copies(self) -> None:
        """Test the time budget ends a shrink whose hook yields copies of the input forever."""
        report = run_tests(
            RepeatingShrinkProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            options=TestRunOptions(
                shrinking=ShrinkOptions(
                    maximum_runs=10**12, time_budget_seconds=0.2, clock=TickingClock(0.05)
                )
            ),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        note = report.outcomes[0].shrink_note

        assert note is not None
        assert note.startswith("shrinking stopped when its time budget (0.2 seconds per ")

    def test_the_deadline_can_pass_part_way_and_the_best_input_so_far_is_kept(self) -> None:
        """Test a time budget that runs out part way keeps the smallest failing input found."""
        clock = ManualClock()

        report, runners = run_with_fake_runners(
            {"bad": build_slow_drop_last(clock)},
            [LARGE_GENERATED],
            options=TestRunOptions(
                shrinking=ShrinkOptions(maximum_runs=10**6, time_budget_seconds=0.25, clock=clock)
            ),
        )

        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert len(shrunk.case.input_data) < 12
        assert len(runners.calls) < 40

    def test_every_candidate_runs_with_a_timeout_the_budget_still_allows(self) -> None:
        """Test each candidate gets a timeout no longer than the time left in the budget."""
        _, runners = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(
                timeout_seconds=100.0, shrinking=ShrinkOptions(time_budget_seconds=5.0)
            ),
        )

        original, *candidates = runners.timeouts

        assert original is None
        assert candidates
        assert all(timeout is not None and timeout <= 5.0 for timeout in candidates)

    def test_the_timeout_of_an_implementation_bounds_a_candidate_too(self) -> None:
        """Test the timeout of an implementation also limits each candidate."""
        implementation = Implementation(name="bad", command=("fake",), timeout_seconds=2.0)
        runners = FakeRunners({"bad": drop_last_above_five})

        run_tests(
            SortingProblem(),
            [implementation],
            resolve_cases(LARGE_GENERATED),
            options=TestRunOptions(timeout_seconds=100.0),
            runner_factory=runners,
        )

        assert all(timeout is not None and timeout <= 2.0 for timeout in runners.timeouts[1:])

    def test_a_candidate_that_times_out_under_a_shortened_limit_proves_nothing(self) -> None:
        """Test a candidate that times out under a shortened limit is not taken as a failure."""
        report, _ = run_with_fake_runners(
            {"slow": time_out_above_three},
            [LARGE_GENERATED],
            options=TestRunOptions(
                timeout_seconds=1000.0, shrinking=ShrinkOptions(time_budget_seconds=30.0)
            ),
        )

        assert report.outcomes[0].status is CaseStatus.ERROR
        assert report.outcomes[0].shrunk is None

    def test_a_failure_does_not_drift_into_an_unrelated_error_while_shrinking(self) -> None:
        """Test a wrong output is not shrunk to an input on which the implementation crashes."""

        def wrong_when_large_crashing_when_tiny(values: list[int]) -> list[int]:
            if len(values) <= 2:
                raise RunnerError("exited with code 7", category="exit code 7")
            return drop_last_above_five(values)

        report, _ = run_with_fake_runners(
            {"bad": wrong_when_large_crashing_when_tiny}, [LARGE_GENERATED]
        )

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.FAILED
        assert outcome.shrunk is not None
        assert outcome.shrunk.case.input_data == [0] * 6
        assert "does not match input length" in outcome.shrunk.message

    def test_an_error_does_not_drift_into_a_failure_while_shrinking(self) -> None:
        """Test a crash is not shrunk to an input on which the output is wrong."""

        def crash_when_large_wrong_when_medium(values: list[int]) -> list[int]:
            if len(values) > 8:
                raise RunnerError("exited with code 7", category="exit code 7")
            return drop_last_above_five(values)

        report, _ = run_with_fake_runners(
            {"bad": crash_when_large_wrong_when_medium}, [LARGE_GENERATED]
        )

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.ERROR
        assert outcome.shrunk is not None
        assert outcome.shrunk.case.input_data == [0] * 9

    def test_an_error_keeps_its_kind_while_shrinking(self) -> None:
        """Test a crash with one exit code is not shrunk to an input with another exit code."""

        def exit_code_depends_on_size(values: list[int]) -> list[int]:
            if len(values) > 8:
                raise RunnerError("exited with code 7", category="exit code 7")
            if len(values) > 3:
                raise RunnerError("exited with code 9", category="exit code 9")
            return sorted(values)

        report, _ = run_with_fake_runners({"bad": exit_code_depends_on_size}, [LARGE_GENERATED])

        shrunk = report.outcomes[0].shrunk

        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 9
        assert "code 7" in shrunk.message


class TestShrinkNotes:
    def test_the_candidate_limit_is_named_when_it_ends_a_shrink(self) -> None:
        """Test the note names the candidate limit when it ended the shrink."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=3)),
        )

        assert report.outcomes[0].shrink_note == (
            "shrinking stopped after 3 candidates, its limit; a smaller failing input may exist"
        )

    def test_the_time_budget_is_named_when_it_ends_a_shrink(self) -> None:
        """Test the note names the time budget when it ended the shrink."""
        clock = ManualClock()

        report, _ = run_with_fake_runners(
            {"bad": build_slow_drop_last(clock)},
            [LARGE_GENERATED],
            options=TestRunOptions(
                shrinking=ShrinkOptions(maximum_runs=10**6, time_budget_seconds=0.25, clock=clock)
            ),
        )

        note = report.outcomes[0].shrink_note

        assert note is not None
        assert note.startswith("shrinking stopped when its time budget (0.25 seconds per ")
        assert "a smaller failing input may exist" in note

    def test_the_time_budget_is_measured_with_the_clock_of_the_options(self) -> None:
        """Test the shrink budget is measured with the clock given in the shrink options."""
        clock = ManualClock()

        def take_one_second_then_drop_last(values: list[int]) -> list[int]:
            clock.advance(1.0)
            return drop_last_above_five(values)

        report, runners = run_with_fake_runners(
            {"bad": take_one_second_then_drop_last},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=ShrinkOptions(time_budget_seconds=3.5, clock=clock)),
        )

        note = report.outcomes[0].shrink_note

        assert len(runners.calls) == 1 + 4
        assert note is not None
        assert note.startswith("shrinking stopped when its time budget (3.5 seconds per ")

    def test_a_case_left_unshrunk_by_the_case_limit_says_so(self) -> None:
        """Test a case skipped because of the shrunk-case limit has a note saying so."""
        identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9, 10)]

        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            identifiers,
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_shrunk_cases=2)),
        )

        assert [outcome.shrink_note for outcome in report.outcomes] == [
            None,
            None,
            "not shrunk: the limit of 2 shrunk cases per implementation was reached",
        ]

    def test_a_case_left_unshrunk_by_a_spent_time_budget_says_so(self) -> None:
        """Test a case skipped because the time budget was used up has a note saying so."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=ShrinkOptions(time_budget_seconds=0.0)),
        )

        assert report.outcomes[0].shrink_note == (
            "not shrunk: the time budget for shrinking (0 seconds per implementation) was used up"
        )

    def test_a_fixture_and_a_passing_case_have_no_note(self) -> None:
        """Test a failing fixture and a passing generated case leave no shrink note."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five}, ["fixture:duplicates", SMALL_GENERATED]
        )

        assert [outcome.shrink_note for outcome in report.outcomes] == [None, None]

    def test_no_shrink_leaves_no_note(self) -> None:
        """Test a failing case leaves no shrink note when shrinking is off."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], options=NO_SHRINKING
        )

        assert report.outcomes[0].shrink_note is None


class TestFailuresThatAreNotShrunk:
    def test_a_verification_that_raises_is_not_shrunk(
        self, exploding_problem: SortingProblem
    ) -> None:
        """Test a failure caused by the verifier is not shrunk and the note says why."""
        runners = FakeRunners({"good": sort_correctly})

        report = run_tests(
            exploding_problem,
            build_named_implementations("good"),
            resolve_cases(LARGE_GENERATED),
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
        """Test a failure to serialize the input is not shrunk and the note says why."""

        def cannot_serialize(values: list[int]) -> list[int]:
            raise RunnerError("serialize_input raised", category="serialization")

        report, runners = run_with_fake_runners({"bad": cannot_serialize}, [LARGE_GENERATED])

        outcome = report.outcomes[0]

        assert outcome.shrunk is None
        assert outcome.shrink_note is not None
        assert outcome.shrink_note.startswith("not shrunk: the serialization failure comes from")
        assert len(runners.calls) == 1

    def test_a_failure_of_the_implementation_is_still_shrunk(self) -> None:
        """Test a wrong output of the implementation is shrunk."""
        report, _ = run_with_fake_runners({"bad": drop_last_above_five}, [LARGE_GENERATED])

        assert report.outcomes[0].shrunk is not None

    def test_a_timeout_longer_than_the_shrink_budget_is_not_shrunk(self) -> None:
        """Test a timeout longer than the shrink budget is not shrunk and the note says why."""
        report, runners = run_with_fake_runners(
            {"slow": time_out_above_three},
            [LARGE_GENERATED],
            options=TestRunOptions(
                timeout_seconds=60.0, shrinking=ShrinkOptions(time_budget_seconds=30.0)
            ),
        )

        outcome = report.outcomes[0]

        assert outcome.status is CaseStatus.ERROR
        assert outcome.shrunk is None
        assert outcome.shrink_note == "not shrunk: the timeout is longer than the shrink budget"
        assert len(runners.calls) == 1

    def test_a_timeout_the_shrink_budget_covers_is_shrunk(self) -> None:
        """Test a timeout that the shrink budget covers is shrunk without a note."""
        report, _ = run_with_fake_runners(
            {"slow": time_out_above_three},
            [LARGE_GENERATED],
            options=TestRunOptions(
                timeout_seconds=1.0, shrinking=ShrinkOptions(time_budget_seconds=30.0)
            ),
        )

        shrunk = report.outcomes[0].shrunk

        assert shrunk is not None
        assert shrunk.case.input_data == [0] * 4
        assert report.outcomes[0].shrink_note is None

    def test_a_spent_budget_is_named_before_a_timeout_that_is_longer_than_it(self) -> None:
        """Test the note for a used-up budget takes precedence over the note about the timeout."""
        identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9)]

        report, _ = run_with_fake_runners(
            {"slow": time_out_above_three},
            identifiers,
            options=TestRunOptions(
                timeout_seconds=1.0, shrinking=ShrinkOptions(time_budget_seconds=0.0)
            ),
        )

        assert [outcome.shrink_note for outcome in report.outcomes] == [
            "not shrunk: the time budget for shrinking (0 seconds per implementation) was used up"
        ] * 2


class TestShrinkingAndTheValidityOfInputs:
    def test_candidates_that_are_not_valid_inputs_are_skipped_and_never_run(self) -> None:
        """Test a candidate that the problem rejects as invalid is never run."""
        runners = FakeRunners({"bad": drop_last_above_five})

        run_tests(
            ShortInputsInvalidProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=runners,
        )

        assert all(len(values) >= 3 for values in runners.collect_inputs_of("bad"))

    def test_a_rule_that_rejects_only_tiny_inputs_does_not_change_the_shrunk_input(self) -> None:
        """Test the shrunk input is still six values when the rule only rejects fewer than three."""
        report = run_tests(
            ShortInputsInvalidProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        shrunk = report.outcomes[0].shrunk

        assert shrunk is not None
        assert len(shrunk.case.input_data) == 6

    def test_a_rule_can_force_a_larger_shrunk_input(self) -> None:
        """Test a rule that rejects short inputs makes the shrunk input longer."""
        report = run_tests(
            NeedsEightValuesProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        shrunk = report.outcomes[0].shrunk

        assert shrunk is not None
        assert len(shrunk.case.input_data) == 8

    def test_rejected_candidates_count_against_the_budget(self) -> None:
        """Test candidates rejected as invalid use up the candidate budget."""
        runners = FakeRunners({"bad": drop_last_above_five})

        report = run_tests(
            RejectingEverythingProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=25, clock=ManualClock())),
            runner_factory=runners,
        )

        assert len(runners.calls) == 1
        assert report.outcomes[0].shrunk is None
        assert report.outcomes[0].shrink_note is not None
        assert "after 25 candidates" in report.outcomes[0].shrink_note

    def test_a_check_that_raises_is_reported_in_a_note_naming_the_hook(self) -> None:
        """Test an input check that raises leaves the failure unshrunk with a note naming the hook."""
        report = run_tests(
            ExplodingCheckProblem(),
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        assert report.outcomes[0].shrunk is None
        assert report.outcomes[0].shrink_note == (
            "the problem's check_input hook raised RuntimeError: check exploded"
        )


class TestFocusAndCategory:
    def test_the_position_the_verifier_names_is_passed_to_the_describe_hook(self) -> None:
        """Test the describe hook receives the position of the first difference as its focus."""
        problem = RecordingDescriptionsProblem()

        run_tests(
            problem,
            build_named_implementations("bad"),
            resolve_cases(LARGE_GENERATED),
            options=NO_SHRINKING,
            runner_factory=FakeRunners({"bad": drop_last_above_five}),
        )

        # The expected output and the actual output of the one failure, both at the
        # first difference (the missing last element).
        assert problem.focuses == [11, 11]

    def test_a_failure_without_a_position_describes_the_outputs_without_one(self) -> None:
        """Test the describe hook receives no focus when the failure names no position."""
        problem = RecordingDescriptionsProblem()

        run_tests(
            problem,
            build_named_implementations("crash"),
            resolve_cases("fixture:two_unsorted"),
            runner_factory=FakeRunners({"crash": crash}),
        )

        assert problem.focuses == [None]

    def test_the_window_around_the_difference_is_in_the_description(self) -> None:
        """Test a short description shows the window around the first difference."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five},
            [LARGE_GENERATED],
            options=TestRunOptions(shrinking=None, description_limit=45),
        )

        detail = report.outcomes[0].detail

        assert detail is not None
        assert detail.expected_text is not None
        assert detail.actual_text is not None
        assert (
            detail.expected_text.startswith("[..., ") and "index 11 shown" in detail.expected_text
        )
        assert detail.actual_text.startswith("[..., ") and "index 10 shown" in detail.actual_text

    @pytest.mark.parametrize(
        ("name", "status", "category"),
        [
            ("bad", CaseStatus.FAILED, "wrong length"),
            ("crashing", CaseStatus.ERROR, "error"),
        ],
        ids=["wrong-output", "runner-error"],
    )
    def test_a_failure_records_its_category(
        self, name: str, status: CaseStatus, category: str
    ) -> None:
        """Test a failing outcome records its status and the category of the failure."""
        report, _ = run_with_fake_runners(
            {"bad": drop_last_above_five, "crashing": crash}, ["fixture:duplicates"]
        )

        outcome = report.outcome("fixture:duplicates", name)

        assert outcome.category == category
        assert outcome.status is status

    def test_a_passing_outcome_has_no_category(self) -> None:
        """Test an outcome that passed has an empty category."""
        report, _ = run_with_fake_runners({"a": sort_correctly}, ["fixture:empty"])

        assert report.outcomes[0].category == ""

    def test_shrinking_keeps_the_category_the_verifier_named(self) -> None:
        """Test a shrink stops at inputs that fail with the same category as the original."""

        def short_when_long_else_unsorted(values: list[int]) -> list[int]:
            return values[:-1] if len(values) > 5 else sorted(values, reverse=True)

        report, _ = run_with_fake_runners(
            {"mixed": short_when_long_else_unsorted}, [LARGE_GENERATED]
        )

        outcome = report.outcomes[0]

        assert outcome.category == "wrong length"
        # Inputs of five values or fewer fail too, as "not sorted": not the same way.
        assert outcome.shrunk is not None
        assert len(outcome.shrunk.case.input_data) == 6


class TestProgress:
    def test_events_follow_each_run_and_end_with_the_completed_outcome(self) -> None:
        """Test each run reports that it is running and then that it completed with its outcome."""
        events: list[CaseProgress] = []

        report, _ = run_with_fake_runners(
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
        """Test a failing generated case reports a shrinking phase between running and completion."""
        events: list[CaseProgress] = []

        run_with_fake_runners(
            {"bad": drop_last_above_five}, [LARGE_GENERATED], on_progress=events.append
        )

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

    @pytest.fixture(scope="class")
    def correct_and_unsorted_report(
        self, python_sort_executable: Path, unsorted_output_executable: Path
    ) -> TestReport:
        """The report of a correct and an unsorted implementation run as real processes."""
        implementations = [
            Implementation.from_executable(python_sort_executable, name="correct"),
            Implementation.from_executable(unsorted_output_executable, name="unsorted"),
        ]
        return run_tests(
            SortingProblem(),
            implementations,
            resolve_cases("fixture:single", "fixture:two_unsorted"),
        )

    def test_a_correct_implementation_passes(self, correct_and_unsorted_report: TestReport) -> None:
        """Test a real correct implementation passes every case."""
        statuses = [
            outcome.status for outcome in correct_and_unsorted_report.outcomes_for("correct")
        ]

        assert statuses == [CaseStatus.PASSED] * 2

    def test_a_wrong_implementation_fails_only_the_unsorted_case(
        self, correct_and_unsorted_report: TestReport
    ) -> None:
        """Test a real implementation that copies its input fails only the unsorted input."""
        statuses = [
            outcome.status for outcome in correct_and_unsorted_report.outcomes_for("unsorted")
        ]

        assert statuses == [CaseStatus.PASSED, CaseStatus.FAILED]

    def test_a_wrong_implementation_has_a_message_and_the_actual_output(
        self, correct_and_unsorted_report: TestReport
    ) -> None:
        """Test the failure of a real implementation holds the message and the output it wrote."""
        failed = correct_and_unsorted_report.outcome("fixture:two_unsorted", "unsorted")

        assert "not sorted ascending" in failed.message
        assert failed.detail is not None
        assert failed.detail.actual_text == "[2, 1]"

    def test_shrinking_runs_the_real_implementation(self, unsorted_output_executable: Path) -> None:
        """Test a failing generated case is shrunk by running the real implementation."""
        unsorted = Implementation.from_executable(unsorted_output_executable, name="unsorted")

        report = run_tests(
            SortingProblem(), [unsorted], resolve_cases("generated:uniform:size=4:seed=3")
        )

        shrunk = report.outcomes[0].shrunk
        assert shrunk is not None
        assert len(shrunk.case.input_data) == 2

    def test_a_crash_is_an_error_with_the_standard_error(self, crashing_executable: Path) -> None:
        """Test an implementation that crashes gives an error outcome holding its standard error."""
        crashing = Implementation.from_executable(crashing_executable, name="crashing")

        report = run_tests(SortingProblem(), [crashing], resolve_cases("fixture:single"))

        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert "exited with code 3" in outcome.message
        assert "kaboom" in outcome.message

    def test_a_missing_command_is_an_error_not_an_exception(self) -> None:
        """Test a command that does not exist gives an error outcome instead of raising."""
        ghost = Implementation(name="ghost", command=("algorithm-playground-no-such-command",))

        report = run_tests(SortingProblem(), [ghost], resolve_cases("fixture:single"))

        assert report.outcomes[0].status is CaseStatus.ERROR

    @pytest.mark.usefixtures("scratch_root")
    def test_kept_temporary_files_are_named_in_error_messages(
        self, crashing_executable: Path
    ) -> None:
        """Test the message of an error names the directory of the kept temporary files."""
        crashing = Implementation.from_executable(crashing_executable, name="crashing")

        report = run_tests(
            SortingProblem(),
            [crashing],
            resolve_cases("fixture:single"),
            options=TestRunOptions(temporary_files=TemporaryFilePolicy.KEEP),
        )

        assert "Temporary files were kept in " in report.outcomes[0].message

    @pytest.mark.usefixtures("scratch_root")
    def test_kept_temporary_files_are_named_in_failure_messages(
        self, unsorted_output_executable: Path
    ) -> None:
        """Test the message of a failure ends with the directory of the kept temporary files."""
        unsorted = Implementation.from_executable(unsorted_output_executable, name="unsorted")

        report = run_tests(
            SortingProblem(),
            [unsorted],
            resolve_cases("fixture:reverse_sorted"),
            options=TestRunOptions(temporary_files=TemporaryFilePolicy.KEEP),
        )

        message = report.outcomes[0].message
        assert "not sorted ascending" in message
        assert message.splitlines()[-1].startswith("Temporary files were kept in ")

    def test_messages_do_not_mention_temporary_files_that_were_deleted(
        self, crashing_executable: Path
    ) -> None:
        """Test the message of an error mentions no temporary files when they were deleted."""
        crashing = Implementation.from_executable(crashing_executable, name="crashing")

        report = run_tests(SortingProblem(), [crashing], resolve_cases("fixture:single"))

        assert "Temporary files" not in report.outcomes[0].message


class TestHooksThatRaiseInTheRealRunner:
    def test_a_problem_that_cannot_write_an_input_gives_an_error_naming_the_hook(
        self, python_sort_executable: Path
    ) -> None:
        """Test an input hook that raises gives an error outcome naming the hook and the cause."""
        implementation = Implementation.from_executable(python_sort_executable, name="sorter")

        report = run_tests(
            UnwritableInputProblem(), [implementation], resolve_cases("fixture:single")
        )

        outcome = report.outcomes[0]
        assert outcome.status is CaseStatus.ERROR
        assert "serialize_input" in outcome.message
        assert "RuntimeError: disk on fire" in outcome.message
        assert outcome.shrunk is None


class TestTestReport:
    @pytest.fixture
    def sample_report(self) -> TestReport:
        """A report of one passing and one failing implementation on a single fixture case."""
        case = Case(FixtureOrigin("case"), [])
        outcomes = (
            CaseOutcome(case, "a", CaseStatus.PASSED, ""),
            CaseOutcome(case, "b", CaseStatus.FAILED, "wrong"),
        )
        return TestReport("sorting", ("a", "b"), (case,), outcomes)

    def test_outcome_lookup(self, sample_report: TestReport) -> None:
        """Test an outcome is found by case identifier and implementation name."""
        outcome = sample_report.outcome("fixture:case", "b")

        assert outcome.message == "wrong"

    def test_lookups_do_not_scan_the_outcomes(self) -> None:
        """Test looking up outcomes repeatedly iterates over the outcomes at most once."""
        case = Case(FixtureOrigin("case"), [])
        outcomes = IterationCountingTuple(
            CaseOutcome(case, name, CaseStatus.PASSED, "") for name in ("a", "b", "c")
        )
        IterationCountingTuple.iterations = 0
        report = TestReport("sorting", ("a", "b", "c"), (case,), outcomes)

        for _ in range(100):
            assert report.outcome("fixture:case", "c").implementation_name == "c"

        assert IterationCountingTuple.iterations <= 1

    def test_the_settings_of_a_run_are_recorded(self) -> None:
        """Test the report records the timeout and the shrink limits of the run."""
        report, _ = run_with_fake_runners(
            {"a": sort_correctly},
            ["fixture:single"],
            options=TestRunOptions(
                timeout_seconds=12.5,
                shrinking=ShrinkOptions(
                    maximum_shrunk_cases=4, maximum_runs=30, time_budget_seconds=7.0
                ),
            ),
        )

        settings = report.settings

        assert (settings.timeout_seconds, settings.shrink, settings.maximum_shrunk_cases) == (
            12.5,
            True,
            4,
        )
        assert (settings.maximum_shrink_runs, settings.shrink_time_budget_seconds) == (30, 7.0)

    def test_a_run_without_shrinking_records_that_shrinking_was_off(self) -> None:
        """Test the report records that shrinking was off along with the timeout."""
        report, _ = run_with_fake_runners(
            {"a": sort_correctly},
            ["fixture:single"],
            options=TestRunOptions(timeout_seconds=12.5, shrinking=None),
        )

        assert (report.settings.timeout_seconds, report.settings.shrink) == (12.5, False)

    def test_outcome_lookup_of_unknown_pair_raises(self, sample_report: TestReport) -> None:
        """Test looking up a pair without an outcome raises a KeyError naming the pair."""
        with pytest.raises(
            KeyError, match=r"No outcome for case 'fixture:case' and implementation 'c'"
        ):
            sample_report.outcome("fixture:case", "c")

    def test_outcomes_for_one_implementation(self, sample_report: TestReport) -> None:
        """Test the outcomes of one implementation are selected by name."""
        outcomes = sample_report.outcomes_for("a")

        assert [outcome.status for outcome in outcomes] == [CaseStatus.PASSED]

    def test_case_identifiers_follow_the_cases(self, sample_report: TestReport) -> None:
        """Test the case identifiers of a report are those of its cases."""
        assert sample_report.case_identifiers == ("fixture:case",)

    def test_pytest_does_not_collect_the_report_class(self) -> None:
        """Test the report class is marked so that pytest does not collect it as a test class."""
        assert TestReport.__test__ is False
