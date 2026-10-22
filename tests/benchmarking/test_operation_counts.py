"""Tests for the operation counts that the benchmark engine reads from traces."""

from collections.abc import Callable
from typing import Any

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    BenchmarkPhase,
    BenchmarkProgress,
    BenchmarkReport,
    BenchmarkSettings,
    CellStatus,
    OperationIssueKind,
    Problem,
    RunnerError,
    run_benchmark,
)
from algorithm_playground.problems.sorting import SortingProblem, SortingTrace
from helpers.fakes import (
    FakeRunners,
    TraceFailure,
    build_insertion_sort_trace,
    build_merge_sort_trace,
    build_named_implementations,
    build_snapshot_only_trace,
    sort_correctly,
)
from helpers.misbehaving import FaultyProblem, count_distinct_values


class ProblemWhoseOperationCountsRaise(SortingProblem):
    """Sorting whose operation counting hook raises."""

    @override
    def operation_counts(
        self, input_data: list[int], output: list[int], trace: SortingTrace
    ) -> dict[str, int] | None:
        message = "counting exploded"
        raise RuntimeError(message)


def build_settings(**overrides: object) -> BenchmarkSettings:
    """Build benchmark settings of two small sizes, with the given fields replaced."""
    values: dict[str, Any] = {
        "seed": 1,
        "sizes": (5, 10),
        "repetitions": 1,
        "warmup": 0,
        "timeout_seconds": 30.0,
        "verify_outputs": True,
        "subtract_startup_time": False,
    }
    values.update(overrides)
    return BenchmarkSettings(**values)


def run_fake_benchmark(
    behaviors: dict[str, Callable[[Any], Any]],
    durations: dict[str, float | Callable[[Any], float]] | None = None,
    *,
    problem: Problem[Any, Any, Any] | None = None,
    **overrides: object,
) -> tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]]:
    """Benchmark fake implementations and return the report, the runners and the progress events."""
    runners = FakeRunners(behaviors, durations)
    events: list[BenchmarkProgress] = []
    report = run_benchmark(
        SortingProblem() if problem is None else problem,
        build_named_implementations(*behaviors),
        build_settings(**overrides),
        runner_factory=runners,
        on_progress=events.append,
    )
    return report, runners, events


def run_counting_benchmark(
    traces: dict[str, Callable[[list[int]], object]],
    *,
    problem: Problem[Any, Any, Any] | None = None,
    **overrides: object,
) -> tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]]:
    """Benchmark fake implementations that write the given traces, counting operations."""
    behaviors = dict.fromkeys(traces, sort_correctly)
    runners = FakeRunners(behaviors, traces=traces)
    events: list[BenchmarkProgress] = []
    settings = build_settings(count_operations=True, sizes=(8, 16, 32, 64), **overrides)
    report = run_benchmark(
        SortingProblem() if problem is None else problem,
        build_named_implementations(*behaviors),
        settings,
        runner_factory=runners,
        on_progress=events.append,
    )
    return report, runners, events


@pytest.fixture
def untraced_run() -> tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]]:
    """A benchmark that asks to count operations of a problem without a trace format."""
    return run_fake_benchmark(
        {"a": count_distinct_values},
        problem=FaultyProblem(),
        sizes=(3, 6),
        count_operations=True,
    )


def test_the_report_passes(
    untraced_run: tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]],
) -> None:
    """Test asking to count operations of such a problem does not fail the benchmark."""
    report, _, _ = untraced_run

    assert report.has_passed


def test_the_settings_say_that_operations_were_not_counted(
    untraced_run: tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]],
) -> None:
    """Test the settings of the report record that operation counting was off."""
    report, _, _ = untraced_run

    assert report.settings.count_operations is False


def test_no_counting_run_is_made(
    untraced_run: tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]],
) -> None:
    """Test no run asks for a trace and no progress event names the counting phase."""
    _, runners, events = untraced_run

    assert runners.traced_calls == []
    assert BenchmarkPhase.OPERATION_COUNT not in {event.phase for event in events}


def test_measurements_have_neither_counts_nor_an_issue(
    untraced_run: tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]],
) -> None:
    """Test no measurement holds operation counts or an operation issue."""
    report, _, _ = untraced_run

    for measurement in report.implementations[0].measurements:
        assert measurement.operation_counts is None
        assert measurement.operation_issue is None


def test_a_problem_with_a_trace_format_keeps_counting() -> None:
    """Test a problem with a trace format has its operations counted at every size."""
    report, runners, _ = run_fake_benchmark(
        {"a": sort_correctly}, sizes=(3, 6), count_operations=True
    )

    assert report.settings.count_operations is True
    assert runners.traced_calls == ["a", "a"]


@pytest.fixture
def insertion_and_merge_report() -> BenchmarkReport:
    """The report of counting an insertion sort and a merge sort on two distributions."""
    report, _, _ = run_counting_benchmark(
        {"insertion": build_insertion_sort_trace, "merge": build_merge_sort_trace},
        distributions=("reversed", "sorted"),
    )
    return report


def test_insertion_sort_counts_every_pair_on_reversed_input(
    insertion_and_merge_report: BenchmarkReport,
) -> None:
    """Test an insertion sort of reversed input compares and swaps every pair of values."""
    insertion = insertion_and_merge_report.implementations[0]

    counts = [
        measurement.operation_counts
        for measurement in insertion.measurements_for("reversed")
    ]

    assert counts == [
        {
            "compares": size * (size - 1) // 2,
            "swaps": size * (size - 1) // 2,
            "writes": 0,
        }
        for size in (8, 16, 32, 64)
    ]


def test_insertion_sort_compares_neighbours_only_on_sorted_input(
    insertion_and_merge_report: BenchmarkReport,
) -> None:
    """Test an insertion sort of sorted input compares neighbours and swaps nothing."""
    insertion = insertion_and_merge_report.implementations[0]

    counts = [
        measurement.operation_counts
        for measurement in insertion.measurements_for("sorted")
    ]

    assert counts == [
        {"compares": size - 1, "swaps": 0, "writes": 0} for size in (8, 16, 32, 64)
    ]


def test_merge_sort_writes_values_and_never_swaps(
    insertion_and_merge_report: BenchmarkReport,
) -> None:
    """Test a merge sort is counted as writing values and swapping none."""
    merge = insertion_and_merge_report.implementations[1].measurement_at("sorted", 8)

    assert merge is not None
    assert merge.operation_counts is not None
    assert merge.operation_counts["swaps"] == 0
    assert merge.operation_counts["writes"] > 0


def test_each_point_gets_one_extra_traced_run_and_the_timed_runs_carry_no_trace() -> (
    None
):
    """Test each measurement point has one traced run besides its untraced timed runs."""
    _, runners, _ = run_counting_benchmark(
        {"a": build_insertion_sort_trace}, repetitions=2, warmup=1
    )

    timed = len(runners.calls) - len(runners.traced_calls)

    assert runners.traced_calls == ["a"] * 4
    assert timed == (1 + 4) * 3


def test_the_traced_run_uses_the_input_of_the_timed_runs() -> None:
    """Test the traced run of a point receives the same input as its timed run."""
    _, runners, _ = run_counting_benchmark(
        {"a": build_insertion_sort_trace}, repetitions=1
    )

    _, *sized = runners.collect_inputs_of("a")

    assert sized[0::2] == sized[1::2]


def test_nothing_is_counted_when_the_setting_is_off() -> None:
    """Test no trace is requested and no counts are recorded when counting is off."""
    runners = FakeRunners(
        {"a": sort_correctly}, traces={"a": build_insertion_sort_trace}
    )

    report = run_benchmark(
        SortingProblem(),
        build_named_implementations("a"),
        build_settings(),
        runner_factory=runners,
    )

    assert runners.traced_calls == []
    assert all(
        measurement.operation_counts is None
        for measurement in report.implementations[0].measurements
    )
    assert report.implementations[0].operation_names() == ()


def test_an_implementation_without_a_trace_has_no_counts_while_the_others_do() -> None:
    """Test an implementation that writes no trace has no counts next to one that does."""
    report, _, _ = run_counting_benchmark(
        {"traced": build_insertion_sort_trace, "silent": lambda _: None}
    )
    traced, silent = report.implementations

    assert all(
        measurement.operation_counts is not None for measurement in traced.measurements
    )
    assert all(
        measurement.operation_counts is None for measurement in silent.measurements
    )
    assert silent.failure is None
    assert silent.operation_growth("uniform") == {}


def test_a_trace_with_snapshots_only_reports_no_counts() -> None:
    """Test a trace that holds snapshots and no events gives no operation counts."""
    report, _, _ = run_counting_benchmark({"a": build_snapshot_only_trace})

    assert all(
        measurement.operation_counts is None
        for measurement in report.implementations[0].measurements
    )


def test_a_malformed_trace_is_recorded_on_the_measurement() -> None:
    """Test a trace that cannot be decoded is recorded as an issue on each measurement."""
    report, _, _ = run_counting_benchmark(
        {
            "broken": lambda _: TraceFailure("Unsupported trace kind: 7"),
            "fine": build_insertion_sort_trace,
        },
    )
    broken, fine = report.implementations

    assert broken.failure is None
    assert len(broken.measurements) == 4
    for measurement in broken.measurements:
        assert measurement.operation_counts is None
        assert measurement.operation_issue is not None
        assert measurement.operation_issue.kind is OperationIssueKind.MALFORMED_TRACE
        assert measurement.operation_issue.message == "Unsupported trace kind: 7"
    assert all(measurement.operation_issue is None for measurement in fine.measurements)


def test_counts_come_only_from_a_traced_run_whose_output_verifies() -> None:
    """Test a traced run with a wrong output gives no counts and records an issue."""
    runners = FakeRunners(
        {"a": sort_correctly},
        traces={"a": build_insertion_sort_trace},
        traced_behaviors={"a": lambda values: sorted(values)[:-1]},
    )

    report = run_benchmark(
        SortingProblem(),
        build_named_implementations("a"),
        build_settings(count_operations=True, sizes=(8, 16)),
        runner_factory=runners,
    )

    item = report.implementations[0]
    assert item.failure is None
    for measurement in item.measurements:
        assert measurement.operation_counts is None
        assert measurement.operation_issue is not None
        assert measurement.operation_issue.kind is OperationIssueKind.UNVERIFIED_OUTPUT
        assert "does not match input length" in measurement.operation_issue.message


def test_counts_are_read_from_an_unverified_output_when_verification_is_off() -> None:
    """Test counts are recorded from a traced run whose output is wrong when verification is off."""
    runners = FakeRunners(
        {"a": sort_correctly},
        traces={"a": build_insertion_sort_trace},
        traced_behaviors={"a": lambda _: []},
    )

    report = run_benchmark(
        SortingProblem(),
        build_named_implementations("a"),
        build_settings(count_operations=True, verify_outputs=False, sizes=(8,)),
        runner_factory=runners,
    )

    measurement = report.implementations[0].measurements[0]
    assert measurement.operation_counts is not None
    assert measurement.operation_issue is None


def test_a_failed_traced_run_fails_the_implementation_but_keeps_its_timings() -> None:
    """Test a traced run that fails ends the implementation and keeps the timings so far."""

    def fail_for_large(values: list[int]) -> object:
        if len(values) > 16:
            message = "could not write the trace"
            raise RunnerError(message)
        return build_insertion_sort_trace(values)

    report, _, _ = run_counting_benchmark(
        {"a": fail_for_large, "b": build_insertion_sort_trace}
    )
    failed, healthy = report.implementations

    assert failed.failure is not None
    assert (
        "Run failed for size 32 (uniform) while counting operations" in failed.failure
    )
    assert [measurement.size for measurement in failed.measurements] == [8, 16, 32]
    assert failed.measurements[-1].operation_counts is None
    issue = failed.measurements[-1].operation_issue
    assert issue is not None
    assert issue.kind is OperationIssueKind.COUNTING_FAILED
    assert failed.status_at("uniform", 32) is CellStatus.MEASURED
    assert failed.status_at("uniform", 64) is CellStatus.SKIPPED
    assert [measurement.size for measurement in healthy.measurements] == [
        8,
        16,
        32,
        64,
    ]


def test_an_exception_while_counting_is_recorded_as_a_failure() -> None:
    """Test an operation counting hook that raises is recorded as a failure naming the hook."""
    report, _, _ = run_counting_benchmark(
        {"a": build_insertion_sort_trace},
        problem=ProblemWhoseOperationCountsRaise(),
    )

    failure = report.implementations[0].failure

    assert failure is not None
    assert "operation_counts raised RuntimeError: counting exploded" in failure


def test_progress_events_announce_each_counting_run() -> None:
    """Test every counting run reports a started and a completed event for its size."""
    _, _, events = run_counting_benchmark(
        {"a": build_insertion_sort_trace}, distributions=("sorted",)
    )

    counting = [
        event for event in events if event.phase is BenchmarkPhase.OPERATION_COUNT
    ]

    assert [
        (event.size, event.completed, event.distribution) for event in counting
    ] == [
        (size, completed, "sorted")
        for size in (8, 16, 32, 64)
        for completed in (False, True)
    ]


def test_compare_counts_grow_quadratically_for_insertion_and_linearithmically_for_merge() -> (
    None
):
    """Test the compares of an insertion sort grow as n squared and those of a merge sort as n log n."""
    report, _, _ = run_counting_benchmark(
        {"insertion": build_insertion_sort_trace, "merge": build_merge_sort_trace},
        distributions=("reversed",),
    )

    insertion, merge = (
        benchmark.operation_growth("reversed")["compares"]
        for benchmark in report.implementations
    )

    assert insertion is not None
    assert merge is not None
    assert insertion.exponent == pytest.approx(2.0, abs=0.2)
    assert insertion.growth_class == "n^2"
    assert 1.0 < merge.exponent < 1.4
    assert merge.growth_class == "n log n"


def test_a_count_that_is_always_zero_has_no_growth_estimate() -> None:
    """Test an operation that is never done has no growth while the others do."""
    report, _, _ = run_counting_benchmark(
        {"insertion": build_insertion_sort_trace}, distributions=("sorted",)
    )

    growths = report.implementations[0].operation_growth("sorted")

    compares = growths["compares"]
    assert compares is not None
    assert compares.exponent == pytest.approx(1.0, abs=0.1)
    assert growths["swaps"] is None
    assert growths["writes"] is None


def test_operation_names_follow_first_appearance() -> None:
    """Test the operation names are listed in the order the counts first name them."""
    report, _, _ = run_counting_benchmark({"a": build_insertion_sort_trace})

    names = report.implementations[0].operation_names()

    assert names == ("compares", "swaps", "writes")
