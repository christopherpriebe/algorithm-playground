"""Tests for how the test engine shrinks a failing input."""

import random
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    Case,
    CaseOutcome,
    CaseProgress,
    CaseStatus,
    Implementation,
    InputGenerator,
    RunnerError,
    ShrinkOptions,
    ShrunkFailure,
    ShrunkOrigin,
    TestReport,
    TestRunOptions,
    resolve_case,
    run_tests,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)
from helpers.inputs import UnequatableValues

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


class ExplodingHooksProblem(SortingProblem):
    """Sorting whose describe and shrink hooks raise."""

    @override
    def describe_input(self, input_data: list[int], *, limit: int) -> str:
        message = "cannot describe"
        raise RuntimeError(message)

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        message = "shrink exploded"
        raise RuntimeError(message)


class NoShrinkProblem(SortingProblem):
    """Sorting whose shrink hook offers no candidates."""

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        return iter(())


class RaisesLateProblem(SortingProblem):
    """Sorting whose shrink hook offers two candidates and then raises."""

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        if len(input_data) <= 6:
            message = "no more ideas"
            raise RuntimeError(message)
        yield input_data[: len(input_data) // 2]
        yield input_data[:6]


class RepeatingShrinkProblem(SortingProblem):
    """A shrink hook that never offers anything but a copy of its input."""

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        while True:
            yield list(input_data)


class CountingShrinkProblem(SortingProblem):
    """A problem whose shrink hook offers an unrunnable candidate before the useful ones."""

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        yield [2**40]
        yield from super().shrink(input_data)


class ShortInputsInvalidProblem(SortingProblem):
    """Sorting where an input needs at least three values, as a rule of the problem."""

    @override
    def check_input(self, input_data: list[int]) -> str | None:
        return None if len(input_data) >= 3 else "needs at least three values"


class NeedsEightValuesProblem(SortingProblem):
    """Sorting where an input needs at least eight values, as a rule of the problem."""

    @override
    def check_input(self, input_data: list[int]) -> str | None:
        return None if len(input_data) >= 8 else "too short"


class RejectingEverythingProblem(SortingProblem):
    """A problem whose shrink hook offers endless candidates that are all invalid inputs."""

    @override
    def check_input(self, input_data: list[int]) -> str | None:
        return "invalid" if len(input_data) < 100 else None

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        for length in range(10**9):
            yield [length]


class ExplodingCheckProblem(SortingProblem):
    """Sorting whose input check raises."""

    @override
    def check_input(self, input_data: list[int]) -> str | None:
        message = "check exploded"
        raise RuntimeError(message)


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
        message = "timed out after 1.000s"
        raise RunnerError(message, category="timeout")
    return sorted(values)


def build_slow_drop_last(clock: ManualClock) -> Callable[[list[int]], list[int]]:
    """Build a behavior that drops the last value and takes 0.03 seconds of the clock per run."""

    def slow_drop_last(values: list[int]) -> list[int]:
        clock.advance(0.03)
        return drop_last_above_five(values)

    return slow_drop_last


@pytest.fixture
def shrunk_failure() -> ShrunkFailure:
    """The shrunk failure of the wrong implementation on the large generated case."""
    report, _ = run_with_fake_runners({"bad": drop_last_above_five}, [LARGE_GENERATED])
    shrunk = report.outcomes[0].shrunk
    assert shrunk is not None
    return shrunk


def test_a_failing_generated_case_is_shrunk_to_the_smallest_failing_input(
    shrunk_failure: ShrunkFailure,
) -> None:
    """Test a failing generated case is shrunk to the smallest input that still fails."""
    assert shrunk_failure.case.input_data == [0] * 6
    assert shrunk_failure.case.identifier == f"shrunk:{LARGE_GENERATED}"
    assert shrunk_failure.case.origin == ShrunkOrigin(LARGE_GENERATED)


def test_a_shrunk_failure_describes_its_own_failure(
    shrunk_failure: ShrunkFailure,
) -> None:
    """Test the shrunk failure holds the message and the detail of the shrunk input."""
    assert shrunk_failure.message == "Output length 5 does not match input length 6"
    assert shrunk_failure.detail.input_text == "[0, 0, 0, 0, 0, 0]"
    assert shrunk_failure.detail.expected_text == "[0, 0, 0, 0, 0, 0]"
    assert shrunk_failure.detail.actual_text == "[0, 0, 0, 0, 0]"


def test_shrinking_only_runs_the_implementation_that_failed() -> None:
    """Test only the failing implementation runs again while shrinking."""
    _, runners = run_with_fake_runners(
        {"good": sort_correctly, "bad": drop_last_above_five}, [LARGE_GENERATED]
    )

    assert len(runners.collect_inputs_of("good")) == 1
    assert len(runners.collect_inputs_of("bad")) > 1


def test_fixtures_are_not_shrunk() -> None:
    """Test a failing fixture is neither shrunk nor run again."""
    report, runners = run_with_fake_runners(
        {"bad": drop_last_above_five}, ["fixture:already_sorted"]
    )

    assert report.outcomes[0].status is CaseStatus.FAILED
    assert report.outcomes[0].shrunk is None
    assert len(runners.calls) == 1


def test_no_shrink_turns_it_off() -> None:
    """Test a failing generated case is not shrunk when shrinking is off."""
    report, runners = run_with_fake_runners(
        {"bad": drop_last_above_five}, [LARGE_GENERATED], options=NO_SHRINKING
    )

    assert report.outcomes[0].shrunk is None
    assert len(runners.calls) == 1


def test_a_passing_case_is_not_shrunk() -> None:
    """Test a passing generated case is run once."""
    _, runners = run_with_fake_runners({"good": sort_correctly}, [LARGE_GENERATED])

    assert len(runners.calls) == 1


def test_an_error_is_shrunk_too() -> None:
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


def test_a_problem_without_a_shrink_hook_reports_no_shrunk_input() -> None:
    """Test a problem whose shrink hook offers nothing leaves the failure unshrunk."""
    report = run_tests(
        NoShrinkProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )

    assert report.outcomes[0].status is CaseStatus.FAILED
    assert report.outcomes[0].shrunk is None


def test_the_run_cap_limits_one_shrink() -> None:
    """Test one shrink runs the implementation at most the maximum number of times."""
    _, runners = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=3)),
    )

    assert len(runners.calls) == 1 + 3


def test_the_cap_still_keeps_the_best_input_found_so_far() -> None:
    """Test a shrink stopped by the run cap keeps the smallest failing input it found."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=3)),
    )

    shrunk = report.outcomes[0].shrunk

    assert shrunk is not None
    assert 6 <= len(shrunk.case.input_data) < 12


def test_a_spent_time_budget_means_no_shrinking() -> None:
    """Test a time budget of zero seconds leaves the failure unshrunk and unrun."""
    report, runners = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=ShrinkOptions(time_budget_seconds=0.0)),
    )

    assert report.outcomes[0].shrunk is None
    assert len(runners.calls) == 1


def test_only_a_limited_number_of_cases_is_shrunk_per_implementation() -> None:
    """Test an implementation has at most the maximum number of cases shrunk."""
    identifiers = [f"generated:uniform:size={size}:seed=1" for size in (8, 9, 10)]

    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five},
        identifiers,
        options=TestRunOptions(shrinking=ShrinkOptions(maximum_shrunk_cases=2)),
    )

    assert [outcome.shrunk is not None for outcome in report.outcomes] == [
        True,
        True,
        False,
    ]


def test_a_candidate_that_cannot_be_run_is_skipped() -> None:
    """Test a candidate that the implementation cannot run is skipped and shrinking goes on."""

    def refuse_huge_values(values: list[int]) -> list[int]:
        if any(value > 2**31 for value in values):
            message = "value out of range"
            raise ValueError(message)
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


def test_a_shrink_hook_that_raises_is_reported_in_a_note() -> None:
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
        outcome.shrink_note
        == "the problem's shrink hook raised RuntimeError: shrink exploded"
    )


@pytest.fixture
def late_raising_outcome() -> CaseOutcome:
    """The outcome of shrinking with a hook that raises after offering two candidates."""
    report = run_tests(
        RaisesLateProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )
    return report.outcomes[0]


def test_a_shrink_hook_that_raises_part_way_keeps_what_was_found(
    late_raising_outcome: CaseOutcome,
) -> None:
    """Test a shrink hook that raises part way leaves the smallest input found so far."""
    assert late_raising_outcome.shrunk is not None
    assert len(late_raising_outcome.shrunk.case.input_data) == 6


def test_a_shrink_hook_that_raises_part_way_leaves_a_note_with_the_reason(
    late_raising_outcome: CaseOutcome,
) -> None:
    """Test the note of a shrink that ended in an exception names the exception."""
    assert late_raising_outcome.shrink_note is not None
    assert "no more ideas" in late_raising_outcome.shrink_note


def test_a_clean_shrink_has_no_note() -> None:
    """Test a shrink that finishes without hitting a limit leaves no note."""
    report, _ = run_with_fake_runners({"bad": drop_last_above_five}, [LARGE_GENERATED])

    assert report.outcomes[0].shrink_note is None


def test_a_hook_that_only_yields_copies_of_the_input_cannot_keep_a_shrink_going() -> (
    None
):
    """Test the candidate cap ends a shrink whose hook only yields copies of the input."""
    runners = FakeRunners({"bad": drop_last_above_five})

    report = run_tests(
        RepeatingShrinkProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        options=TestRunOptions(
            shrinking=ShrinkOptions(maximum_runs=50, clock=ManualClock())
        ),
        runner_factory=runners,
    )

    assert report.outcomes[0].shrunk is None
    assert report.outcomes[0].shrink_note is not None
    assert "after 50 candidates" in report.outcomes[0].shrink_note
    assert len(runners.calls) == 1


def test_the_time_budget_stops_a_hook_that_never_stops_yielding_copies() -> None:
    """Test the time budget ends a shrink whose hook yields copies of the input forever."""
    report = run_tests(
        RepeatingShrinkProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        options=TestRunOptions(
            shrinking=ShrinkOptions(
                maximum_runs=10**12,
                time_budget_seconds=0.2,
                clock=TickingClock(0.05),
            )
        ),
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )

    note = report.outcomes[0].shrink_note

    assert note is not None
    assert note.startswith("shrinking stopped when its time budget (0.2 seconds per ")


def test_the_deadline_can_pass_part_way_and_the_best_input_so_far_is_kept() -> None:
    """Test a time budget that runs out part way keeps the smallest failing input found."""
    clock = ManualClock()

    report, runners = run_with_fake_runners(
        {"bad": build_slow_drop_last(clock)},
        [LARGE_GENERATED],
        options=TestRunOptions(
            shrinking=ShrinkOptions(
                maximum_runs=10**6, time_budget_seconds=0.25, clock=clock
            )
        ),
    )

    shrunk = report.outcomes[0].shrunk
    assert shrunk is not None
    assert len(shrunk.case.input_data) < 12
    assert len(runners.calls) < 40


def test_every_candidate_runs_with_a_timeout_the_budget_still_allows() -> None:
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


def test_the_timeout_of_an_implementation_bounds_a_candidate_too() -> None:
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

    assert all(
        timeout is not None and timeout <= 2.0 for timeout in runners.timeouts[1:]
    )


def test_a_candidate_that_times_out_under_a_shortened_limit_proves_nothing() -> None:
    """Test a candidate that times out under a shortened limit is not taken as a failure."""
    report, _ = run_with_fake_runners(
        {"slow": time_out_above_three},
        [LARGE_GENERATED],
        options=TestRunOptions(
            timeout_seconds=1000.0,
            shrinking=ShrinkOptions(time_budget_seconds=30.0),
        ),
    )

    assert report.outcomes[0].status is CaseStatus.ERROR
    assert report.outcomes[0].shrunk is None


def test_a_failure_does_not_drift_into_an_unrelated_error_while_shrinking() -> None:
    """Test a wrong output is not shrunk to an input on which the implementation crashes."""

    def wrong_when_large_crashing_when_tiny(values: list[int]) -> list[int]:
        if len(values) <= 2:
            message = "exited with code 7"
            raise RunnerError(message, category="exit code 7")
        return drop_last_above_five(values)

    report, _ = run_with_fake_runners(
        {"bad": wrong_when_large_crashing_when_tiny}, [LARGE_GENERATED]
    )

    outcome = report.outcomes[0]

    assert outcome.status is CaseStatus.FAILED
    assert outcome.shrunk is not None
    assert outcome.shrunk.case.input_data == [0] * 6
    assert "does not match input length" in outcome.shrunk.message


def test_an_error_does_not_drift_into_a_failure_while_shrinking() -> None:
    """Test a crash is not shrunk to an input on which the output is wrong."""

    def crash_when_large_wrong_when_medium(values: list[int]) -> list[int]:
        if len(values) > 8:
            message = "exited with code 7"
            raise RunnerError(message, category="exit code 7")
        return drop_last_above_five(values)

    report, _ = run_with_fake_runners(
        {"bad": crash_when_large_wrong_when_medium}, [LARGE_GENERATED]
    )

    outcome = report.outcomes[0]

    assert outcome.status is CaseStatus.ERROR
    assert outcome.shrunk is not None
    assert outcome.shrunk.case.input_data == [0] * 9


def test_an_error_keeps_its_kind_while_shrinking() -> None:
    """Test a crash with one exit code is not shrunk to an input with another exit code."""

    def exit_code_depends_on_size(values: list[int]) -> list[int]:
        if len(values) > 8:
            message = "exited with code 7"
            raise RunnerError(message, category="exit code 7")
        if len(values) > 3:
            message = "exited with code 9"
            raise RunnerError(message, category="exit code 9")
        return sorted(values)

    report, _ = run_with_fake_runners(
        {"bad": exit_code_depends_on_size}, [LARGE_GENERATED]
    )

    shrunk = report.outcomes[0].shrunk

    assert shrunk is not None
    assert shrunk.case.input_data == [0] * 9
    assert "code 7" in shrunk.message


def test_the_candidate_limit_is_named_when_it_ends_a_shrink() -> None:
    """Test the note names the candidate limit when it ended the shrink."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=ShrinkOptions(maximum_runs=3)),
    )

    assert report.outcomes[0].shrink_note == (
        "shrinking stopped after 3 candidates, its limit; a smaller failing input may exist"
    )


def test_the_time_budget_is_named_when_it_ends_a_shrink() -> None:
    """Test the note names the time budget when it ended the shrink."""
    clock = ManualClock()

    report, _ = run_with_fake_runners(
        {"bad": build_slow_drop_last(clock)},
        [LARGE_GENERATED],
        options=TestRunOptions(
            shrinking=ShrinkOptions(
                maximum_runs=10**6, time_budget_seconds=0.25, clock=clock
            )
        ),
    )

    note = report.outcomes[0].shrink_note

    assert note is not None
    assert note.startswith("shrinking stopped when its time budget (0.25 seconds per ")
    assert "a smaller failing input may exist" in note


def test_the_time_budget_is_measured_with_the_clock_of_the_options() -> None:
    """Test the shrink budget is measured with the clock given in the shrink options."""
    clock = ManualClock()

    def take_one_second_then_drop_last(values: list[int]) -> list[int]:
        clock.advance(1.0)
        return drop_last_above_five(values)

    report, runners = run_with_fake_runners(
        {"bad": take_one_second_then_drop_last},
        [LARGE_GENERATED],
        options=TestRunOptions(
            shrinking=ShrinkOptions(time_budget_seconds=3.5, clock=clock)
        ),
    )

    note = report.outcomes[0].shrink_note

    assert len(runners.calls) == 1 + 4
    assert note is not None
    assert note.startswith("shrinking stopped when its time budget (3.5 seconds per ")


def test_a_case_left_unshrunk_by_the_case_limit_says_so() -> None:
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


def test_a_case_left_unshrunk_by_a_spent_time_budget_says_so() -> None:
    """Test a case skipped because the time budget was used up has a note saying so."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=ShrinkOptions(time_budget_seconds=0.0)),
    )

    assert report.outcomes[0].shrink_note == (
        "not shrunk: the time budget for shrinking (0 seconds per implementation) was used up"
    )


def test_a_fixture_and_a_passing_case_have_no_note() -> None:
    """Test a failing fixture and a passing generated case leave no shrink note."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five}, ["fixture:duplicates", SMALL_GENERATED]
    )

    assert [outcome.shrink_note for outcome in report.outcomes] == [None, None]


def test_no_shrink_leaves_no_note() -> None:
    """Test a failing case leaves no shrink note when shrinking is off."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five}, [LARGE_GENERATED], options=NO_SHRINKING
    )

    assert report.outcomes[0].shrink_note is None


def test_a_verification_that_raises_is_not_shrunk(
    exploding_problem: SortingProblem,
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


def test_an_input_that_cannot_be_serialized_is_not_shrunk() -> None:
    """Test a failure to serialize the input is not shrunk and the note says why."""

    def cannot_serialize(_values: list[int]) -> list[int]:
        message = "serialize_input raised"
        raise RunnerError(message, category="serialization")

    report, runners = run_with_fake_runners(
        {"bad": cannot_serialize}, [LARGE_GENERATED]
    )

    outcome = report.outcomes[0]

    assert outcome.shrunk is None
    assert outcome.shrink_note is not None
    assert outcome.shrink_note.startswith(
        "not shrunk: the serialization failure comes from"
    )
    assert len(runners.calls) == 1


def test_a_failure_of_the_implementation_is_still_shrunk() -> None:
    """Test a wrong output of the implementation is shrunk."""
    report, _ = run_with_fake_runners({"bad": drop_last_above_five}, [LARGE_GENERATED])

    assert report.outcomes[0].shrunk is not None


def test_a_timeout_longer_than_the_shrink_budget_is_not_shrunk() -> None:
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
    assert (
        outcome.shrink_note
        == "not shrunk: the timeout is longer than the shrink budget"
    )
    assert len(runners.calls) == 1


def test_a_timeout_the_shrink_budget_covers_is_shrunk() -> None:
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


def test_a_spent_budget_is_named_before_a_timeout_that_is_longer_than_it() -> None:
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


def test_candidates_that_are_not_valid_inputs_are_skipped_and_never_run() -> None:
    """Test a candidate that the problem rejects as invalid is never run."""
    runners = FakeRunners({"bad": drop_last_above_five})

    run_tests(
        ShortInputsInvalidProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        runner_factory=runners,
    )

    assert all(len(values) >= 3 for values in runners.collect_inputs_of("bad"))


def test_a_rule_that_rejects_only_tiny_inputs_does_not_change_the_shrunk_input() -> (
    None
):
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


def test_a_rule_can_force_a_larger_shrunk_input() -> None:
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


def test_rejected_candidates_count_against_the_budget() -> None:
    """Test candidates rejected as invalid use up the candidate budget."""
    runners = FakeRunners({"bad": drop_last_above_five})

    report = run_tests(
        RejectingEverythingProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        options=TestRunOptions(
            shrinking=ShrinkOptions(maximum_runs=25, clock=ManualClock())
        ),
        runner_factory=runners,
    )

    assert len(runners.calls) == 1
    assert report.outcomes[0].shrunk is None
    assert report.outcomes[0].shrink_note is not None
    assert "after 25 candidates" in report.outcomes[0].shrink_note


def test_a_check_that_raises_is_reported_in_a_note_naming_the_hook() -> None:
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


class UnequatableInputsProblem(SortingProblem):
    """Sorting whose generated inputs cannot be compared, with a shrink hook that never compares."""

    @override
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        (uniform, *_) = super().generators()

        def generate_unequatable(
            random_generator: random.Random, size: int
        ) -> list[int]:
            return UnequatableValues(uniform.generate(random_generator, size=size))

        return (
            InputGenerator(
                "uniform", description="uncomparable", generate=generate_unequatable
            ),
        )

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        yield list(input_data)[:-1]


def test_a_shrink_candidate_whose_comparison_raises_is_noted_as_such() -> None:
    """Test a comparison that raises ends shrinking with a note that names the comparison."""
    problem = UnequatableInputsProblem()

    report = run_tests(
        problem,
        build_named_implementations("bad"),
        [resolve_case(problem, LARGE_GENERATED)],
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )

    (outcome,) = report.outcomes
    assert outcome.status is CaseStatus.FAILED
    assert outcome.shrunk is None
    assert outcome.shrink_note == (
        "comparing a shrink candidate with its input raised TypeError: no equality here"
    )
