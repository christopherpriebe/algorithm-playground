"""Tests for the benchmark engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fakes import (
    FakeRunners,
    TraceFailure,
    crash,
    insertion_sort_trace,
    merge_sort_trace,
    named,
    snapshot_only_trace,
    sort_correctly,
)
from misbehaving import FaultyProblem, distinct_count
from support import WriteSorter

from algorithm_playground.core.benchmarking import (
    BenchmarkFailure,
    BenchmarkPhase,
    BenchmarkProgress,
    BenchmarkReport,
    BenchmarkSettings,
    CellStatus,
    FailureStage,
    ImplementationBenchmark,
    OperationIssueKind,
    SizeMeasurement,
    include_failed_implementations,
    run_benchmark,
    total_runs,
)
from algorithm_playground.core.cases import (
    CaseError,
    InputGenerator,
    default_generator,
    generate_case,
)
from algorithm_playground.core.hooks import HookError
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.runner import RunnerError
from algorithm_playground.core.statistics import summarize
from algorithm_playground.problems.sorting import SortingProblem


def make_settings(**overrides: object) -> BenchmarkSettings:
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


class TestBenchmarkSettings:
    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"distributions": ("sorted", "uniform", "sorted")}, r"Distributions.*unique.*sorted"),
            ({"sizes": ()}, "At least one size"),
            ({"sizes": (5, -1)}, "non-negative"),
            ({"sizes": (4, 8, 4)}, r"unique.*\[4\]"),
            ({"repetitions": 0}, "Repetitions"),
            ({"warmup": -1}, "Warmup"),
            ({"timeout_seconds": 0.0}, "Timeout"),
            ({"timeout_seconds": float("nan")}, "Timeout"),
            ({"timeout_seconds": float("inf")}, "Timeout"),
        ],
    )
    def test_rejects_invalid_values(self, overrides: dict[str, object], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            make_settings(**overrides)


class TestTotalRuns:
    def test_counts_warmup_and_repetitions_for_every_size_and_the_startup(self) -> None:
        settings = make_settings(sizes=(5, 10, 20), repetitions=3, warmup=2)
        assert total_runs(settings, 2) == 2 * 4 * 5

    def test_counting_operations_adds_one_run_per_implementation_distribution_and_size(
        self,
    ) -> None:
        settings = make_settings(
            sizes=(5, 10, 20),
            repetitions=3,
            warmup=2,
            distributions=("uniform", "sorted"),
            count_operations=True,
        )
        assert total_runs(settings, 2) == 2 * (2 * 3 + 1) * 5 + 2 * 2 * 3

    def test_every_distribution_is_measured_at_every_size_but_the_startup_only_once(self) -> None:
        settings = make_settings(
            sizes=(5, 10, 20),
            repetitions=3,
            warmup=2,
            distributions=("uniform", "sorted"),
        )
        assert total_runs(settings, 2) == 2 * (2 * 3 + 1) * 5


@pytest.fixture(scope="module")
def steady_report(
    tmp_path_factory: pytest.TempPathFactory, write_sorter: WriteSorter
) -> BenchmarkReport:
    """Two correct implementations run as real processes with two repetitions."""
    directory = tmp_path_factory.mktemp("steady")
    implementations = [
        Implementation.from_executable(write_sorter(directory / name), name=name)
        for name in ("a", "b")
    ]
    return run_benchmark(SortingProblem(), implementations, make_settings(repetitions=2))


class TestRunBenchmarkWithRealProcesses:
    def test_measures_startup_and_every_size_for_each_implementation(
        self, steady_report: BenchmarkReport
    ) -> None:
        assert steady_report.passed
        assert steady_report.problem_name == "sorting"
        assert [item.implementation.name for item in steady_report.implementations] == ["a", "b"]
        for item in steady_report.implementations:
            assert item.failure is None
            assert item.startup is not None
            assert item.startup.count == 2
            assert [measurement.size for measurement in item.measurements] == [5, 10]
            for measurement in item.measurements:
                assert len(measurement.raw_samples) == 2
                assert measurement.summary.count == 2
                assert measurement.summary.minimum > 0.0
                assert measurement.summary.samples == tuple(sorted(measurement.raw_samples))
                assert (
                    measurement.case_identifier
                    == f"generated:uniform:size={measurement.size}:seed=1"
                )
        first, second = steady_report.implementations
        assert [measurement.case_identifier for measurement in first.measurements] == [
            measurement.case_identifier for measurement in second.measurements
        ]

    def test_rejects_duplicate_names(self) -> None:
        with pytest.raises(ValueError, match="Duplicate implementation name"):
            run_benchmark(SortingProblem(), named("a", "a"), make_settings())

    def test_rejects_an_empty_implementation_list(self) -> None:
        with pytest.raises(ValueError, match="At least one implementation"):
            run_benchmark(SortingProblem(), [], make_settings())


def run_fake_benchmark(
    behaviors: dict[str, Callable[[Any], Any]],
    durations: dict[str, float | Callable[[Any], float]] | None = None,
    *,
    problem: Problem[Any, Any, Any] | None = None,
    **overrides: object,
) -> tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]]:
    runners = FakeRunners(behaviors, durations)
    events: list[BenchmarkProgress] = []
    report = run_benchmark(
        SortingProblem() if problem is None else problem,
        named(*behaviors),
        make_settings(**overrides),
        runner_factory=runners,
        on_progress=events.append,
    )
    return report, runners, events


class TestRunBenchmarkWithFakeRunners:
    def test_inputs_come_from_the_default_generator_with_the_settings_seed(self) -> None:
        report, runners, _ = run_fake_benchmark({"a": sort_correctly}, sizes=(3, 6), seed=9)
        generator = default_generator(SortingProblem())
        startup, *sized = runners.inputs_of("a")
        assert startup == []
        assert sized == [
            generate_case(generator, size=3, seed=9).input_data,
            generate_case(generator, size=6, seed=9).input_data,
        ]
        assert [
            measurement.case_identifier for measurement in report.implementations[0].measurements
        ] == [
            "generated:uniform:size=3:seed=9",
            "generated:uniform:size=6:seed=9",
        ]

    def test_every_implementation_receives_identical_inputs(self) -> None:
        _, runners, _ = run_fake_benchmark({"a": sort_correctly, "b": sort_correctly})
        assert runners.inputs_of("a") == runners.inputs_of("b")

    def test_a_failing_implementation_is_skipped_while_the_others_continue(self) -> None:
        def fail_above_seven(values: list[int]) -> list[int]:
            if len(values) > 7:
                return crash(values)
            return sorted(values)

        report, runners, _ = run_fake_benchmark(
            {"flaky": fail_above_seven, "steady": sort_correctly}, sizes=(5, 10, 20)
        )
        flaky, steady = report.implementations
        assert flaky.failure is not None and "size 10" in flaky.failure
        assert "kaboom" in flaky.failure
        assert flaky.startup is not None
        assert [measurement.size for measurement in flaky.measurements] == [5]
        assert steady.failure is None
        assert [measurement.size for measurement in steady.measurements] == [5, 10, 20]
        assert len(runners.inputs_of("flaky")) == 1 + 1 + 1  # startup, size 5, failed size 10

    def test_repetitions_are_interleaved_across_implementations(self) -> None:
        settings = make_settings(sizes=(5,), repetitions=2, warmup=1)
        runners = FakeRunners({"a": sort_correctly, "b": sort_correctly})
        events: list[BenchmarkProgress] = []
        run_benchmark(
            SortingProblem(),
            named("a", "b"),
            settings,
            runner_factory=runners,
            on_progress=events.append,
        )
        # Per measurement point: warmup of both implementations, then repetitions alternating.
        labels = [name for name, _ in runners.calls]
        assert labels == ["a", "b"] * (len(settings.sizes) + 1) * (
            settings.warmup + settings.repetitions
        )
        assert len(labels) == total_runs(settings, 2)
        assert sum(event.completed for event in events) == total_runs(settings, 2)

    def test_a_failure_during_startup_leaves_no_measurements(self) -> None:
        report, _, _ = run_fake_benchmark({"crashing": crash, "steady": sort_correctly})
        crashing, steady = report.implementations
        assert crashing.startup is None
        assert crashing.measurements == ()
        assert crashing.failure is not None
        assert "startup" in crashing.failure
        assert steady.failure is None
        assert len(steady.measurements) == 2

    def test_a_verification_failure_is_recorded(self) -> None:
        report, _, _ = run_fake_benchmark({"unsorted": list}, sizes=(50,))
        result = report.implementations[0]
        assert result.failure is not None
        assert result.failure.startswith("Verification failed for size 50")
        assert result.measurements == ()

    def test_an_exception_in_verification_is_recorded_as_a_failure(
        self, exploding_problem: SortingProblem
    ) -> None:
        report = run_benchmark(
            exploding_problem,
            named("sorter"),
            make_settings(sizes=(5,)),
            runner_factory=FakeRunners({"sorter": sort_correctly}),
        )
        result = report.implementations[0]
        assert result.failure == (
            "Verification failed for startup: verification raised RuntimeError: verifier exploded"
        )
        assert result.measurements == ()

    def test_verification_can_be_disabled(self) -> None:
        report, _, _ = run_fake_benchmark({"unsorted": list}, sizes=(50,), verify_outputs=False)
        assert report.passed
        assert len(report.implementations[0].measurements) == 1

    def test_progress_events_come_in_started_and_completed_pairs_with_the_phase(self) -> None:
        _, _, events = run_fake_benchmark(
            {"a": sort_correctly}, sizes=(4,), repetitions=2, warmup=1
        )
        assert [(event.phase, event.size, event.completed) for event in events] == [
            (BenchmarkPhase.STARTUP, None, False),
            (BenchmarkPhase.STARTUP, None, True),
            (BenchmarkPhase.STARTUP, None, False),
            (BenchmarkPhase.STARTUP, None, True),
            (BenchmarkPhase.STARTUP, None, False),
            (BenchmarkPhase.STARTUP, None, True),
            (BenchmarkPhase.WARMUP, 4, False),
            (BenchmarkPhase.WARMUP, 4, True),
            (BenchmarkPhase.MEASUREMENT, 4, False),
            (BenchmarkPhase.MEASUREMENT, 4, True),
            (BenchmarkPhase.MEASUREMENT, 4, False),
            (BenchmarkPhase.MEASUREMENT, 4, True),
        ]
        assert {event.implementation_name for event in events} == {"a"}

    def test_a_failed_run_still_sends_its_completed_event(self) -> None:
        _, _, events = run_fake_benchmark({"crash": crash})
        assert [event.completed for event in events] == [False, True]


class TestStartupSubtractionWithFakeRunners:
    def test_each_implementation_subtracts_its_own_startup(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"fast": sort_correctly, "slow": sort_correctly},
            durations={"fast": 0.010, "slow": 0.300},
            sizes=(5,),
            repetitions=3,
            subtract_startup_time=True,
        )
        for item in report.implementations:
            assert item.startup is not None
            measurement = item.measurements[0]
            assert measurement.raw_samples == (item.startup.mean,) * 3
            assert measurement.summary.samples == pytest.approx((0.0, 0.0, 0.0))
        fast, slow = (item.startup for item in report.implementations)
        assert fast is not None and slow is not None
        assert fast.mean == pytest.approx(0.010)
        assert slow.mean == pytest.approx(0.300)

    def test_samples_are_not_adjusted_without_the_flag(self) -> None:
        report, _, _ = run_fake_benchmark({"a": sort_correctly}, durations={"a": 0.02})
        for measurement in report.implementations[0].measurements:
            assert measurement.summary.samples == measurement.raw_samples == (0.02,)


class TestDistributions:
    def test_the_default_generator_alone_is_measured_when_none_is_named(self) -> None:
        report, _, _ = run_fake_benchmark({"a": sort_correctly}, sizes=(3,))
        assert report.settings.distributions == ("uniform",)
        assert [
            measurement.distribution for measurement in report.implementations[0].measurements
        ] == ["uniform"]

    def test_every_named_distribution_is_measured_at_every_size_in_order(self) -> None:
        report, runners, _ = run_fake_benchmark(
            {"a": sort_correctly},
            sizes=(4, 9),
            seed=3,
            distributions=("sorted", "few_unique"),
        )
        assert report.settings.distributions == ("sorted", "few_unique")
        measurements = report.implementations[0].measurements
        assert [(measurement.distribution, measurement.size) for measurement in measurements] == [
            ("sorted", 4),
            ("sorted", 9),
            ("few_unique", 4),
            ("few_unique", 9),
        ]
        assert [measurement.case_identifier for measurement in measurements] == [
            "generated:sorted:size=4:seed=3",
            "generated:sorted:size=9:seed=3",
            "generated:few_unique:size=4:seed=3",
            "generated:few_unique:size=9:seed=3",
        ]
        by_name = {generator.name: generator for generator in SortingProblem().generators()}
        sorted_input = generate_case(by_name["sorted"], size=9, seed=3).input_data
        assert sorted_input == sorted(sorted_input)
        assert sorted_input in runners.inputs_of("a")

    def test_measurements_are_found_by_distribution_and_size(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly}, sizes=(4, 9), distributions=("sorted", "reversed")
        )
        item = report.implementations[0]
        found = item.measurement_at("reversed", 9)
        assert found is not None
        assert (found.distribution, found.size) == ("reversed", 9)
        assert item.measurement_at("reversed", 5) is None
        assert item.measurement_at("uniform", 9) is None
        assert [measurement.size for measurement in item.measurements_for("sorted")] == [4, 9]
        assert item.measurements_for("uniform") == ()

    def test_the_startup_is_measured_once_per_implementation_whatever_the_distributions(
        self,
    ) -> None:
        report, runners, events = run_fake_benchmark(
            {"a": sort_correctly},
            sizes=(4,),
            repetitions=2,
            distributions=("sorted", "reversed", "all_equal"),
        )
        assert [(event.phase, event.distribution) for event in events if event.completed][:2] == [
            (BenchmarkPhase.STARTUP, None)
        ] * 2
        startup_events = [
            event for event in events if event.phase is BenchmarkPhase.STARTUP and event.completed
        ]
        assert len(startup_events) == 2
        assert runners.inputs_of("a")[:2] == [[], []]
        assert report.implementations[0].startup is not None
        assert len(runners.inputs_of("a")) == 2 + 3 * 2

    def test_the_startup_input_has_the_minimum_size_of_the_problem(self) -> None:
        class NeedsTwo(SortingProblem):
            minimum_size = 2

        runners = FakeRunners({"a": sort_correctly})
        run_benchmark(
            NeedsTwo(),
            named("a"),
            make_settings(sizes=(4,), distributions=("reversed",)),
            runner_factory=runners,
        )
        assert len(runners.inputs_of("a")[0]) == 2
        assert len(runners.inputs_of("a")[1]) == 4

    def test_a_size_below_the_minimum_size_of_the_problem_is_an_error(self) -> None:
        class NeedsTwo(SortingProblem):
            minimum_size = 2

        with pytest.raises(CaseError, match="at least 2 elements, but the sizes include 1"):
            run_benchmark(
                NeedsTwo(),
                named("a"),
                make_settings(sizes=(1, 4)),
                runner_factory=FakeRunners({"a": sort_correctly}),
            )

    def test_progress_events_name_the_distribution_of_each_sized_run(self) -> None:
        _, _, events = run_fake_benchmark(
            {"a": sort_correctly}, sizes=(4,), distributions=("sorted", "reversed")
        )
        sized = [
            (event.distribution, event.size)
            for event in events
            if event.size is not None and event.completed
        ]
        assert sized == [("sorted", 4), ("reversed", 4)]

    def test_identical_inputs_reach_every_implementation_in_every_distribution(self) -> None:
        _, runners, _ = run_fake_benchmark(
            {"a": sort_correctly, "b": sort_correctly}, distributions=("sorted", "organ_pipe")
        )
        assert runners.inputs_of("a") == runners.inputs_of("b")

    def test_a_failure_skips_only_the_rest_of_its_distribution(self) -> None:
        def fail_on_sorted_input(values: list[int]) -> list[int]:
            if len(values) > 3 and values == sorted(values):
                return crash(values)
            return sorted(values)

        report, runners, _ = run_fake_benchmark(
            {"picky": fail_on_sorted_input, "steady": sort_correctly},
            sizes=(5, 10),
            distributions=("uniform", "sorted", "reversed"),
        )
        picky, steady = report.implementations
        assert picky.failure is not None and "size 5 (sorted)" in picky.failure
        assert [(item.stage, item.distribution, item.size) for item in picky.failures] == [
            (FailureStage.MEASUREMENT, "sorted", 5)
        ]
        assert [
            (measurement.distribution, measurement.size) for measurement in picky.measurements
        ] == [
            ("uniform", 5),
            ("uniform", 10),
            ("reversed", 5),
            ("reversed", 10),
        ]
        assert [measurement.distribution for measurement in steady.measurements] == [
            "uniform",
            "uniform",
            "sorted",
            "sorted",
            "reversed",
            "reversed",
        ]
        # startup, uniform x2, the failed sorted run, reversed x2: nothing ran for sorted size 10
        assert len(runners.inputs_of("picky")) == 1 + 2 + 1 + 2

    def test_cells_after_a_failure_are_skipped_and_the_failed_cell_is_failed(self) -> None:
        def fail_on_sorted_input(values: list[int]) -> list[int]:
            return crash(values) if len(values) > 3 and values == sorted(values) else sorted(values)

        report, _, _ = run_fake_benchmark(
            {"picky": fail_on_sorted_input},
            sizes=(5, 10),
            distributions=("uniform", "sorted", "reversed"),
        )
        picky = report.implementations[0]
        assert picky.startup_status() is CellStatus.MEASURED
        assert [
            picky.status_at(distribution, size)
            for distribution in ("uniform", "sorted", "reversed")
            for size in (5, 10)
        ] == [
            CellStatus.MEASURED,
            CellStatus.MEASURED,
            CellStatus.FAILED,
            CellStatus.SKIPPED,
            CellStatus.MEASURED,
            CellStatus.MEASURED,
        ]

    def test_a_startup_failure_fails_the_startup_cell_and_skips_every_size(self) -> None:
        report, runners, _ = run_fake_benchmark(
            {"crashing": crash, "steady": sort_correctly}, distributions=("uniform", "sorted")
        )
        crashing = report.implementations[0]
        assert crashing.failures[0].stage is FailureStage.STARTUP
        assert crashing.startup_status() is CellStatus.FAILED
        assert crashing.status_at("sorted", 5) is CellStatus.SKIPPED
        assert len(runners.inputs_of("crashing")) == 1

    def test_a_failed_build_fails_every_cell(self) -> None:
        report, _, _ = run_fake_benchmark({"steady": sort_correctly})
        completed = include_failed_implementations(
            report,
            named("steady", "unbuilt"),
            {"unbuilt": BenchmarkFailure(FailureStage.BUILD, "make: error")},
        )
        unbuilt = completed.implementations[1]
        assert [(item.stage, item.message) for item in unbuilt.failures] == [
            (FailureStage.BUILD, "make: error")
        ]
        assert unbuilt.startup_status() is CellStatus.FAILED
        assert unbuilt.status_at("uniform", 5) is CellStatus.FAILED
        assert not completed.passed

    def test_an_implementation_that_cannot_run_fails_every_cell_like_a_failed_build(self) -> None:
        report, _, _ = run_fake_benchmark({"steady": sort_correctly})
        completed = include_failed_implementations(
            report,
            named("steady", "missing"),
            {"missing": BenchmarkFailure(FailureStage.CANNOT_RUN, "Cannot run: not found")},
        )
        missing = completed.implementations[1]
        assert missing.failures[0].stage is FailureStage.CANNOT_RUN
        assert missing.startup_status() is CellStatus.FAILED
        assert missing.status_at("uniform", 5) is CellStatus.FAILED

    def test_a_run_that_cannot_write_the_input_fails_that_implementation_and_distribution(
        self,
    ) -> None:
        def cannot_serialize(values: list[int]) -> list[int]:
            if values and values == sorted(values):
                raise RunnerError("The problem's serialize_input hook could not write the input")
            return sorted(values)

        report, _, _ = run_fake_benchmark(
            {"a": cannot_serialize}, sizes=(5,), distributions=("sorted", "reversed")
        )
        item = report.implementations[0]
        assert item.failure is not None and "serialize_input" in item.failure
        assert [measurement.distribution for measurement in item.measurements] == ["reversed"]

    def test_an_unknown_distribution_is_an_error_naming_the_available_ones(self) -> None:
        with pytest.raises(
            CaseError, match=r"Unknown distribution 'nope'.*uniform.*median_of_three"
        ):
            run_fake_benchmark({"a": sort_correctly}, distributions=("nope",))


def quadratic_seconds(values: list[int]) -> float:
    return 0.01 + 1e-7 * len(values) ** 2


class TestGrowth:
    SIZES = (100, 200, 400, 800)

    def test_it_follows_the_work_when_the_startup_is_subtracted(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly},
            durations={"a": quadratic_seconds},
            sizes=self.SIZES,
            subtract_startup_time=True,
        )
        growth = report.implementations[0].growth("uniform")
        assert growth is not None
        assert growth.exponent == pytest.approx(2.0)
        assert growth.growth_class == "n^2"

    def test_the_startup_is_excluded_even_when_it_is_not_subtracted(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly}, durations={"a": quadratic_seconds}, sizes=self.SIZES
        )
        growth = report.implementations[0].growth("uniform")
        assert growth is not None
        assert growth.exponent == pytest.approx(2.0, abs=0.05)
        assert growth.growth_class == "n^2"

    def test_it_is_estimated_for_each_distribution_separately(self) -> None:
        def duration(values: list[int]) -> float:
            return 1e-6 * len(values) * (len(set(values)) if len(values) > 1 else 1)

        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly},
            durations={"a": duration},
            sizes=self.SIZES,
            distributions=("all_equal", "sorted"),
        )
        item = report.implementations[0]
        all_equal, sorted_growth = item.growth("all_equal"), item.growth("sorted")
        assert all_equal is not None and sorted_growth is not None
        assert all_equal.exponent == pytest.approx(1.0)
        assert all_equal.growth_class == "n"
        assert sorted_growth.exponent == pytest.approx(2.0, abs=0.01)
        assert sorted_growth.growth_class == "n^2"

    def test_the_startup_median_is_subtracted_not_the_mean(self) -> None:
        startup = summarize([0.01, 0.01, 0.01, 0.01, 0.21])
        assert startup.median == pytest.approx(0.01) and startup.mean == pytest.approx(0.05)
        measurements = tuple(
            SizeMeasurement(
                distribution="uniform",
                size=size,
                case_identifier=f"generated:uniform:size={size}:seed=0",
                raw_samples=(0.01 + 1e-5 * size,) * 3,
                summary=summarize([0.01 + 1e-5 * size] * 3),
            )
            for size in self.SIZES
        )
        item = ImplementationBenchmark(
            implementation=named("a")[0], startup=startup, measurements=measurements
        )
        growth = item.growth("uniform")
        assert growth is not None
        assert growth.exponent == pytest.approx(1.0)
        assert growth.growth_class == "n"

    def test_there_is_none_with_fewer_than_three_sizes(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly}, durations={"a": quadratic_seconds}, sizes=(100, 200)
        )
        assert report.implementations[0].growth("uniform") is None

    def test_there_is_none_for_a_distribution_that_was_not_measured(self) -> None:
        report, _, _ = run_fake_benchmark({"a": sort_correctly}, sizes=self.SIZES)
        assert report.implementations[0].growth("sorted") is None


def exploding_generator(random_generator: Any, size: int) -> list[int]:
    raise RuntimeError("generator exploded")


class ProblemWhoseGeneratorRaises(SortingProblem):
    """Sorting in which the ``reversed`` generator raises for sizes of ``fails_from`` and up."""

    fails_from = 0

    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        def reversed_unless_failing(random_generator: Any, size: int) -> list[int]:
            if size >= self.fails_from:
                raise RuntimeError("generator exploded")
            return list(range(size, 0, -1))

        return tuple(
            InputGenerator(generator.name, generator.description, reversed_unless_failing)
            if generator.name == "reversed"
            else generator
            for generator in super().generators()
        )


class ProblemWhoseDefaultGeneratorRaises(SortingProblem):
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        return (InputGenerator("uniform", "raises", exploding_generator),)


class ProblemWhoseGeneratorsHookRaises(SortingProblem):
    def generators(self) -> tuple[InputGenerator[list[int]], ...]:
        raise RuntimeError("generators exploded")


class TestGeneratorsThatRaise:
    DISTRIBUTIONS = ("uniform", "reversed", "sorted")

    def run_with_failing_reversed(
        self, behaviors: dict[str, Any], fails_from: int, sizes: tuple[int, ...]
    ) -> BenchmarkReport:
        problem = type("Failing", (ProblemWhoseGeneratorRaises,), {"fails_from": fails_from})()
        report, _, _ = run_fake_benchmark(
            behaviors, problem=problem, distributions=self.DISTRIBUTIONS, sizes=sizes
        )
        return report

    def test_the_distribution_fails_for_every_implementation_and_the_others_still_run(
        self,
    ) -> None:
        report = self.run_with_failing_reversed(
            {"a": sort_correctly, "b": sort_correctly}, fails_from=0, sizes=(5, 10)
        )
        assert not report.passed
        messages = set()
        for item in report.implementations:
            (failure,) = item.failures
            assert (failure.stage, failure.distribution, failure.size) == (
                FailureStage.DISTRIBUTION,
                "reversed",
                None,
            )
            messages.add(failure.message)
            assert [(m.distribution, m.size) for m in item.measurements] == [
                ("uniform", 5),
                ("uniform", 10),
                ("sorted", 5),
                ("sorted", 10),
            ]
            assert item.startup is not None
            assert item.startup_status() is CellStatus.MEASURED
            assert [item.status_at("reversed", size) for size in (5, 10)] == [CellStatus.FAILED] * 2
            assert item.status_at("sorted", 5) is CellStatus.MEASURED
        assert len(messages) == 1
        (message,) = messages
        assert message == (
            "Could not generate the input of size 5 for the distribution 'reversed': "
            "The problem's 'reversed' generator hook raised RuntimeError: generator exploded."
        )

    def test_the_sizes_measured_before_the_failure_stay_and_the_rest_are_failed(self) -> None:
        report = self.run_with_failing_reversed(
            {"a": sort_correctly}, fails_from=10, sizes=(5, 10, 20)
        )
        (item,) = report.implementations
        assert [(m.distribution, m.size) for m in item.measurements_for("reversed")] == [
            ("reversed", 5)
        ]
        assert [item.status_at("reversed", size) for size in (5, 10, 20)] == [
            CellStatus.MEASURED,
            CellStatus.FAILED,
            CellStatus.FAILED,
        ]
        (failure,) = item.failures
        assert "input of size 10" in failure.message

    def test_an_implementation_that_already_failed_in_the_distribution_keeps_its_own_failure(
        self,
    ) -> None:
        def fails_on_the_first_size(values: list[int]) -> list[int]:
            if values == [5, 4, 3, 2, 1]:
                raise RunnerError("exited with code 3")
            return sorted(values)

        report = self.run_with_failing_reversed(
            {"flaky": fails_on_the_first_size, "steady": sort_correctly},
            fails_from=10,
            sizes=(5, 10),
        )
        flaky, steady = report.implementations
        assert [(f.stage, f.size) for f in flaky.failures] == [(FailureStage.MEASUREMENT, 5)]
        assert [f.stage for f in steady.failures] == [FailureStage.DISTRIBUTION]
        assert flaky.status_at("reversed", 10) is CellStatus.SKIPPED

    def test_an_implementation_with_a_failed_startup_gets_no_distribution_failure(self) -> None:
        def cannot_start(values: list[int]) -> list[int]:
            if not values:
                raise RunnerError("exited with code 3")
            return sorted(values)

        report = self.run_with_failing_reversed(
            {"broken": cannot_start, "steady": sort_correctly}, fails_from=0, sizes=(5,)
        )
        broken, steady = report.implementations
        assert [f.stage for f in broken.failures] == [FailureStage.STARTUP]
        assert [f.stage for f in steady.failures] == [FailureStage.DISTRIBUTION]

    def test_a_failed_startup_row_is_not_confused_with_a_failed_distribution(self) -> None:
        report = self.run_with_failing_reversed({"a": sort_correctly}, fails_from=0, sizes=(5,))
        assert report.implementations[0].startup_status() is CellStatus.MEASURED

    def test_the_generator_of_the_startup_input_has_to_work(self) -> None:
        with pytest.raises(HookError, match="'uniform' generator hook raised RuntimeError"):
            run_fake_benchmark(
                {"a": sort_correctly}, problem=ProblemWhoseDefaultGeneratorRaises(), sizes=(3,)
            )

    def test_a_generators_hook_that_raises_is_a_hook_error(self) -> None:
        with pytest.raises(HookError, match="The problem's generators hook raised"):
            run_fake_benchmark(
                {"a": sort_correctly}, problem=ProblemWhoseGeneratorsHookRaises(), sizes=(3,)
            )


class TestOperationCountsWithoutATraceFormat:
    def test_no_counting_run_is_made_and_the_settings_say_so(self) -> None:
        report, runners, events = run_fake_benchmark(
            {"a": distinct_count}, problem=FaultyProblem(), sizes=(3, 6), count_operations=True
        )
        assert report.passed
        assert report.settings.count_operations is False
        assert runners.traced_calls == []
        assert BenchmarkPhase.OPERATION_COUNT not in {event.phase for event in events}
        for measurement in report.implementations[0].measurements:
            assert measurement.operation_counts is None
            assert measurement.operation_issue is None

    def test_a_problem_with_a_trace_format_keeps_counting(self) -> None:
        report, runners, _ = run_fake_benchmark(
            {"a": sort_correctly}, sizes=(3, 6), count_operations=True
        )
        assert report.settings.count_operations is True
        assert runners.traced_calls == ["a", "a"]


class TestGrowthReliability:
    SIZES = (100, 200, 400, 800)

    def test_work_well_above_the_startup_is_reliable(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly},
            durations={"a": quadratic_seconds},
            sizes=(1000, 2000, 4000, 8000),
            repetitions=3,
        )
        assert report.implementations[0].growth_is_reliable("uniform")

    def test_medians_within_the_noise_of_the_startup_are_not(self) -> None:
        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly},
            durations={"a": lambda values: 0.01 + 1e-9 * len(values)},
            sizes=self.SIZES,
        )
        item = report.implementations[0]
        assert item.growth("uniform") is not None
        assert not item.growth_is_reliable("uniform")

    def test_only_sizes_clearly_above_the_startup_count(self) -> None:
        def duration(values: list[int]) -> float:
            return 0.01 if len(values) < 400 else 0.05

        report, _, _ = run_fake_benchmark(
            {"a": sort_correctly}, durations={"a": duration}, sizes=self.SIZES
        )
        assert not report.implementations[0].growth_is_reliable("uniform")

    def test_without_a_startup_measurement_there_is_nothing_to_doubt(self) -> None:
        report, _, _ = run_fake_benchmark({"a": crash})
        assert report.implementations[0].growth_is_reliable("uniform")


def run_counting_benchmark(
    traces: dict[str, Callable[[list[int]], object]],
    **overrides: object,
) -> tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]]:
    behaviors = dict.fromkeys(traces, sort_correctly)
    runners = FakeRunners(behaviors, traces=traces)
    events: list[BenchmarkProgress] = []
    settings = make_settings(count_operations=True, sizes=(8, 16, 32, 64), **overrides)
    report = run_benchmark(
        SortingProblem(),
        named(*behaviors),
        settings,
        runner_factory=runners,
        on_progress=events.append,
    )
    return report, runners, events


class TestOperationCounting:
    def test_counts_are_recorded_per_implementation_distribution_and_size(self) -> None:
        report, _, _ = run_counting_benchmark(
            {"insertion": insertion_sort_trace, "merge": merge_sort_trace},
            distributions=("reversed", "sorted"),
        )
        insertion = report.implementations[0]
        reversed_counts = [
            measurement.operation_counts for measurement in insertion.measurements_for("reversed")
        ]
        assert reversed_counts == [
            {"compares": size * (size - 1) // 2, "swaps": size * (size - 1) // 2, "writes": 0}
            for size in (8, 16, 32, 64)
        ]
        sorted_counts = [
            measurement.operation_counts for measurement in insertion.measurements_for("sorted")
        ]
        assert sorted_counts == [
            {"compares": size - 1, "swaps": 0, "writes": 0} for size in (8, 16, 32, 64)
        ]
        merge = report.implementations[1].measurement_at("sorted", 8)
        assert merge is not None and merge.operation_counts is not None
        assert merge.operation_counts["swaps"] == 0
        assert merge.operation_counts["writes"] > 0

    def test_each_point_gets_one_extra_traced_run_and_the_timed_runs_carry_no_trace(self) -> None:
        _, runners, _ = run_counting_benchmark({"a": insertion_sort_trace}, repetitions=2, warmup=1)
        assert runners.traced_calls == ["a"] * 4
        timed = len(runners.calls) - len(runners.traced_calls)
        assert timed == (1 + 4) * 3

    def test_the_traced_run_uses_the_input_of_the_timed_runs(self) -> None:
        _, runners, _ = run_counting_benchmark({"a": insertion_sort_trace}, repetitions=1)
        _, *sized = runners.inputs_of("a")
        assert sized[0::2] == sized[1::2]

    def test_nothing_is_counted_when_the_setting_is_off(self) -> None:
        runners = FakeRunners({"a": sort_correctly}, traces={"a": insertion_sort_trace})
        report = run_benchmark(
            SortingProblem(), named("a"), make_settings(), runner_factory=runners
        )
        assert runners.traced_calls == []
        assert all(
            measurement.operation_counts is None
            for measurement in report.implementations[0].measurements
        )
        assert report.implementations[0].operation_names() == ()

    def test_an_implementation_without_a_trace_has_no_counts_while_the_others_do(self) -> None:
        report, _, _ = run_counting_benchmark(
            {"traced": insertion_sort_trace, "silent": lambda values: None}
        )
        traced, silent = report.implementations
        assert all(measurement.operation_counts is not None for measurement in traced.measurements)
        assert all(measurement.operation_counts is None for measurement in silent.measurements)
        assert silent.failure is None
        assert silent.operation_growth("uniform") == {}

    def test_a_trace_with_snapshots_only_reports_no_counts(self) -> None:
        report, _, _ = run_counting_benchmark({"a": snapshot_only_trace})
        assert all(
            measurement.operation_counts is None
            for measurement in report.implementations[0].measurements
        )

    def test_a_malformed_trace_is_recorded_on_the_measurement(self) -> None:
        report, _, _ = run_counting_benchmark(
            {
                "broken": lambda values: TraceFailure("Unsupported trace kind: 7"),
                "fine": insertion_sort_trace,
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

    def test_counts_come_only_from_a_traced_run_whose_output_verifies(self) -> None:
        runners = FakeRunners(
            {"a": sort_correctly},
            traces={"a": insertion_sort_trace},
            traced_behaviors={"a": lambda values: sorted(values)[:-1]},
        )
        report = run_benchmark(
            SortingProblem(),
            named("a"),
            make_settings(count_operations=True, sizes=(8, 16)),
            runner_factory=runners,
        )
        item = report.implementations[0]
        assert item.failure is None
        for measurement in item.measurements:
            assert measurement.operation_counts is None
            assert measurement.operation_issue is not None
            assert measurement.operation_issue.kind is OperationIssueKind.UNVERIFIED_OUTPUT
            assert "does not match input length" in measurement.operation_issue.message

    def test_counts_are_read_from_an_unverified_output_when_verification_is_off(self) -> None:
        runners = FakeRunners(
            {"a": sort_correctly},
            traces={"a": insertion_sort_trace},
            traced_behaviors={"a": lambda values: []},
        )
        report = run_benchmark(
            SortingProblem(),
            named("a"),
            make_settings(count_operations=True, verify_outputs=False, sizes=(8,)),
            runner_factory=runners,
        )
        measurement = report.implementations[0].measurements[0]
        assert measurement.operation_counts is not None
        assert measurement.operation_issue is None

    def test_a_failed_traced_run_fails_the_implementation_but_keeps_its_timings(self) -> None:
        def fail_for_large(values: list[int]) -> object:
            if len(values) > 16:
                raise RunnerError("could not write the trace")
            return insertion_sort_trace(values)

        report, _, _ = run_counting_benchmark({"a": fail_for_large, "b": insertion_sort_trace})
        failed, healthy = report.implementations
        assert failed.failure is not None
        assert "Run failed for size 32 (uniform) while counting operations" in failed.failure
        assert [measurement.size for measurement in failed.measurements] == [8, 16, 32]
        assert failed.measurements[-1].operation_counts is None
        issue = failed.measurements[-1].operation_issue
        assert issue is not None and issue.kind is OperationIssueKind.COUNTING_FAILED
        assert failed.status_at("uniform", 32) is CellStatus.MEASURED
        assert failed.status_at("uniform", 64) is CellStatus.SKIPPED
        assert [measurement.size for measurement in healthy.measurements] == [8, 16, 32, 64]

    def test_an_exception_while_counting_is_recorded_as_a_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(
            self: SortingProblem, input_data: object, output: object, trace: object
        ) -> None:
            raise RuntimeError("counting exploded")

        monkeypatch.setattr(SortingProblem, "operation_counts", explode)
        report, _, _ = run_counting_benchmark({"a": insertion_sort_trace})
        failure = report.implementations[0].failure
        assert failure is not None
        assert "operation_counts raised RuntimeError: counting exploded" in failure

    def test_progress_events_announce_each_counting_run(self) -> None:
        _, _, events = run_counting_benchmark(
            {"a": insertion_sort_trace}, distributions=("sorted",)
        )
        counting = [event for event in events if event.phase is BenchmarkPhase.OPERATION_COUNT]
        assert [(event.size, event.completed, event.distribution) for event in counting] == [
            (size, completed, "sorted") for size in (8, 16, 32, 64) for completed in (False, True)
        ]

    def test_compare_counts_grow_quadratically_for_insertion_and_linearithmically_for_merge(
        self,
    ) -> None:
        report, _, _ = run_counting_benchmark(
            {"insertion": insertion_sort_trace, "merge": merge_sort_trace},
            distributions=("reversed",),
        )
        insertion, merge = (
            benchmark.operation_growth("reversed")["compares"]
            for benchmark in report.implementations
        )
        assert insertion is not None and merge is not None
        assert insertion.exponent == pytest.approx(2.0, abs=0.2)
        assert insertion.growth_class == "n^2"
        assert 1.0 < merge.exponent < 1.4
        assert merge.growth_class == "n log n"

    def test_a_count_that_is_always_zero_has_no_growth_estimate(self) -> None:
        report, _, _ = run_counting_benchmark(
            {"insertion": insertion_sort_trace}, distributions=("sorted",)
        )
        growths = report.implementations[0].operation_growth("sorted")
        compares = growths["compares"]
        assert compares is not None and compares.exponent == pytest.approx(1.0, abs=0.1)
        assert growths["swaps"] is None and growths["writes"] is None

    def test_operation_names_follow_first_appearance(self) -> None:
        report, _, _ = run_counting_benchmark({"a": insertion_sort_trace})
        assert report.implementations[0].operation_names() == ("compares", "swaps", "writes")
