"""Tests for how the benchmark engine measures implementations."""

import random
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
    FailureStage,
    HookError,
    Implementation,
    InputGenerator,
    Problem,
    RunnerError,
    Size,
    count_total_runs,
    generate_case,
    get_default_generator,
    run_benchmark,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import write_sorter
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    sort_correctly,
)
from helpers.sizes import build_sizes
from helpers.two_dimensions import TwoDimensionProblem, add_pair


def fail_to_generate(
    _random_generator: random.Random,
    size: int,  # noqa: ARG001  signature fixed by the generator contract
) -> list[int]:
    """Fail for every size, as a generator that is broken."""
    message = "generator exploded"
    raise RuntimeError(message)


class ProblemWhoseGeneratorRaises(SortingProblem):
    """Sorting in which the ``reversed`` generator raises for sizes of ``fails_from`` and up."""

    fails_from = 0

    @override
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        def reversed_unless_failing(
            _random_generator: random.Random, size: int
        ) -> list[int]:
            if size >= self.fails_from:
                message = "generator exploded"
                raise RuntimeError(message)
            return list(range(size, 0, -1))

        return tuple(
            InputGenerator(
                generator.name,
                description=generator.description,
                generate=reversed_unless_failing,
            )
            if generator.name == "reversed"
            else generator
            for generator in super().generators()
        )


class ProblemWhoseDefaultGeneratorRaises(SortingProblem):
    """Sorting whose only generator raises."""

    @override
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        return (
            InputGenerator("uniform", description="raises", generate=fail_to_generate),
        )


class ProblemWhoseGeneratorsHookRaises(SortingProblem):
    """Sorting whose generators hook raises."""

    @override
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        message = "generators exploded"
        raise RuntimeError(message)


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


def run_with_failing_reversed_generator(
    behaviors: dict[str, Any], fails_from: int, sizes: tuple[Size, ...]
) -> BenchmarkReport:
    """Benchmark three distributions where ``reversed`` fails to generate from a size on."""
    problem = type(
        "Failing", (ProblemWhoseGeneratorRaises,), {"fails_from": fails_from}
    )()
    report, _, _ = run_fake_benchmark(
        behaviors,
        problem=problem,
        distributions=("uniform", "reversed", "sorted"),
        sizes=sizes,
    )
    return report


@pytest.fixture(scope="module")
def steady_report(tmp_path_factory: pytest.TempPathFactory) -> BenchmarkReport:
    """Two correct implementations run as real processes with two repetitions."""
    directory = tmp_path_factory.mktemp("steady")
    implementations = [
        Implementation.from_executable(write_sorter(directory / name), name=name)
        for name in ("a", "b")
    ]
    return run_benchmark(
        SortingProblem(), implementations, build_settings(repetitions=2)
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"distributions": ("sorted", "uniform", "sorted")},
            r"Distributions.*unique.*sorted",
        ),
        ({"sizes": ()}, "At least one size"),
        ({"sizes": build_sizes(4, 8, 4)}, r"unique.*size=4"),
        ({"repetitions": 0}, "Repetitions"),
        ({"warmup": -1}, "Warmup"),
        ({"timeout_seconds": 0.0}, "Timeout"),
        ({"timeout_seconds": float("nan")}, "Timeout"),
        ({"timeout_seconds": float("inf")}, "Timeout"),
    ],
    ids=[
        "duplicate-distributions",
        "no-sizes",
        "duplicate-sizes",
        "no-repetitions",
        "negative-warmup",
        "zero-timeout",
        "nan-timeout",
        "infinite-timeout",
    ],
)
def test_rejects_invalid_values(overrides: dict[str, object], message: str) -> None:
    """Test settings with an invalid value raise a ValueError naming the value."""
    with pytest.raises(ValueError, match=message):
        build_settings(**overrides)


def test_counts_warmup_and_repetitions_for_every_size_and_the_startup() -> None:
    """Test the total covers warmup and repetitions at every size and at the startup."""
    settings = build_settings(sizes=build_sizes(5, 10, 20), repetitions=3, warmup=2)

    runs = count_total_runs(settings, 2)

    assert runs == 2 * 4 * 5


def test_counting_operations_adds_one_run_per_implementation_distribution_and_size() -> (
    None
):
    """Test counting operations adds one run for each implementation, distribution and size."""
    settings = build_settings(
        sizes=build_sizes(5, 10, 20),
        repetitions=3,
        warmup=2,
        distributions=("uniform", "sorted"),
        count_operations=True,
    )

    runs = count_total_runs(settings, 2)

    assert runs == 2 * (2 * 3 + 1) * 5 + 2 * 2 * 3


def test_every_distribution_is_measured_at_every_size_but_the_startup_only_once() -> (
    None
):
    """Test every distribution runs at every size while the startup runs once."""
    settings = build_settings(
        sizes=build_sizes(5, 10, 20),
        repetitions=3,
        warmup=2,
        distributions=("uniform", "sorted"),
    )

    runs = count_total_runs(settings, 2)

    assert runs == 2 * (2 * 3 + 1) * 5


def test_passes_and_names_the_problem_and_the_implementations(
    steady_report: BenchmarkReport,
) -> None:
    """Test a benchmark of two correct implementations passes and names both."""
    assert steady_report.has_passed
    assert steady_report.problem_name == "sorting"
    assert [item.implementation.name for item in steady_report.implementations] == [
        "a",
        "b",
    ]


def test_measures_the_startup_of_each_implementation(
    steady_report: BenchmarkReport,
) -> None:
    """Test each implementation has no failure and a startup summary of every repetition."""
    for item in steady_report.implementations:
        assert item.failure is None
        assert item.startup is not None
        assert item.startup.count == 2


def test_measures_every_size_with_every_repetition(
    steady_report: BenchmarkReport,
) -> None:
    """Test each size has one measurement whose summary covers every repetition."""
    for item in steady_report.implementations:
        assert [measurement.size for measurement in item.measurements] == list(
            build_sizes(5, 10)
        )
        for measurement in item.measurements:
            assert len(measurement.raw_samples) == 2
            assert measurement.summary.count == 2
            assert measurement.summary.minimum > 0.0
            assert measurement.summary.samples == tuple(sorted(measurement.raw_samples))


def test_names_the_generated_case_of_every_measurement(
    steady_report: BenchmarkReport,
) -> None:
    """Test each measurement names the generated case of its size and the seed."""
    for item in steady_report.implementations:
        for measurement in item.measurements:
            assert (
                measurement.case_identifier
                == f"generated:uniform:{measurement.size}:seed=1"
            )


def test_every_implementation_is_measured_on_the_same_cases(
    steady_report: BenchmarkReport,
) -> None:
    """Test both implementations are measured on the same generated cases."""
    first, second = steady_report.implementations

    assert [measurement.case_identifier for measurement in first.measurements] == [
        measurement.case_identifier for measurement in second.measurements
    ]


def test_rejects_duplicate_names() -> None:
    """Test two implementations with the same name raise a ValueError."""
    with pytest.raises(ValueError, match="Duplicate implementation name"):
        run_benchmark(
            SortingProblem(),
            build_named_implementations("a", "a"),
            build_settings(),
        )


def test_rejects_an_empty_implementation_list() -> None:
    """Test an empty list of implementations raises a ValueError."""
    with pytest.raises(ValueError, match="At least one implementation"):
        run_benchmark(SortingProblem(), [], build_settings())


def test_inputs_come_from_the_default_generator_with_the_settings_seed() -> None:
    """Test the runners receive the inputs of the default generator for the seed and sizes."""
    _, runners, _ = run_fake_benchmark(
        {"a": sort_correctly}, sizes=build_sizes(3, 6), seed=9
    )
    generator = get_default_generator(SortingProblem())

    startup, *sized = runners.collect_inputs_of("a")

    assert startup == []
    assert sized == [
        generate_case(generator, size=Size(size=3), seed=9).input_data,
        generate_case(generator, size=Size(size=6), seed=9).input_data,
    ]


def test_measurements_name_the_cases_of_the_default_generator() -> None:
    """Test each measurement names the generated case of the default generator."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly}, sizes=build_sizes(3, 6), seed=9
    )

    identifiers = [
        measurement.case_identifier
        for measurement in report.implementations[0].measurements
    ]

    assert identifiers == [
        "generated:uniform:size=3:seed=9",
        "generated:uniform:size=6:seed=9",
    ]


def test_every_implementation_receives_identical_inputs() -> None:
    """Test two implementations receive the same inputs in the same order."""
    _, runners, _ = run_fake_benchmark({"a": sort_correctly, "b": sort_correctly})

    assert runners.collect_inputs_of("a") == runners.collect_inputs_of("b")


@pytest.fixture
def flaky_report() -> tuple[BenchmarkReport, FakeRunners]:
    """The report of an implementation that crashes above seven values next to a steady one."""

    def fail_above_seven(values: list[int]) -> list[int]:
        if len(values) > 7:
            return crash(values)
        return sorted(values)

    report, runners, _ = run_fake_benchmark(
        {"flaky": fail_above_seven, "steady": sort_correctly},
        sizes=build_sizes(5, 10, 20),
    )
    return report, runners


def test_a_failure_names_the_size_and_the_error(
    flaky_report: tuple[BenchmarkReport, FakeRunners],
) -> None:
    """Test the failure of an implementation names the size and holds the error output."""
    flaky = flaky_report[0].implementations[0]

    assert flaky.failure is not None
    assert "size=10" in flaky.failure
    assert "kaboom" in flaky.failure


def test_a_failing_implementation_keeps_its_startup_and_earlier_sizes_and_stops(
    flaky_report: tuple[BenchmarkReport, FakeRunners],
) -> None:
    """Test an implementation that fails keeps what it measured and is not run again."""
    report, runners = flaky_report
    flaky = report.implementations[0]

    assert flaky.startup is not None
    assert [measurement.size for measurement in flaky.measurements] == [Size(size=5)]
    # startup, size 5, failed size 10
    assert len(runners.collect_inputs_of("flaky")) == 1 + 1 + 1


def test_a_failing_implementation_does_not_stop_the_others(
    flaky_report: tuple[BenchmarkReport, FakeRunners],
) -> None:
    """Test an implementation next to a failing one is measured at every size."""
    steady = flaky_report[0].implementations[1]

    assert steady.failure is None
    assert [measurement.size for measurement in steady.measurements] == list(
        build_sizes(5, 10, 20)
    )


def test_repetitions_are_interleaved_across_implementations() -> None:
    """Test every measurement point runs all implementations before the next run."""
    settings = build_settings(sizes=build_sizes(5), repetitions=2, warmup=1)
    runners = FakeRunners({"a": sort_correctly, "b": sort_correctly})

    run_benchmark(
        SortingProblem(),
        build_named_implementations("a", "b"),
        settings,
        runner_factory=runners,
    )

    # Per measurement point: warmup of both implementations, then repetitions alternating.
    labels = [name for name, _ in runners.calls]
    assert labels == ["a", "b"] * (len(settings.sizes) + 1) * (
        settings.warmup + settings.repetitions
    )


def test_the_number_of_runs_matches_the_total_and_the_progress() -> None:
    """Test the runs made and the progress reported both equal the planned total of runs."""
    settings = build_settings(sizes=build_sizes(5), repetitions=2, warmup=1)
    runners = FakeRunners({"a": sort_correctly, "b": sort_correctly})
    events: list[BenchmarkProgress] = []

    run_benchmark(
        SortingProblem(),
        build_named_implementations("a", "b"),
        settings,
        runner_factory=runners,
        on_progress=events.append,
    )

    assert len(runners.calls) == count_total_runs(settings, 2)
    assert sum(event.completed for event in events) == count_total_runs(settings, 2)


def test_a_failure_during_startup_leaves_no_measurements() -> None:
    """Test an implementation that fails at startup has no startup, no measurements and a note."""
    report, _, _ = run_fake_benchmark({"crashing": crash, "steady": sort_correctly})

    crashing = report.implementations[0]

    assert crashing.startup is None
    assert crashing.measurements == ()
    assert crashing.failure is not None
    assert "startup" in crashing.failure


def test_a_failure_during_startup_does_not_stop_the_other_implementations() -> None:
    """Test an implementation next to one that fails at startup is measured as usual."""
    report, _, _ = run_fake_benchmark({"crashing": crash, "steady": sort_correctly})

    steady = report.implementations[1]

    assert steady.failure is None
    assert len(steady.measurements) == 2


def test_a_verification_failure_is_recorded() -> None:
    """Test an output that does not verify is recorded as a failure without measurements."""
    report, _, _ = run_fake_benchmark({"unsorted": list}, sizes=build_sizes(50))

    result = report.implementations[0]

    assert result.failure is not None
    assert result.failure.startswith("Verification failed for size=50")
    assert result.measurements == ()


def test_an_exception_in_verification_is_recorded_as_a_failure(
    exploding_problem: SortingProblem,
) -> None:
    """Test a verifier that raises is recorded as a failure that names the exception."""
    report = run_benchmark(
        exploding_problem,
        build_named_implementations("sorter"),
        build_settings(sizes=build_sizes(5)),
        runner_factory=FakeRunners({"sorter": sort_correctly}),
    )

    result = report.implementations[0]

    assert result.failure == (
        "Verification failed for startup: verification raised RuntimeError: verifier exploded"
    )
    assert result.measurements == ()


def test_verification_can_be_disabled() -> None:
    """Test a wrong output is measured and the report passes when verification is off."""
    report, _, _ = run_fake_benchmark(
        {"unsorted": list}, sizes=build_sizes(50), verify_outputs=False
    )

    assert report.has_passed
    assert len(report.implementations[0].measurements) == 1


def test_progress_events_come_in_started_and_completed_pairs_with_the_phase() -> None:
    """Test each run reports a started and a completed event that name its phase and size."""
    _, _, events = run_fake_benchmark(
        {"a": sort_correctly}, sizes=build_sizes(4), repetitions=2, warmup=1
    )

    assert [(event.phase, event.size, event.completed) for event in events] == [
        (BenchmarkPhase.STARTUP, None, False),
        (BenchmarkPhase.STARTUP, None, True),
        (BenchmarkPhase.STARTUP, None, False),
        (BenchmarkPhase.STARTUP, None, True),
        (BenchmarkPhase.STARTUP, None, False),
        (BenchmarkPhase.STARTUP, None, True),
        (BenchmarkPhase.WARMUP, Size(size=4), False),
        (BenchmarkPhase.WARMUP, Size(size=4), True),
        (BenchmarkPhase.MEASUREMENT, Size(size=4), False),
        (BenchmarkPhase.MEASUREMENT, Size(size=4), True),
        (BenchmarkPhase.MEASUREMENT, Size(size=4), False),
        (BenchmarkPhase.MEASUREMENT, Size(size=4), True),
    ]
    assert {event.implementation_name for event in events} == {"a"}


def test_a_failed_run_still_sends_its_completed_event() -> None:
    """Test a run that fails still reports that it completed."""
    _, _, events = run_fake_benchmark({"crash": crash})

    assert [event.completed for event in events] == [False, True]


def test_each_implementation_subtracts_its_own_startup() -> None:
    """Test each implementation has its own mean startup time taken off its samples."""
    report, _, _ = run_fake_benchmark(
        {"fast": sort_correctly, "slow": sort_correctly},
        durations={"fast": 0.010, "slow": 0.300},
        sizes=build_sizes(5),
        repetitions=3,
        subtract_startup_time=True,
    )

    for item in report.implementations:
        assert item.startup is not None
        measurement = item.measurements[0]
        assert measurement.raw_samples == (item.startup.mean,) * 3
        assert measurement.summary.samples == pytest.approx((0.0, 0.0, 0.0))
    fast, slow = (item.startup for item in report.implementations)
    assert fast is not None
    assert slow is not None
    assert fast.mean == pytest.approx(0.010)
    assert slow.mean == pytest.approx(0.300)


def test_samples_are_not_adjusted_without_the_flag() -> None:
    """Test samples keep their raw values when startup subtraction is off."""
    report, _, _ = run_fake_benchmark({"a": sort_correctly}, durations={"a": 0.02})

    for measurement in report.implementations[0].measurements:
        assert measurement.summary.samples == measurement.raw_samples == (0.02,)


@pytest.fixture(scope="module")
def failing_reversed_report() -> BenchmarkReport:
    """The report in which the reversed generator fails for every size."""
    return run_with_failing_reversed_generator(
        {"a": sort_correctly, "b": sort_correctly},
        fails_from=0,
        sizes=build_sizes(5, 10),
    )


def test_the_report_has_not_passed(failing_reversed_report: BenchmarkReport) -> None:
    """Test a generator that fails makes the report fail."""
    assert not failing_reversed_report.has_passed


def test_the_distribution_fails_for_every_implementation(
    failing_reversed_report: BenchmarkReport,
) -> None:
    """Test every implementation records one failure for the distribution without a size."""
    for item in failing_reversed_report.implementations:
        (failure,) = item.failures
        assert (failure.stage, failure.distribution, failure.size) == (
            FailureStage.DISTRIBUTION,
            "reversed",
            None,
        )


def test_the_failure_message_names_the_generator_and_the_cause(
    failing_reversed_report: BenchmarkReport,
) -> None:
    """Test every implementation has the same failure message naming the generator hook."""
    messages = {
        failure.message
        for item in failing_reversed_report.implementations
        for failure in item.failures
    }

    assert messages == {
        (
            "Could not generate the input size=5 for the distribution 'reversed': "
            "The problem's 'reversed' generator hook raised RuntimeError: generator exploded."
        )
    }


def test_the_other_distributions_are_still_measured(
    failing_reversed_report: BenchmarkReport,
) -> None:
    """Test the distributions whose generators work are still measured."""
    for item in failing_reversed_report.implementations:
        assert [(m.distribution, m.size) for m in item.measurements] == [
            ("uniform", Size(size=5)),
            ("uniform", Size(size=10)),
            ("sorted", Size(size=5)),
            ("sorted", Size(size=10)),
        ]
        assert item.startup is not None


def test_the_cells_of_the_failed_distribution_are_failed(
    failing_reversed_report: BenchmarkReport,
) -> None:
    """Test every size of the failed distribution has the status failed."""
    for item in failing_reversed_report.implementations:
        assert item.startup_status() is CellStatus.MEASURED
        assert [item.status_at("reversed", size) for size in build_sizes(5, 10)] == [
            CellStatus.FAILED
        ] * 2
        assert item.status_at("sorted", Size(size=5)) is CellStatus.MEASURED


def test_the_sizes_measured_before_the_failure_stay_and_the_rest_are_failed() -> None:
    """Test sizes measured before a generator fails stay measured and later sizes fail."""
    report = run_with_failing_reversed_generator(
        {"a": sort_correctly}, fails_from=10, sizes=build_sizes(5, 10, 20)
    )
    (item,) = report.implementations

    assert [(m.distribution, m.size) for m in item.measurements_for("reversed")] == [
        ("reversed", Size(size=5))
    ]
    assert [item.status_at("reversed", size) for size in build_sizes(5, 10, 20)] == [
        CellStatus.MEASURED,
        CellStatus.FAILED,
        CellStatus.FAILED,
    ]
    (failure,) = item.failures
    assert "input size=10" in failure.message


def test_an_implementation_that_already_failed_in_the_distribution_keeps_its_own_failure() -> (
    None
):
    """Test an implementation that failed in a distribution keeps its failure, not the generator's."""

    def fails_on_the_first_size(values: list[int]) -> list[int]:
        if values == [5, 4, 3, 2, 1]:
            message = "exited with code 3"
            raise RunnerError(message)
        return sorted(values)

    report = run_with_failing_reversed_generator(
        {"flaky": fails_on_the_first_size, "steady": sort_correctly},
        fails_from=10,
        sizes=build_sizes(5, 10),
    )
    flaky, steady = report.implementations

    assert [(f.stage, f.size) for f in flaky.failures] == [
        (FailureStage.MEASUREMENT, Size(size=5))
    ]
    assert [f.stage for f in steady.failures] == [FailureStage.DISTRIBUTION]
    assert flaky.status_at("reversed", Size(size=10)) is CellStatus.SKIPPED


def test_an_implementation_with_a_failed_startup_gets_no_distribution_failure() -> None:
    """Test an implementation that failed at startup records only the startup failure."""

    def cannot_start(values: list[int]) -> list[int]:
        if not values:
            message = "exited with code 3"
            raise RunnerError(message)
        return sorted(values)

    report = run_with_failing_reversed_generator(
        {"broken": cannot_start, "steady": sort_correctly},
        fails_from=0,
        sizes=build_sizes(5),
    )
    broken, steady = report.implementations

    assert [f.stage for f in broken.failures] == [FailureStage.STARTUP]
    assert [f.stage for f in steady.failures] == [FailureStage.DISTRIBUTION]


def test_a_failed_startup_row_is_not_confused_with_a_failed_distribution() -> None:
    """Test a failed distribution does not make the startup cell failed."""
    report = run_with_failing_reversed_generator(
        {"a": sort_correctly}, fails_from=0, sizes=build_sizes(5)
    )

    status = report.implementations[0].startup_status()

    assert status is CellStatus.MEASURED


def test_the_generator_of_the_startup_input_has_to_work() -> None:
    """Test a default generator that raises stops the benchmark with a HookError."""
    with pytest.raises(HookError, match="'uniform' generator hook raised RuntimeError"):
        run_fake_benchmark(
            {"a": sort_correctly},
            problem=ProblemWhoseDefaultGeneratorRaises(),
            sizes=build_sizes(3),
        )


def test_a_generators_hook_that_raises_is_a_hook_error() -> None:
    """Test a generators hook that raises stops the benchmark with a HookError."""
    with pytest.raises(HookError, match="The problem's generators hook raised"):
        run_fake_benchmark(
            {"a": sort_correctly},
            problem=ProblemWhoseGeneratorsHookRaises(),
            sizes=build_sizes(3),
        )


def test_measurements_carry_the_size_of_every_dimension() -> None:
    """Test a problem with two dimensions is measured at the exact sizes given, in order."""
    sizes = (Size(vertices=2, edges=3), Size(vertices=4, edges=6))
    runners = FakeRunners({"adder": add_pair})

    report = run_benchmark(
        TwoDimensionProblem(),
        build_named_implementations("adder"),
        build_settings(sizes=sizes),
        runner_factory=runners,
    )

    item = report.implementations[0]
    assert [measurement.size for measurement in item.measurements] == list(sizes)
    assert [measurement.case_identifier for measurement in item.measurements] == [
        "generated:exact:vertices=2:edges=3:seed=1",
        "generated:exact:vertices=4:edges=6:seed=1",
    ]
    assert item.measurement_at("exact", Size(edges=6, vertices=4)) is not None
    assert runners.collect_inputs_of("adder") == [(1, 0), (2, 3), (4, 6)]


def test_sizes_that_differ_only_in_order_are_duplicates() -> None:
    """Test two sizes with the same values in another order are the same size."""
    with pytest.raises(ValueError, match=r"unique.*vertices=1:edges=2"):
        build_settings(sizes=(Size(vertices=1, edges=2), Size(edges=2, vertices=1)))


def test_sizes_are_measured_in_the_declared_order_of_their_dimensions() -> None:
    """Test a size given in another order is recorded in the order the problem declares."""
    report = run_benchmark(
        TwoDimensionProblem(),
        build_named_implementations("adder"),
        build_settings(sizes=(Size(edges=3, vertices=2),)),
        runner_factory=FakeRunners({"adder": add_pair}),
    )

    (measurement,) = report.implementations[0].measurements
    assert measurement.case_identifier == "generated:exact:vertices=2:edges=3:seed=1"
    assert str(measurement.size) == "vertices=2:edges=3"
    assert str(report.settings.sizes[0]) == "vertices=2:edges=3"
