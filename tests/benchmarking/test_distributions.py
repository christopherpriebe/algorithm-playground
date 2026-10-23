"""Tests for benchmarking every distribution of inputs."""

from collections.abc import Callable
from typing import Any

import pytest

from algorithm_playground.core import (
    BenchmarkFailure,
    BenchmarkPhase,
    BenchmarkProgress,
    BenchmarkReport,
    BenchmarkSettings,
    CaseError,
    CellStatus,
    Dimension,
    FailureStage,
    Problem,
    RunnerError,
    Size,
    generate_case,
    include_failed_implementations,
    run_benchmark,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    sort_correctly,
)
from helpers.sizes import build_sizes
from helpers.two_dimensions import (
    RejectingMinimumSizeProblem,
    SimpleGraphProblem,
    add_pair,
)


class NeedsTwoValuesProblem(SortingProblem):
    """Sorting whose generators cannot produce fewer than two values."""

    dimensions = (Dimension("size", minimum=2),)


def build_settings(**overrides: object) -> BenchmarkSettings:
    """Build benchmark settings of two small sizes, with the given fields replaced."""
    values: dict[str, Any] = {
        "seed": 1,
        "sizes": build_sizes(5, 10),
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


def run_picky_benchmark() -> tuple[BenchmarkReport, FakeRunners]:
    """Benchmark an implementation that crashes on sorted input next to a correct one."""

    def fail_on_sorted_input(values: list[int]) -> list[int]:
        if len(values) > 3 and values == sorted(values):
            return crash(values)
        return sorted(values)

    report, runners, _ = run_fake_benchmark(
        {"picky": fail_on_sorted_input, "steady": sort_correctly},
        sizes=build_sizes(5, 10),
        distributions=("uniform", "sorted", "reversed"),
    )
    return report, runners


def test_the_default_generator_alone_is_measured_when_none_is_named() -> None:
    """Test the settings and the measurements name the uniform distribution by default."""
    report, _, _ = run_fake_benchmark({"a": sort_correctly}, sizes=build_sizes(3))

    assert report.settings.distributions == ("uniform",)
    assert [
        measurement.distribution
        for measurement in report.implementations[0].measurements
    ] == ["uniform"]


def test_every_named_distribution_is_measured_at_every_size_in_order() -> None:
    """Test each named distribution is measured at every size, one distribution after another."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4, 9),
        seed=3,
        distributions=("sorted", "few_unique"),
    )

    measurements = report.implementations[0].measurements

    assert report.settings.distributions == ("sorted", "few_unique")
    assert [
        (measurement.distribution, measurement.size) for measurement in measurements
    ] == [
        ("sorted", Size(size=4)),
        ("sorted", Size(size=9)),
        ("few_unique", Size(size=4)),
        ("few_unique", Size(size=9)),
    ]


def test_each_measurement_names_the_generated_case_of_its_distribution() -> None:
    """Test the case identifier of a measurement names its distribution, size and seed."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4, 9),
        seed=3,
        distributions=("sorted", "few_unique"),
    )

    measurements = report.implementations[0].measurements

    assert [measurement.case_identifier for measurement in measurements] == [
        "generated:sorted:size=4:seed=3",
        "generated:sorted:size=9:seed=3",
        "generated:few_unique:size=4:seed=3",
        "generated:few_unique:size=9:seed=3",
    ]


def test_the_runner_receives_the_input_of_the_named_distribution() -> None:
    """Test the sorted distribution sends an already sorted input to the runner."""
    _, runners, _ = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4, 9),
        seed=3,
        distributions=("sorted", "few_unique"),
    )
    by_name = {generator.name: generator for generator in SortingProblem().generators()}
    sorted_input = generate_case(
        by_name["sorted"], size=Size(size=9), seed=3
    ).input_data

    assert sorted_input == sorted(sorted_input)
    assert sorted_input in runners.collect_inputs_of("a")


def test_a_measurement_is_found_by_distribution_and_size() -> None:
    """Test a measurement is looked up by its distribution and size."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4, 9),
        distributions=("sorted", "reversed"),
    )

    found = report.implementations[0].measurement_at("reversed", Size(size=9))

    assert found is not None
    assert (found.distribution, found.size) == ("reversed", Size(size=9))


def test_a_measurement_that_does_not_exist_is_not_found() -> None:
    """Test looking up an unmeasured size or distribution finds nothing."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4, 9),
        distributions=("sorted", "reversed"),
    )
    item = report.implementations[0]

    assert item.measurement_at("reversed", Size(size=5)) is None
    assert item.measurement_at("uniform", Size(size=9)) is None


def test_the_measurements_of_one_distribution_are_selected_by_name() -> None:
    """Test the measurements of a distribution are selected in size order."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4, 9),
        distributions=("sorted", "reversed"),
    )
    item = report.implementations[0]

    assert [measurement.size for measurement in item.measurements_for("sorted")] == [
        Size(size=4),
        Size(size=9),
    ]
    assert item.measurements_for("uniform") == ()


def test_the_startup_is_measured_once_per_implementation_whatever_the_distributions() -> (
    None
):
    """Test the startup runs once per repetition however many distributions are measured."""
    report, runners, events = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4),
        repetitions=2,
        distributions=("sorted", "reversed", "all_equal"),
    )

    startup_events = [
        event
        for event in events
        if event.phase is BenchmarkPhase.STARTUP and event.completed
    ]

    assert [(event.phase, event.distribution) for event in events if event.completed][
        :2
    ] == [(BenchmarkPhase.STARTUP, None)] * 2
    assert len(startup_events) == 2
    assert runners.collect_inputs_of("a")[:2] == [[], []]
    assert report.implementations[0].startup is not None
    assert len(runners.collect_inputs_of("a")) == 2 + 3 * 2


def test_the_startup_input_has_the_minimum_size_of_the_problem() -> None:
    """Test the startup runs on an input of the minimum size of the problem."""
    runners = FakeRunners({"a": sort_correctly})

    run_benchmark(
        NeedsTwoValuesProblem(),
        build_named_implementations("a"),
        build_settings(sizes=build_sizes(4), distributions=("reversed",)),
        runner_factory=runners,
    )

    inputs = runners.collect_inputs_of("a")
    assert len(inputs[0]) == 2
    assert len(inputs[1]) == 4


def test_a_size_below_the_minimum_size_of_the_problem_is_an_error() -> None:
    """Test a size below the minimum size of the problem raises a CaseError."""
    with pytest.raises(
        CaseError, match=r"'size' of at least 2, but the sizes include size=1"
    ):
        run_benchmark(
            NeedsTwoValuesProblem(),
            build_named_implementations("a"),
            build_settings(sizes=build_sizes(1, 4)),
            runner_factory=FakeRunners({"a": sort_correctly}),
        )


def test_progress_events_name_the_distribution_of_each_sized_run() -> None:
    """Test each completed sized run reports its distribution and size."""
    _, _, events = run_fake_benchmark(
        {"a": sort_correctly},
        sizes=build_sizes(4),
        distributions=("sorted", "reversed"),
    )

    sized = [
        (event.distribution, event.size)
        for event in events
        if event.size is not None and event.completed
    ]

    assert sized == [("sorted", Size(size=4)), ("reversed", Size(size=4))]


def test_identical_inputs_reach_every_implementation_in_every_distribution() -> None:
    """Test two implementations receive the same inputs in every distribution."""
    _, runners, _ = run_fake_benchmark(
        {"a": sort_correctly, "b": sort_correctly},
        distributions=("sorted", "organ_pipe"),
    )

    assert runners.collect_inputs_of("a") == runners.collect_inputs_of("b")


def test_a_failure_names_its_distribution_and_size() -> None:
    """Test the failure of an implementation names the stage, distribution and size."""
    report, _ = run_picky_benchmark()

    picky = report.implementations[0]

    assert picky.failure is not None
    assert "size=5 (sorted)" in picky.failure
    assert [(item.stage, item.distribution, item.size) for item in picky.failures] == [
        (FailureStage.MEASUREMENT, "sorted", Size(size=5))
    ]


def test_a_failure_skips_only_the_rest_of_its_distribution() -> None:
    """Test an implementation keeps the measurements of the distributions that did not fail."""
    report, runners = run_picky_benchmark()

    picky = report.implementations[0]

    assert [
        (measurement.distribution, measurement.size)
        for measurement in picky.measurements
    ] == [
        ("uniform", Size(size=5)),
        ("uniform", Size(size=10)),
        ("reversed", Size(size=5)),
        ("reversed", Size(size=10)),
    ]
    # startup, uniform x2, the failed sorted run, reversed x2: nothing ran for sorted size 10
    assert len(runners.collect_inputs_of("picky")) == 1 + 2 + 1 + 2


def test_a_failure_in_one_distribution_does_not_affect_other_implementations() -> None:
    """Test an implementation next to a failing one is measured in every distribution."""
    report, _ = run_picky_benchmark()

    steady = report.implementations[1]

    assert [measurement.distribution for measurement in steady.measurements] == [
        "uniform",
        "uniform",
        "sorted",
        "sorted",
        "reversed",
        "reversed",
    ]


def test_cells_after_a_failure_are_skipped_and_the_failed_cell_is_failed() -> None:
    """Test the failed cell is failed and the cells after it in its distribution are skipped."""
    report, _ = run_picky_benchmark()

    picky = report.implementations[0]

    assert picky.startup_status() is CellStatus.MEASURED
    assert [
        picky.status_at(distribution, size)
        for distribution in ("uniform", "sorted", "reversed")
        for size in build_sizes(5, 10)
    ] == [
        CellStatus.MEASURED,
        CellStatus.MEASURED,
        CellStatus.FAILED,
        CellStatus.SKIPPED,
        CellStatus.MEASURED,
        CellStatus.MEASURED,
    ]


def test_a_startup_failure_fails_the_startup_cell_and_skips_every_size() -> None:
    """Test a startup failure fails the startup cell and skips every size and distribution."""
    report, runners, _ = run_fake_benchmark(
        {"crashing": crash, "steady": sort_correctly},
        distributions=("uniform", "sorted"),
    )

    crashing = report.implementations[0]

    assert crashing.failures[0].stage is FailureStage.STARTUP
    assert crashing.startup_status() is CellStatus.FAILED
    assert crashing.status_at("sorted", Size(size=5)) is CellStatus.SKIPPED
    assert len(runners.collect_inputs_of("crashing")) == 1


@pytest.fixture(
    params=[
        (FailureStage.BUILD, "make: error"),
        (FailureStage.CANNOT_RUN, "Cannot run: not found"),
    ],
    ids=["build", "cannot-run"],
)
def completed_report(request: pytest.FixtureRequest) -> BenchmarkReport:
    """A report completed with an implementation that failed before it could run."""
    stage, message = request.param
    report, _, _ = run_fake_benchmark({"steady": sort_correctly})
    return include_failed_implementations(
        report,
        build_named_implementations("steady", "unrun"),
        {"unrun": BenchmarkFailure(stage=stage, message=message)},
    )


def test_an_implementation_that_failed_before_running_fails_every_cell(
    completed_report: BenchmarkReport,
) -> None:
    """Test an implementation that never ran has the status failed in every cell."""
    unrun = completed_report.implementations[1]

    assert unrun.startup_status() is CellStatus.FAILED
    assert unrun.status_at("uniform", Size(size=5)) is CellStatus.FAILED


def test_an_implementation_that_failed_before_running_fails_the_report(
    completed_report: BenchmarkReport,
) -> None:
    """Test a report with an implementation that never ran has not passed."""
    assert not completed_report.has_passed


def test_a_failed_build_records_the_build_message() -> None:
    """Test a build failure is recorded with its stage and message."""
    report, _, _ = run_fake_benchmark({"steady": sort_correctly})
    completed = include_failed_implementations(
        report,
        build_named_implementations("steady", "unbuilt"),
        {"unbuilt": BenchmarkFailure(stage=FailureStage.BUILD, message="make: error")},
    )

    unbuilt = completed.implementations[1]

    assert [(item.stage, item.message) for item in unbuilt.failures] == [
        (FailureStage.BUILD, "make: error")
    ]


def test_an_implementation_that_cannot_run_records_the_cannot_run_stage() -> None:
    """Test an implementation that cannot run is recorded with the cannot-run stage."""
    report, _, _ = run_fake_benchmark({"steady": sort_correctly})
    completed = include_failed_implementations(
        report,
        build_named_implementations("steady", "missing"),
        {
            "missing": BenchmarkFailure(
                stage=FailureStage.CANNOT_RUN, message="Cannot run: not found"
            )
        },
    )

    missing = completed.implementations[1]

    assert missing.failures[0].stage is FailureStage.CANNOT_RUN


def test_a_run_that_cannot_write_the_input_fails_that_implementation_and_distribution() -> (
    None
):
    """Test a run that cannot write its input fails the implementation in that distribution."""

    def cannot_serialize(values: list[int]) -> list[int]:
        if values and values == sorted(values):
            message = "The problem's serialize_input hook could not write the input"
            raise RunnerError(message)
        return sorted(values)

    report, _, _ = run_fake_benchmark(
        {"a": cannot_serialize},
        sizes=build_sizes(5),
        distributions=("sorted", "reversed"),
    )

    item = report.implementations[0]

    assert item.failure is not None
    assert "serialize_input" in item.failure
    assert [measurement.distribution for measurement in item.measurements] == [
        "reversed"
    ]


def test_an_unknown_distribution_is_an_error_naming_the_available_ones() -> None:
    """Test an unknown distribution raises a CaseError that lists the available ones."""
    with pytest.raises(
        CaseError, match=r"Unknown distribution 'nope'.*uniform.*median_of_three"
    ):
        run_fake_benchmark({"a": sort_correctly}, distributions=("nope",))


def test_a_size_the_problem_rejects_is_an_error_before_anything_runs() -> None:
    """Test a benchmark size the problem's own rule rejects is refused before any run."""
    runners = FakeRunners({"adder": add_pair})

    with pytest.raises(CaseError, match="does not accept the size vertices=3:edges=4"):
        run_benchmark(
            SimpleGraphProblem(),
            build_named_implementations("adder"),
            build_settings(sizes=(Size(vertices=3, edges=4),)),
            runner_factory=runners,
        )

    assert runners.calls == []


def test_a_problem_that_rejects_its_minimum_size_is_an_error_before_anything_runs() -> (
    None
):
    """Test the startup size is checked against the problem's rule before any run."""
    runners = FakeRunners({"adder": add_pair})

    with pytest.raises(
        CaseError,
        match="does not accept the size vertices=1:edges=0: an edge is needed",
    ):
        run_benchmark(
            RejectingMinimumSizeProblem(),
            build_named_implementations("adder"),
            build_settings(sizes=(Size(vertices=3, edges=3),)),
            runner_factory=runners,
        )

    assert runners.calls == []
