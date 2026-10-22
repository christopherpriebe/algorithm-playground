"""Benchmark engine: time several implementations on identical, seeded inputs.

For every size the engine runs the warmup iterations of each implementation
first, then interleaves the measured repetitions round-robin (repetition 1 of
every implementation, repetition 2 of every implementation, and so on) so
that drift in system load affects all implementations equally. Each
implementation also gets its own startup measurement on the problem's
startup case (the default generator at the problem's minimum size), once
per implementation however many distributions are measured. Inputs come from
the problem's generators, called distributions here: the settings name them,
and the default generator alone is used when they name none. Every
distribution is measured at every size with the settings' seed, so all
implementations see identical inputs. With the ``count_operations`` setting
every implementation also gets one untimed run per distribution and size with
a trace path, from which the problem's ``operation_counts`` are read; the
counts are only taken from a run whose output verifies (when verification is
on) and whose trace is well formed, and a measurement records why it has none.
An implementation that fails is recorded and skipped for the rest of that
distribution (or for everything when its startup run fails) while the others
continue and its later distributions still run. A generator of the problem
that raises fails its distribution for every implementation at once, and the
other distributions still run; the startup input and the problem's
``generators`` hook have to work, because nothing can be measured without
them. The growth of the median time with the problem's growth dimension is reported with its
best-fitting class, and judged unreliable when the medians are too close to the
startup median (see :meth:`ImplementationBenchmark.is_growth_reliable`). The
engine never prints, and runs go through a runner factory that tests replace
with an in-process fake.
"""

import math
import statistics
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum

from algorithm_playground.core._cases import (
    AnyCase,
    AnyInputGenerator,
    build_startup_case,
    check_sizes,
    generate_case,
    get_default_generator,
    select_generators,
)
from algorithm_playground.core._description import describe_error
from algorithm_playground.core._dimensions import (
    Dimension,
    Size,
    build_minimum_size,
    get_growth_dimension,
)
from algorithm_playground.core._hooks import HookError
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._problem import AnyProblem, has_trace_format
from algorithm_playground.core._runner import (
    RunnerError,
    RunnerFactory,
    RunResult,
    build_subprocess_runner_factory,
)
from algorithm_playground.core._statistics import (
    MINIMUM_GROWTH_POINTS,
    Growth,
    TimingSummary,
    estimate_growth,
    subtract_startup,
    summarize,
)
from algorithm_playground.core._support import validate_implementations

__all__ = [
    "MINIMUM_NOISE_FRACTION",
    "NOISE_STANDARD_DEVIATIONS",
    "BenchmarkFailure",
    "BenchmarkPhase",
    "BenchmarkProgress",
    "BenchmarkReport",
    "BenchmarkSettings",
    "CellStatus",
    "FailureStage",
    "ImplementationBenchmark",
    "OperationIssue",
    "OperationIssueKind",
    "SizeMeasurement",
    "count_total_runs",
    "include_failed_implementations",
    "run_benchmark",
]

# A run is clearly slower than an empty-input run when it exceeds the startup median by
# this many standard deviations of the startup samples, and by at least this fraction of it.
NOISE_STANDARD_DEVIATIONS = 3.0
MINIMUM_NOISE_FRACTION = 0.1


def _list_repeated(values: Sequence[str]) -> list[str]:
    """List the values that occur more than once, in first-seen order.

    Args:
        values: The values to check.

    Returns:
        Each repeated value once.
    """
    return [value for value in dict.fromkeys(values) if values.count(value) > 1]


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSettings:
    """The parameters of a benchmark run.

    ``distributions`` names the generators to measure; empty means the
    problem's default generator only. :func:`run_benchmark` returns a report
    whose settings always list the distributions it measured.
    ``count_operations`` adds the untimed counting run described in the module
    documentation; it has no effect for a problem without a trace format, and
    the report's settings then say so by holding ``False``.
    """

    seed: int
    sizes: tuple[Size, ...]
    repetitions: int
    warmup: int
    timeout_seconds: float
    verify_outputs: bool
    subtract_startup_time: bool
    distributions: tuple[str, ...] = ()
    count_operations: bool = False

    def __post_init__(self) -> None:
        if not self.sizes:
            message = "At least one size is required"
            raise ValueError(message)
        repeated_sizes = [
            str(size)
            for size in dict.fromkeys(self.sizes)
            if self.sizes.count(size) > 1
        ]
        if repeated_sizes:
            message = f"Sizes must be unique, but these were repeated: {', '.join(repeated_sizes)}"
            raise ValueError(message)
        repeated_distributions = sorted(_list_repeated(self.distributions))
        if repeated_distributions:
            message = f"Distributions must be unique, but these were repeated: {repeated_distributions}"
            raise ValueError(message)
        if self.repetitions < 1:
            message = f"Repetitions must be at least 1, got {self.repetitions}"
            raise ValueError(message)
        if self.warmup < 0:
            message = f"Warmup must be non-negative, got {self.warmup}"
            raise ValueError(message)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            message = (
                f"Timeout must be a finite positive number, got {self.timeout_seconds}"
            )
            raise ValueError(message)


class BenchmarkPhase(Enum):
    """Which part of a benchmark a run belongs to."""

    STARTUP = "startup"
    WARMUP = "warmup"
    MEASUREMENT = "measurement"
    OPERATION_COUNT = "operation count"


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkProgress:
    """A progress event: one run of one implementation is starting or has ended.

    ``size`` and ``distribution`` are ``None`` for the startup measurement.
    ``completed`` is false when the run is about to start and true after it
    ended, whether or not it succeeded; exactly one completed event is sent per
    attempted run.
    """

    implementation_name: str
    phase: BenchmarkPhase
    size: Size | None
    completed: bool
    distribution: str | None = None


class OperationIssueKind(Enum):
    """Why a measurement has no operation counts although counting was on."""

    MALFORMED_TRACE = "malformed trace"
    UNVERIFIED_OUTPUT = "output did not verify"
    COUNTING_FAILED = "counting failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationIssue:
    """The reason an implementation reported no operation counts at one size."""

    kind: OperationIssueKind
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SizeMeasurement:
    """One implementation's timings at one input size of one distribution.

    ``case_identifier`` names the generated input, the same for every
    implementation. ``summary`` describes the reported samples (startup
    subtracted when the settings ask for it); ``raw_samples`` always holds the
    unadjusted wall times in run order. ``operation_counts`` maps the problem's
    operation names to how often the implementation did them; it is ``None``
    when counting was off or the implementation reported nothing, and
    ``operation_issue`` then says why when there was a reason other than the
    implementation writing no trace. ``scores`` holds the score that the
    problem's ``verify`` gave the output of each verified timed repetition, in
    run order; it is empty when verification was off or the verifier gave no
    score. The counting run does not contribute.
    """

    distribution: str
    size: Size
    case_identifier: str
    raw_samples: tuple[float, ...]
    summary: TimingSummary
    operation_counts: Mapping[str, int] | None = None
    operation_issue: OperationIssue | None = None
    scores: tuple[float, ...] = ()


class FailureStage(Enum):
    """Where in a benchmark an implementation failed.

    ``BUILD`` and ``CANNOT_RUN`` (the command cannot be started) happen before
    any measurement and affect every cell of the implementation. ``DISTRIBUTION``
    is a failure of the problem, not of the implementation: the problem's
    generator raised, so no implementation could run that distribution from
    there on; every implementation records it.
    """

    BUILD = "build"
    CANNOT_RUN = "cannot run"
    STARTUP = "startup"
    MEASUREMENT = "measurement"
    DISTRIBUTION = "distribution"

    @property
    def is_before_measurement(self) -> bool:
        """Whether the implementation never got to run because of this failure."""
        return self in (FailureStage.BUILD, FailureStage.CANNOT_RUN)

    @property
    def is_distribution_specific(self) -> bool:
        """Whether the failure affects one distribution and leaves the others and the startup."""
        return self in (FailureStage.MEASUREMENT, FailureStage.DISTRIBUTION)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkFailure:
    """Why an implementation stopped measuring.

    A ``MEASUREMENT`` failure names the ``distribution`` and ``size`` it
    happened at; the implementation's remaining sizes of that distribution
    are skipped, and its other distributions still run. A ``DISTRIBUTION``
    failure names the ``distribution`` whose generator raised, and no size:
    every size that was not measured before it failed. A build or startup
    failure has neither and affects every distribution.
    """

    stage: FailureStage
    message: str
    distribution: str | None = None
    size: Size | None = None


class CellStatus(Enum):
    """What became of one table cell of an implementation."""

    MEASURED = "measured"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True, kw_only=True)
class ImplementationBenchmark:
    """Everything measured for one implementation.

    ``failures`` lists what went wrong, in the order it happened; ``startup``
    and ``measurements`` hold whatever completed. ``growth_dimension`` names
    the dimension of the size that the growth is fitted against.
    """

    implementation: Implementation
    startup: TimingSummary | None
    measurements: tuple[SizeMeasurement, ...]
    failures: tuple[BenchmarkFailure, ...] = ()
    growth_dimension: str = "size"

    @property
    def failure(self) -> str | None:
        """The message of the first failure, or ``None`` when there was none."""
        return self.failures[0].message if self.failures else None

    def startup_status(self) -> CellStatus:
        """Say what became of the startup row of this implementation.

        Returns:
            Whether the startup row was measured, failed, or skipped.
        """
        if self.startup is not None:
            return CellStatus.MEASURED
        for failure in self.failures:
            if not failure.stage.is_distribution_specific:
                return CellStatus.FAILED
        return CellStatus.SKIPPED

    def status_at(self, distribution: str, size: Size) -> CellStatus:
        """Say what became of the cell for a distribution and size.

        A size that was never reached because of an earlier failure is
        ``SKIPPED``; the size at which the failure happened is ``FAILED``, and
        so is every size of an implementation whose build failed or that cannot
        run, and every size of a distribution whose generator raised.

        Args:
            distribution: The name of the distribution.
            size: The input size.

        Returns:
            The status of the cell.
        """
        if self.measurement_at(distribution, size) is not None:
            return CellStatus.MEASURED
        for failure in self.failures:
            if failure.stage.is_before_measurement:
                return CellStatus.FAILED
            if failure.distribution != distribution:
                continue
            if failure.stage is FailureStage.DISTRIBUTION:
                return CellStatus.FAILED
            if failure.stage is FailureStage.MEASUREMENT:
                return CellStatus.FAILED if failure.size == size else CellStatus.SKIPPED
        return CellStatus.SKIPPED

    def measurements_for(self, distribution: str) -> tuple[SizeMeasurement, ...]:
        """Select the measurements of one distribution.

        Args:
            distribution: The name of the distribution.

        Returns:
            Its measurements, in size order of the settings.
        """
        return tuple(
            measurement
            for measurement in self.measurements
            if measurement.distribution == distribution
        )

    def measurement_at(self, distribution: str, size: Size) -> SizeMeasurement | None:
        """Look up the measurement for a distribution and size.

        Args:
            distribution: The name of the distribution.
            size: The input size.

        Returns:
            The measurement, or ``None`` if it was not made.
        """
        for measurement in self.measurements:
            if measurement.distribution == distribution and measurement.size == size:
                return measurement
        return None

    def growth(self, distribution: str) -> Growth | None:
        """Estimate how the median time grows with the size for one distribution.

        The fit always uses the medians of the unadjusted samples minus the
        median startup time (the statistic :meth:`is_growth_reliable` compares
        with), whether or not the settings subtract startup from the reported
        samples: a constant startup cost flattens any curve, so growth fitted on
        total times would describe process startup rather than the algorithm.
        Without a startup measurement the unadjusted medians are used.

        Args:
            distribution: The name of the distribution.

        Returns:
            The growth, or ``None`` when there is no estimate (see
            :func:`~algorithm_playground.core.estimate_growth`).
        """
        measurements = self.measurements_for(distribution)
        startup_seconds = self.startup.median if self.startup is not None else 0.0
        return estimate_growth(
            [measurement.size[self.growth_dimension] for measurement in measurements],
            [
                statistics.median(measurement.raw_samples) - startup_seconds
                for measurement in measurements
            ],
        )

    def is_growth_reliable(self, distribution: str) -> bool:
        """Tell whether enough medians are clearly above the startup time to trust the growth.

        A run of a fast program is mostly process startup, and the fitted growth
        of a series that is mostly startup is flat whatever the algorithm does.
        The growth is reliable when at least three sizes of the distribution have
        a median (of the unadjusted samples) above the startup median by more than
        the noise of the startup samples. It is judged reliable when there is no
        startup measurement to compare with.

        Args:
            distribution: The name of the distribution.

        Returns:
            ``True`` when the growth of the distribution can be trusted.
        """
        if self.startup is None:
            return True
        floor = self.startup.median + max(
            NOISE_STANDARD_DEVIATIONS * self.startup.standard_deviation,
            MINIMUM_NOISE_FRACTION * self.startup.median,
        )
        clear = sum(
            statistics.median(measurement.raw_samples) > floor
            for measurement in self.measurements_for(distribution)
        )
        return clear >= MINIMUM_GROWTH_POINTS

    def operation_names(self) -> tuple[str, ...]:
        """List the operations this implementation reported.

        Returns:
            The operation names, in first-seen order.
        """
        names: dict[str, None] = {}
        for measurement in self.measurements:
            names.update(dict.fromkeys(measurement.operation_counts or {}))
        return tuple(names)

    def operation_growth(self, distribution: str) -> dict[str, Growth | None]:
        """Estimate how each reported operation count grows with the size for one distribution.

        Args:
            distribution: The name of the distribution.

        Returns:
            An entry for every operation this implementation reported; it is
            ``None`` when fewer than three sizes had a positive count (see
            :func:`~algorithm_playground.core.estimate_growth`).
        """
        measurements = [
            measurement
            for measurement in self.measurements_for(distribution)
            if measurement.operation_counts is not None
        ]
        return {
            name: estimate_growth(
                [
                    measurement.size[self.growth_dimension]
                    for measurement in measurements
                ],
                [
                    (measurement.operation_counts or {}).get(name, 0)
                    for measurement in measurements
                ],
            )
            for name in self.operation_names()
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkReport:
    """The result of benchmarking several implementations of one problem.

    ``score_name`` is what the problem's ``verify`` scores, or ``None``.
    """

    problem_name: str
    settings: BenchmarkSettings
    implementations: tuple[ImplementationBenchmark, ...]
    dimensions: tuple[Dimension, ...] = (Dimension("size"),)
    growth_dimension: str = "size"
    score_name: str | None = None

    @property
    def has_passed(self) -> bool:
        """Whether every implementation completed all of its runs."""
        return not any(benchmark.failures for benchmark in self.implementations)


@dataclass(frozen=True, slots=True)
class _MeasurementPoint:
    """Where a run belongs: a ``size`` of a ``distribution``, or the startup (both ``None``).

    ``label`` names the point in failure messages.
    """

    label: str
    size: Size | None = None
    distribution: str | None = None

    @property
    def warmup_phase(self) -> BenchmarkPhase:
        """The phase of a discarded run at this point."""
        return BenchmarkPhase.STARTUP if self.size is None else BenchmarkPhase.WARMUP

    @property
    def measurement_phase(self) -> BenchmarkPhase:
        """The phase of a timed run at this point."""
        return (
            BenchmarkPhase.STARTUP if self.size is None else BenchmarkPhase.MEASUREMENT
        )


class _Benchmark:
    """The state of one benchmark run: the runners and the failures so far.

    A failure is recorded in ``failures``. It takes the implementation out of
    the rest of its distribution, or out of everything when it happened in the
    startup measurement.
    """

    def __init__(
        self,
        problem: AnyProblem,
        implementations: Sequence[Implementation],
        settings: BenchmarkSettings,
        *,
        runner_factory: RunnerFactory,
        on_progress: Callable[[BenchmarkProgress], None] | None,
    ) -> None:
        self._problem = problem
        self._implementations = implementations
        self._runners = {
            implementation.name: runner_factory(problem, implementation)
            for implementation in implementations
        }
        self._settings = settings
        self._on_progress = on_progress
        self.failures: dict[str, list[BenchmarkFailure]] = {}
        self._stopped: set[tuple[str, str | None]] = set()

    def run(self, generators: Sequence[AnyInputGenerator]) -> BenchmarkReport:
        """Measure the startup and then every size of every distribution.

        Args:
            generators: The generators of the distributions to measure.

        Returns:
            The report, with the failures recorded along the way.
        """
        startups = self._measure_startups()
        measurements: dict[str, list[SizeMeasurement]] = {
            implementation.name: [] for implementation in self._implementations
        }
        for generator in generators:
            for name, measurement in self._measure_distribution(generator, startups):
                measurements[name].append(measurement)
        growth_dimension = get_growth_dimension(self._problem).name
        return BenchmarkReport(
            problem_name=self._problem.name,
            settings=self._settings,
            implementations=tuple(
                ImplementationBenchmark(
                    implementation=implementation,
                    startup=startups.get(implementation.name),
                    measurements=tuple(measurements[implementation.name]),
                    failures=tuple(self.failures.get(implementation.name, ())),
                    growth_dimension=growth_dimension,
                )
                for implementation in self._implementations
            ),
            dimensions=tuple(self._problem.dimensions),
            growth_dimension=growth_dimension,
            score_name=self._problem.score_name,
        )

    def _measure_point(
        self, case: AnyCase, distribution: str, size: Size
    ) -> tuple[
        dict[str, list[float]],
        dict[str, Mapping[str, int]],
        dict[str, OperationIssue],
        dict[str, list[float]],
    ]:
        """Time every active implementation on ``case``; with counting on, also count operations.

        Args:
            case: The generated case to run.
            distribution: The name of the distribution of the case.
            size: The input size of the case.

        Returns:
            The wall-time samples of the implementations that completed every
            run, the operation counts of those that reported some, the
            issues of those that could not, and the scores of the verified
            repetitions of each implementation.
        """
        point = _MeasurementPoint(f"{size} ({distribution})", size, distribution)
        samples, scores = self._measure(case.input_data, point)
        if not self._settings.count_operations:
            return samples, {}, {}, scores
        counts, issues = self._count_operations(list(samples), case.input_data, point)
        return samples, counts, issues, scores

    def _measure(
        self, input_data: object, point: _MeasurementPoint
    ) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
        """Time the active implementations on one input, round-robin.

        The implementations that fail are recorded in ``failures`` and left out
        of the result. A ``point`` without a size is the startup measurement.

        Args:
            input_data: The input to run.
            point: Where the runs belong.

        Returns:
            The wall-time samples of the implementations that completed every
            run, and the scores of the verified timed repetitions of each
            implementation that took part.
        """
        distribution = point.distribution
        samples: dict[str, list[float]] = {
            name: [] for name in self._active_names(distribution=distribution)
        }
        scores: dict[str, list[float]] = {name: [] for name in samples}
        for _ in range(self._settings.warmup):
            for name in self._active_names(samples, distribution=distribution):
                self._execute(name, input_data, point, phase=point.warmup_phase)
        for _ in range(self._settings.repetitions):
            for name in self._active_names(samples, distribution=distribution):
                self._record_sample(
                    name, input_data, point, samples=samples, scores=scores
                )
        completed = {
            name: values
            for name, values in samples.items()
            if not self._is_stopped(name, distribution)
        }
        return completed, scores

    def _fail_distribution(self, distribution: str, message: str) -> None:
        """Record that the problem could not generate the inputs of ``distribution``.

        Every implementation that was still running in the distribution gets the
        failure and takes no further part in it.

        Args:
            distribution: The name of the distribution.
            message: What went wrong.
        """
        for name in self._active_names(distribution=distribution):
            self.failures.setdefault(name, []).append(
                BenchmarkFailure(
                    stage=FailureStage.DISTRIBUTION,
                    message=message,
                    distribution=distribution,
                )
            )
            self._stopped.add((name, distribution))

    def _measure_startups(self) -> dict[str, TimingSummary]:
        """Time the active implementations on the startup input.

        Returns:
            The timing summary of every implementation that completed every run.
        """
        input_data = build_startup_case(self._problem, self._settings.seed).input_data
        return {
            name: summarize(samples)
            for name, samples in self._measure(
                input_data, _MeasurementPoint("startup")
            )[0].items()
        }

    def _measure_distribution(
        self, generator: AnyInputGenerator, startups: Mapping[str, TimingSummary]
    ) -> Iterator[tuple[str, SizeMeasurement]]:
        """Measure every size of one distribution.

        A generator that raises fails the distribution for every implementation
        and ends it.

        Args:
            generator: The generator of the distribution.
            startups: The startup summary of each implementation, subtracted
                from the reported samples when the settings ask for it.

        Yields:
            The name of an implementation with its measurement at one size.
        """
        for size in self._settings.sizes:
            try:
                case = generate_case(generator, size=size, seed=self._settings.seed)
            except HookError as error:
                self._fail_distribution(
                    generator.name,
                    f"Could not generate the input {size} for the distribution "
                    f"'{generator.name}': {error}",
                )
                return
            yield from self._measure_size(
                case, startups, distribution=generator.name, size=size
            )

    def _measure_size(
        self,
        case: AnyCase,
        startups: Mapping[str, TimingSummary],
        *,
        distribution: str,
        size: Size,
    ) -> Iterator[tuple[str, SizeMeasurement]]:
        samples, counts, issues, scores = self._measure_point(case, distribution, size)
        for name, raw_samples in samples.items():
            reported_samples = (
                subtract_startup(raw_samples, startups[name].mean)
                if self._settings.subtract_startup_time
                else raw_samples
            )
            yield (
                name,
                SizeMeasurement(
                    distribution=distribution,
                    size=size,
                    case_identifier=case.identifier,
                    raw_samples=tuple(raw_samples),
                    summary=summarize(reported_samples),
                    operation_counts=counts.get(name),
                    operation_issue=issues.get(name),
                    scores=tuple(scores.get(name, ())),
                ),
            )

    def _is_stopped(self, name: str, distribution: str | None) -> bool:
        return (name, None) in self._stopped or (name, distribution) in self._stopped

    def _active_names(
        self, among: Mapping[str, object] | None = None, *, distribution: str | None
    ) -> list[str]:
        """List the implementations that may still run in ``distribution``.

        Returns:
            The names, in run order.
        """
        names = among if among is not None else self._runners
        return [name for name in names if not self._is_stopped(name, distribution)]

    def _fail(self, name: str, message: str, point: _MeasurementPoint) -> None:
        """Record a failure; the implementation stops here for its distribution (or entirely)."""
        stage = FailureStage.STARTUP if point.size is None else FailureStage.MEASUREMENT
        self.failures.setdefault(name, []).append(
            BenchmarkFailure(
                stage=stage,
                message=message,
                distribution=point.distribution,
                size=point.size,
            )
        )
        self._stopped.add((name, point.distribution))

    def _execute(
        self,
        name: str,
        input_data: object,
        point: _MeasurementPoint,
        *,
        phase: BenchmarkPhase,
    ) -> RunResult[object, object] | None:
        """Run one implementation once.

        Returns:
            The result, or ``None`` after recording a failure.
        """
        self._report_started(name, phase, point)
        try:
            return self._runners[name].run(input_data)
        except RunnerError as error:
            self._fail(name, f"Run failed for {point.label}: {error}", point)
            return None
        finally:
            self._report_completed(name, phase, point)

    def _record_sample(
        self,
        name: str,
        input_data: object,
        point: _MeasurementPoint,
        *,
        samples: dict[str, list[float]],
        scores: dict[str, list[float]],
    ) -> None:
        """Run one implementation once and keep its wall time when the run is good.

        The sample is kept only when the run succeeded and, if outputs are
        verified, its output verified; the score of a verified output is kept
        in ``scores``.
        """
        result = self._execute(name, input_data, point, phase=point.measurement_phase)
        if result is None:
            return
        if self._settings.verify_outputs:
            message, score = self._verify(input_data, result.output)
            if message is not None:
                self._fail(
                    name, f"Verification failed for {point.label}: {message}", point
                )
                return
            if score is not None:
                scores[name].append(score)
        samples[name].append(result.wall_seconds)

    def _verify(
        self, input_data: object, output: object
    ) -> tuple[str | None, float | None]:
        """Verify ``output``.

        Returns:
            Why ``output`` was rejected, or ``None`` when it passed, and the
            score the verifier gave, if any.
        """
        try:
            verification = self._problem.verify(input_data, output)
        except Exception as error:  # noqa: BLE001  the verify hook is problem code
            return f"verification raised {describe_error(error)}", None
        message = None if verification.passed else verification.message
        return message, verification.score

    def _verification_failure(self, input_data: object, output: object) -> str | None:
        """Verify ``output``.

        Returns:
            Why ``output`` was rejected, or ``None`` when it passed.
        """
        return self._verify(input_data, output)[0]

    def _count_operations(
        self, names: list[str], input_data: object, point: _MeasurementPoint
    ) -> tuple[dict[str, Mapping[str, int]], dict[str, OperationIssue]]:
        """Run each of ``names`` once with a trace and read its operation counts.

        A run that fails, or a problem hook that raises, is recorded in
        ``failures`` like a failed timed run; an output that does not verify
        and a malformed trace only cost the counts.

        Returns:
            The counts of the implementations that reported some and the issue
            of each one that could not.
        """
        counts: dict[str, Mapping[str, int]] = {}
        issues: dict[str, OperationIssue] = {}
        for name in names:
            if self._is_stopped(name, point.distribution):
                continue
            reported = self._count_one(name, input_data, point)
            if isinstance(reported, OperationIssue):
                issues[name] = reported
            elif reported is not None:
                counts[name] = reported
        return counts, issues

    def _count_one(
        self, name: str, input_data: object, point: _MeasurementPoint
    ) -> Mapping[str, int] | OperationIssue | None:
        """Count the operations of one implementation, reporting progress.

        Returns:
            The counts, the reason there are none, or ``None`` when the
            implementation reported nothing.
        """
        phase = BenchmarkPhase.OPERATION_COUNT
        self._report_started(name, phase, point)
        try:
            return self._counting_run(name, input_data)
        except RunnerError as error:
            message = f"Run failed for {point.label} while counting operations: {error}"
            return self._fail_counting(name, message, point)
        except Exception as error:  # noqa: BLE001  operation_counts is problem code
            message = (
                f"Counting operations failed for {point.label}: "
                f"operation_counts raised {describe_error(error)}"
            )
            return self._fail_counting(name, message, point)
        finally:
            self._report_completed(name, phase, point)

    def _fail_counting(
        self, name: str, message: str, point: _MeasurementPoint
    ) -> OperationIssue:
        """Record a failed counting run.

        Returns:
            The issue to report for it.
        """
        self._fail(name, message, point)
        return OperationIssue(kind=OperationIssueKind.COUNTING_FAILED, message=message)

    def _counting_run(
        self, name: str, input_data: object
    ) -> Mapping[str, int] | OperationIssue | None:
        """Run once with a trace.

        Returns:
            The counts, the reason there are none, or ``None``.
        """
        result = self._runners[name].run_with_trace(input_data)
        if self._settings.verify_outputs:
            message = self._verification_failure(input_data, result.output)
            if message is not None:
                return OperationIssue(
                    kind=OperationIssueKind.UNVERIFIED_OUTPUT, message=message
                )
        if result.trace_error is not None:
            return OperationIssue(
                kind=OperationIssueKind.MALFORMED_TRACE, message=result.trace_error
            )
        if result.trace is None:
            return None
        counts = self._problem.operation_counts(input_data, result.output, result.trace)
        return None if counts is None else dict(counts)

    def _report_started(
        self, name: str, phase: BenchmarkPhase, point: _MeasurementPoint
    ) -> None:
        self._notify(
            BenchmarkProgress(
                implementation_name=name,
                phase=phase,
                size=point.size,
                completed=False,
                distribution=point.distribution,
            )
        )

    def _report_completed(
        self, name: str, phase: BenchmarkPhase, point: _MeasurementPoint
    ) -> None:
        self._notify(
            BenchmarkProgress(
                implementation_name=name,
                phase=phase,
                size=point.size,
                completed=True,
                distribution=point.distribution,
            )
        )

    def _notify(self, event: BenchmarkProgress) -> None:
        if self._on_progress is not None:
            self._on_progress(event)


def include_failed_implementations(
    report: BenchmarkReport,
    implementations: Sequence[Implementation],
    failures: Mapping[str, BenchmarkFailure],
) -> BenchmarkReport:
    """Add an entry for each implementation that could not be measured at all.

    Each shows up as an implementation that failed before its first
    measurement. The others keep the entries of ``report``.

    Args:
        report: The report of the implementations that were measured.
        implementations: All the implementations, in the order the result lists them.
        failures: A ``BUILD`` or ``CANNOT_RUN`` failure for each implementation
            whose build failed or whose command cannot be started, keyed by name.

    Returns:
        The report with an entry for every implementation, in the order of
        ``implementations``.
    """
    measured = {
        benchmark.implementation.name: benchmark for benchmark in report.implementations
    }
    entries = tuple(
        measured[implementation.name]
        if implementation.name in measured
        else ImplementationBenchmark(
            implementation=implementation,
            startup=None,
            measurements=(),
            failures=(failures[implementation.name],),
            growth_dimension=report.growth_dimension,
        )
        for implementation in implementations
    )
    return replace(report, implementations=entries)


def count_total_runs(settings: BenchmarkSettings, implementation_count: int) -> int:
    """Count the most executable runs a benchmark can perform (for progress bars).

    A failing implementation skips its remaining runs, so the actual number
    can be lower.

    Args:
        settings: The settings of the benchmark.
        implementation_count: How many implementations are benchmarked.

    Returns:
        The number of runs.
    """
    distribution_count = max(len(settings.distributions), 1)
    points = distribution_count * len(settings.sizes)
    timed = (
        implementation_count * (points + 1) * (settings.warmup + settings.repetitions)
    )
    counting = implementation_count * points if settings.count_operations else 0
    return timed + counting


def run_benchmark(
    problem: AnyProblem,
    implementations: Sequence[Implementation],
    settings: BenchmarkSettings,
    *,
    runner_factory: RunnerFactory | None = None,
    on_progress: Callable[[BenchmarkProgress], None] | None = None,
) -> BenchmarkReport:
    """Benchmark every implementation on identical inputs and return the comparison.

    A generator that raises for an input after the startup input is a failure
    of its distribution (stage ``DISTRIBUTION``) and the run goes on.

    It raises ``ValueError`` if there is no implementation or names repeat,
    ``CaseError`` for a distribution the problem does not define and for a size
    that is not one the problem accepts (the startup size included), and ``HookError`` when the problem's
    ``generators`` hook raises or the generator of the startup input does.

    Args:
        problem: The problem that generates and verifies the inputs.
        implementations: The implementations to benchmark.
        settings: The parameters of the run.
        runner_factory: Replaces the process-spawning runner; it receives the
            problem and the implementation.
        on_progress: Receives an event before and after each executable run
            that is attempted.

    Returns:
        The report, whose settings list the distributions it measured.
    """
    validate_implementations(implementations)
    check_sizes(problem, (build_minimum_size(problem), *settings.sizes))
    canonical_sizes = tuple(
        Size(
            **{dimension.name: size[dimension.name] for dimension in problem.dimensions}
        )
        for size in settings.sizes
    )
    generators = (
        select_generators(problem, settings.distributions)
        if settings.distributions
        else [get_default_generator(problem)]
    )
    settings = replace(
        settings,
        sizes=canonical_sizes,
        distributions=tuple(generator.name for generator in generators),
        count_operations=settings.count_operations and has_trace_format(problem),
    )
    factory = runner_factory or build_subprocess_runner_factory(
        timeout_seconds=settings.timeout_seconds
    )
    benchmark = _Benchmark(
        problem,
        implementations,
        settings,
        runner_factory=factory,
        on_progress=on_progress,
    )
    return benchmark.run(generators)
