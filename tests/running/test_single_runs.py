"""Tests for running and judging a single case."""

from collections.abc import Callable
from typing import Any

from algorithm_playground.core import (
    CaseStatus,
    RunnerLike,
    SingleRun,
    run_single,
    run_single_with_trace,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    TraceFailure,
    build_insertion_sort_trace,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)

INPUT = [3, 1, 2]


def build_only_runner(
    behavior: Callable[[Any], Any],
    **keywords: Any,  # noqa: ANN401  forwarded unchanged to FakeRunners
) -> tuple[FakeRunners, RunnerLike]:
    """Build the fake runner of one implementation called ``only``."""
    factory = FakeRunners({"only": behavior}, **keywords)
    return factory, factory(SortingProblem(), build_named_implementations("only")[0])


def test_a_correct_output_passes_without_asking_for_a_trace() -> None:
    """Test a correct output passes and no trace is requested."""
    factory, runner = build_only_runner(sort_correctly)

    run = run_single(SortingProblem(), runner, INPUT)

    assert run.status is CaseStatus.PASSED
    assert run.message == ""
    assert run.output == [1, 2, 3]
    assert factory.traced_calls == []


def test_a_wrong_output_fails_with_the_message_of_the_verifier() -> None:
    """Test a wrong output fails with a message from the verifier and keeps the output."""
    _, runner = build_only_runner(drop_last_above_five)

    run = run_single(SortingProblem(), runner, [6, 5, 4, 3, 2, 1])

    assert run.status is CaseStatus.FAILED
    assert run.message != ""
    assert run.has_output


def test_a_runner_error_is_an_error_with_its_category() -> None:
    """Test a runner error gives an error status with the category "error" and no output."""
    _, runner = build_only_runner(crash)

    run = run_single(SortingProblem(), runner, INPUT)

    assert run.status is CaseStatus.ERROR
    assert run.category == "error"
    assert not run.has_output


def test_the_timeout_is_handed_to_the_runner_of_a_plain_run() -> None:
    """Test the timeout reaches the runner of a plain run."""
    factory, runner = build_only_runner(sort_correctly)

    run_single(SortingProblem(), runner, INPUT, timeout_seconds=2.5)

    assert factory.timeouts == [2.5]


def test_the_run_asks_for_a_trace_and_keeps_it_in_the_result() -> None:
    """Test the run requests a trace and keeps it in the result."""
    factory, runner = build_only_runner(
        sort_correctly, traces={"only": build_insertion_sort_trace}
    )

    run = run_single_with_trace(SortingProblem(), runner, INPUT)

    assert run.status is CaseStatus.PASSED
    assert factory.traced_calls == ["only"]
    assert run.result is not None
    assert run.result.trace == build_insertion_sort_trace(INPUT)


def test_a_trace_that_cannot_be_decoded_is_reported_in_the_result() -> None:
    """Test a trace that cannot be decoded is reported in the result while the run passes."""
    _, runner = build_only_runner(
        sort_correctly, traces={"only": lambda _: TraceFailure("bad trace")}
    )

    run = run_single_with_trace(SortingProblem(), runner, INPUT)

    assert run.status is CaseStatus.PASSED
    assert run.result is not None
    assert run.result.trace is None
    assert run.result.trace_error == "bad trace"


def test_the_timeout_is_handed_to_the_runner_of_a_traced_run() -> None:
    """Test the timeout reaches the runner of a traced run."""
    factory, runner = build_only_runner(sort_correctly)

    run_single_with_trace(SortingProblem(), runner, INPUT, timeout_seconds=4.0)

    assert factory.timeouts == [4.0]


def test_failures_of_the_same_status_and_category_match() -> None:
    """Test two failures with the same status and category are the same failure."""
    first = SingleRun(CaseStatus.ERROR, "exited with code 3", category="exit code 3")
    second = SingleRun(CaseStatus.ERROR, "another message", category="exit code 3")

    assert first.is_same_failure_as(second)


def test_failures_of_another_category_do_not_match() -> None:
    """Test failures with different categories are not the same failure."""
    first = SingleRun(CaseStatus.ERROR, "", category="exit code 3")
    second = SingleRun(CaseStatus.ERROR, "", category="timeout")

    assert not first.is_same_failure_as(second)


def test_failures_of_another_status_do_not_match() -> None:
    """Test failures with different statuses are not the same failure."""
    failed = SingleRun(CaseStatus.FAILED, "", category="wrong output")
    errored = SingleRun(CaseStatus.ERROR, "", category="wrong output")

    assert not failed.is_same_failure_as(errored)


def test_a_pass_never_matches() -> None:
    """Test a passing run is never the same failure as another run."""
    passed = SingleRun(CaseStatus.PASSED, "")

    assert not passed.is_same_failure_as(passed)
