"""Benchmark engine: time several implementations on identical, seeded inputs.

For every size the engine runs the warmup iterations of each implementation
first, then interleaves the measured repetitions round-robin (repetition 1 of
every implementation, repetition 2 of every implementation, and so on) so
that drift in system load affects all implementations equally. Each
implementation also gets its own startup measurement on the problem's
startup case (the default generator at the problem's ``minimum_size``), once
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
them. The growth of the median time with the size is reported with its
best-fitting class, and judged unreliable when the medians are too close to the
startup median (see :meth:`ImplementationBenchmark.growth_is_reliable`). The engine never prints, and
runs go through a runner factory that tests replace with an in-process fake.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from algorithm_playground.core._support import describe_error, validate_implementations
from algorithm_playground.core.cases import (
    Case,
    check_sizes,
    default_generator,
    generate_case,
    select_generators,
    startup_case,
)
from algorithm_playground.core.hooks import HookError
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import Problem, has_trace_format
from algorithm_playground.core.runner import (
    RunnerError,
    RunnerFactory,
    RunnerLike,
    subprocess_runner_factory,
)
from algorithm_playground.core.statistics import (
    MINIMUM_GROWTH_POINTS,
    Growth,
    TimingSummary,
    estimate_growth,
    subtract_startup,
    summarize,
)

# A run is clearly slower than an empty-input run when it exceeds the startup median by
# this many standard deviations of the startup samples, and by at least this fraction of it.
NOISE_STANDARD_DEVIATIONS = 3.0
MINIMUM_NOISE_FRACTION = 0.1


@dataclass(frozen=True)
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
    sizes: tuple[int, ...]
    repetitions: int
    warmup: int
    timeout_seconds: float
    verify_outputs: bool
    subtract_startup_time: bool
    distributions: tuple[str, ...] = ()
    count_operations: bool = False

    def __post_init__(self) -> None:
        if not self.sizes:
            raise ValueError("At least one size is required")
        if any(size < 0 for size in self.sizes):
            raise ValueError(f"Sizes must be non-negative, got {self.sizes}")
        repeated = sorted({size for size in self.sizes if self.sizes.count(size) > 1})
        if repeated:
            raise ValueError(f"Sizes must be unique, but these were repeated: {repeated}")
        repeated_distributions = sorted(
            {name for name in self.distributions if self.distributions.count(name) > 1}
        )
        if repeated_distributions:
            raise ValueError(
                f"Distributions must be unique, but these were repeated: {repeated_distributions}"
            )
        if self.repetitions < 1:
            raise ValueError(f"Repetitions must be at least 1, got {self.repetitions}")
        if self.warmup < 0:
            raise ValueError(f"Warmup must be non-negative, got {self.warmup}")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError(
                f"Timeout must be a finite positive number, got {self.timeout_seconds}"
            )


class BenchmarkPhase(Enum):
    """Which part of a benchmark a run belongs to."""

    STARTUP = "startup"
    WARMUP = "warmup"
    MEASUREMENT = "measurement"
    OPERATION_COUNT = "operation count"


@dataclass(frozen=True)
class BenchmarkProgress:
    """A progress event: one run of one implementation is starting or has ended.

    ``size`` and ``distribution`` are ``None`` for the startup measurement.
    ``completed`` is false when the run is about to start and true after it
    ended, whether or not it succeeded; exactly one completed event is sent per
    attempted run.
    """

    implementation_name: str
    phase: BenchmarkPhase
    size: int | None
    completed: bool
    distribution: str | None = None


class OperationIssueKind(Enum):
    """Why a measurement has no operation counts although counting was on."""

    MALFORMED_TRACE = "malformed trace"
    UNVERIFIED_OUTPUT = "output did not verify"
    COUNTING_FAILED = "counting failed"


@dataclass(frozen=True)
class OperationIssue:
    """The reason an implementation reported no operation counts at one size."""

    kind: OperationIssueKind
    message: str


@dataclass(frozen=True)
class SizeMeasurement:
    """One implementation's timings at one input size of one distribution.

    ``case_identifier`` names the generated input, the same for every
    implementation. ``summary`` describes the reported samples (startup
    subtracted when the settings ask for it); ``raw_samples`` always holds the
    unadjusted wall times in run order. ``operation_counts`` maps the problem's
    operation names to how often the implementation did them; it is ``None``
    when counting was off or the implementation reported nothing, and
    ``operation_issue`` then says why when there was a reason other than the
    implementation writing no trace.
    """

    distribution: str
    size: int
    case_identifier: str
    raw_samples: tuple[float, ...]
    summary: TimingSummary
    operation_counts: Mapping[str, int] | None = None
    operation_issue: OperationIssue | None = None


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
    def precedes_measurement(self) -> bool:
        """Whether the implementation never got to run because of this failure."""
        return self in (FailureStage.BUILD, FailureStage.CANNOT_RUN)

    @property
    def belongs_to_distribution(self) -> bool:
        """Whether the failure affects one distribution and leaves the others and the startup."""
        return self in (FailureStage.MEASUREMENT, FailureStage.DISTRIBUTION)


@dataclass(frozen=True)
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
    size: int | None = None


class CellStatus(Enum):
    """What became of one table cell of an implementation."""

    MEASURED = "measured"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ImplementationBenchmark:
    """Everything measured for one implementation.

    ``failures`` lists what went wrong, in the order it happened; ``startup``
    and ``measurements`` hold whatever completed.
    """

    implementation: Implementation
    startup: TimingSummary | None
    measurements: tuple[SizeMeasurement, ...]
    failures: tuple[BenchmarkFailure, ...] = ()

    @property
    def failure(self) -> str | None:
        """The message of the first failure, or ``None`` when there was none."""
        return self.failures[0].message if self.failures else None

    def startup_status(self) -> CellStatus:
        """Whether the startup row of this implementation was measured, failed, or skipped."""
        if self.startup is not None:
            return CellStatus.MEASURED
        for failure in self.failures:
            if not failure.stage.belongs_to_distribution:
                return CellStatus.FAILED
        return CellStatus.SKIPPED

    def status_at(self, distribution: str, size: int) -> CellStatus:
        """Say what became of the cell for a distribution and size.

        A size that was never reached because of an earlier failure is
        ``SKIPPED``; the size at which the failure happened is ``FAILED``, and
        so is every size of an implementation whose build failed or that cannot
        run, and every size of a distribution whose generator raised.
        """
        if self.measurement_at(distribution, size) is not None:
            return CellStatus.MEASURED
        for failure in self.failures:
            if failure.stage.precedes_measurement:
                return CellStatus.FAILED
            if failure.distribution != distribution:
                continue
            if failure.stage is FailureStage.DISTRIBUTION:
                return CellStatus.FAILED
            if failure.stage is FailureStage.MEASUREMENT:
                return CellStatus.FAILED if failure.size == size else CellStatus.SKIPPED
        return CellStatus.SKIPPED

    def measurements_for(self, distribution: str) -> tuple[SizeMeasurement, ...]:
        """Return the measurements of one distribution, in size order of the settings."""
        return tuple(
            measurement
            for measurement in self.measurements
            if measurement.distribution == distribution
        )

    def measurement_at(self, distribution: str, size: int) -> SizeMeasurement | None:
        """Return the measurement for a distribution and size, or ``None`` if it was not made."""
        for measurement in self.measurements:
            if measurement.distribution == distribution and measurement.size == size:
                return measurement
        return None

    def growth(self, distribution: str) -> Growth | None:
        """Estimate how the median time grows with the size for one distribution.

        The fit always uses the medians of the unadjusted samples minus the
        median startup time (the statistic :meth:`growth_is_reliable` compares
        with), whether or not the settings subtract startup from the reported
        samples: a constant startup cost flattens any curve, so growth fitted on
        total times would describe process startup rather than the algorithm.
        Without a startup measurement the unadjusted medians are used.
        See :func:`~algorithm_playground.core.statistics.estimate_growth` for when
        there is no estimate.
        """
        measurements = self.measurements_for(distribution)
        startup_seconds = self.startup.median if self.startup is not None else 0.0
        return estimate_growth(
            [measurement.size for measurement in measurements],
            [
                statistics.median(measurement.raw_samples) - startup_seconds
                for measurement in measurements
            ],
        )

    def growth_is_reliable(self, distribution: str) -> bool:
        """Whether enough medians are clearly above the startup time to trust the time growth.

        A run of a fast program is mostly process startup, and the fitted growth
        of a series that is mostly startup is flat whatever the algorithm does.
        The growth is reliable when at least three sizes of the distribution have
        a median (of the unadjusted samples) above the startup median by more than
        the noise of the startup samples. It is judged reliable when there is no
        startup measurement to compare with.
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
        """Return the names of the operations this implementation reported, in first-seen order."""
        names: dict[str, None] = {}
        for measurement in self.measurements:
            names.update(dict.fromkeys(measurement.operation_counts or {}))
        return tuple(names)

    def operation_growth(self, distribution: str) -> dict[str, Growth | None]:
        """Estimate how each reported operation count grows with the size for one distribution.

        Every operation this implementation reported has an entry; it is
        ``None`` when fewer than three sizes had a positive count. See
        :func:`~algorithm_playground.core.statistics.estimate_growth`.
        """
        measurements = [
            measurement
            for measurement in self.measurements_for(distribution)
            if measurement.operation_counts is not None
        ]
        return {
            name: estimate_growth(
                [measurement.size for measurement in measurements],
                [(measurement.operation_counts or {}).get(name, 0) for measurement in measurements],
            )
            for name in self.operation_names()
        }


@dataclass(frozen=True)
class BenchmarkReport:
    """The result of benchmarking several implementations of one problem."""

    problem_name: str
    settings: BenchmarkSettings
    implementations: tuple[ImplementationBenchmark, ...]

    @property
    def passed(self) -> bool:
        """Whether every implementation completed all of its runs."""
        return not any(benchmark.failures for benchmark in self.implementations)


def include_failed_implementations(
    report: BenchmarkReport,
    implementations: Sequence[Implementation],
    failures: Mapping[str, BenchmarkFailure],
) -> BenchmarkReport:
    """Return ``report`` with an entry, in the order of ``implementations``, for each failure.

    ``failures`` maps the names of implementations that could not be measured
    at all, because their build failed or their command cannot be started, to
    the failure (a ``BUILD`` or ``CANNOT_RUN`` one). Each shows up as an
    implementation that failed before its first measurement. The others keep the
    entries of ``report``.
    """
    measured = {benchmark.implementation.name: benchmark for benchmark in report.implementations}
    entries = tuple(
        measured[implementation.name]
        if implementation.name in measured
        else ImplementationBenchmark(
            implementation=implementation,
            startup=None,
            measurements=(),
            failures=(failures[implementation.name],),
        )
        for implementation in implementations
    )
    return replace(report, implementations=entries)


def total_runs(settings: BenchmarkSettings, implementation_count: int) -> int:
    """Return the most executable runs a benchmark can perform (for progress bars).

    A failing implementation skips its remaining runs, so the actual number
    can be lower.
    """
    distribution_count = max(len(settings.distributions), 1)
    points = distribution_count * len(settings.sizes)
    timed = implementation_count * (points + 1) * (settings.warmup + settings.repetitions)
    counting = implementation_count * points if settings.count_operations else 0
    return timed + counting


def run_benchmark(
    problem: Problem[Any, Any, Any],
    implementations: Sequence[Implementation],
    settings: BenchmarkSettings,
    *,
    runner_factory: RunnerFactory | None = None,
    on_progress: Callable[[BenchmarkProgress], None] | None = None,
) -> BenchmarkReport:
    """Benchmark every implementation on identical inputs and return the comparison.

    ``on_progress`` receives an event before and after each executable run
    that is attempted. ``runner_factory`` replaces the process-spawning runner
    (it receives the problem and the implementation). Raise
    :class:`~algorithm_playground.core.cases.CaseError` for a distribution the
    problem does not define and for a size below the problem's ``minimum_size``,
    and :class:`~algorithm_playground.core.hooks.HookError` when the problem's
    ``generators`` hook raises or the generator of the startup input does. A
    generator that raises for a later input is a failure of its distribution
    (stage ``DISTRIBUTION``) and the run goes on.
    """
    validate_implementations(implementations)
    check_sizes(problem, settings.sizes)
    generators = (
        select_generators(problem, settings.distributions)
        if settings.distributions
        else [default_generator(problem)]
    )
    settings = replace(
        settings,
        distributions=tuple(generator.name for generator in generators),
        count_operations=settings.count_operations and has_trace_format(problem),
    )
    factory = runner_factory or subprocess_runner_factory(timeout_seconds=settings.timeout_seconds)
    benchmark = _Benchmark(
        problem,
        {
            implementation.name: factory(problem, implementation)
            for implementation in implementations
        },
        settings,
        on_progress,
    )

    startups = {
        name: summarize(samples)
        for name, samples in benchmark.measure(
            startup_case(problem, settings.seed).input_data, "startup"
        ).items()
    }
    measurements: dict[str, list[SizeMeasurement]] = {
        implementation.name: [] for implementation in implementations
    }
    for generator in generators:
        for size in settings.sizes:
            try:
                case = generate_case(generator, size=size, seed=settings.seed)
            except HookError as error:
                message = (
                    f"Could not generate the input of size {size:,} for the distribution "
                    f"'{generator.name}': {error}"
                )
                benchmark.fail_distribution(generator.name, message)
                break
            samples, counts, issues = benchmark.measure_point(case, generator.name, size)
            for name, raw_samples in samples.items():
                reported_samples = (
                    subtract_startup(raw_samples, startups[name].mean)
                    if settings.subtract_startup_time
                    else raw_samples
                )
                measurements[name].append(
                    SizeMeasurement(
                        distribution=generator.name,
                        size=size,
                        case_identifier=case.identifier,
                        raw_samples=tuple(raw_samples),
                        summary=summarize(reported_samples),
                        operation_counts=counts.get(name),
                        operation_issue=issues.get(name),
                    )
                )

    return BenchmarkReport(
        problem_name=problem.name,
        settings=settings,
        implementations=tuple(
            ImplementationBenchmark(
                implementation=implementation,
                startup=startups.get(implementation.name),
                measurements=tuple(measurements[implementation.name]),
                failures=tuple(benchmark.failures.get(implementation.name, ())),
            )
            for implementation in implementations
        ),
    )


class _Benchmark:
    """The state of one benchmark run: the runners and the failures so far.

    A failure is recorded in ``failures``. It takes the implementation out of
    the rest of its distribution, or out of everything when it happened in the
    startup measurement.
    """

    def __init__(
        self,
        problem: Problem[Any, Any, Any],
        runners: dict[str, RunnerLike],
        settings: BenchmarkSettings,
        on_progress: Callable[[BenchmarkProgress], None] | None,
    ) -> None:
        self._problem = problem
        self._runners = runners
        self._settings = settings
        self._on_progress = on_progress
        self.failures: dict[str, list[BenchmarkFailure]] = {}
        self._stopped: set[tuple[str, str | None]] = set()

    def measure_point(
        self, case: Case[Any], distribution: str, size: int
    ) -> tuple[dict[str, list[float]], dict[str, Mapping[str, int]], dict[str, OperationIssue]]:
        """Time every active implementation on ``case``; with counting on, also count operations.

        Return the wall-time samples of the implementations that completed every
        run, the operation counts of those that reported some, and the issues of
        those that could not.
        """
        label = f"size {size} ({distribution})"
        samples = self.measure(case.input_data, label, size=size, distribution=distribution)
        if not self._settings.count_operations:
            return samples, {}, {}
        counts, issues = self._count_operations(
            list(samples), case.input_data, label, size=size, distribution=distribution
        )
        return samples, counts, issues

    def measure(
        self,
        input_data: Any,
        label: str,
        *,
        size: int | None = None,
        distribution: str | None = None,
    ) -> dict[str, list[float]]:
        """Time the active implementations on one input, round-robin.

        Return the wall-time samples of the implementations that completed every
        run. The others are recorded in ``failures`` and left out of the result.
        A ``size`` of ``None`` marks the startup measurement.
        """
        samples: dict[str, list[float]] = {
            name: [] for name in self._active_names(distribution=distribution)
        }
        for _ in range(self._settings.warmup):
            for name in self._active_names(samples, distribution=distribution):
                self._run_once(name, input_data, label, size, distribution, samples=None)
        for _ in range(self._settings.repetitions):
            for name in self._active_names(samples, distribution=distribution):
                self._run_once(name, input_data, label, size, distribution, samples=samples)
        return {
            name: values
            for name, values in samples.items()
            if not self._is_stopped(name, distribution)
        }

    def _is_stopped(self, name: str, distribution: str | None) -> bool:
        return (name, None) in self._stopped or (name, distribution) in self._stopped

    def _active_names(
        self, among: Mapping[str, object] | None = None, *, distribution: str | None
    ) -> list[str]:
        """The implementations that may still run in ``distribution``, in run order."""
        names = among if among is not None else self._runners
        return [name for name in names if not self._is_stopped(name, distribution)]

    def fail_distribution(self, distribution: str, message: str) -> None:
        """Record that the problem could not generate the inputs of ``distribution``.

        Every implementation that was still running in the distribution gets the
        failure and takes no further part in it.
        """
        for name in self._active_names(distribution=distribution):
            self.failures.setdefault(name, []).append(
                BenchmarkFailure(FailureStage.DISTRIBUTION, message, distribution)
            )
            self._stopped.add((name, distribution))

    def _fail(self, name: str, message: str, *, size: int | None, distribution: str | None) -> None:
        """Record a failure; the implementation stops here for its distribution (or entirely)."""
        stage = FailureStage.STARTUP if size is None else FailureStage.MEASUREMENT
        self.failures.setdefault(name, []).append(
            BenchmarkFailure(stage, message, distribution, size)
        )
        self._stopped.add((name, distribution))

    def _run_once(
        self,
        name: str,
        input_data: Any,
        label: str,
        size: int | None,
        distribution: str | None,
        *,
        samples: dict[str, list[float]] | None,
    ) -> None:
        """Run one implementation once; ``samples`` is ``None`` for a discarded warmup run."""
        if size is None:
            phase = BenchmarkPhase.STARTUP
        else:
            phase = BenchmarkPhase.WARMUP if samples is None else BenchmarkPhase.MEASUREMENT
        self._report(name, phase, size, distribution, completed=False)
        try:
            result = self._runners[name].run(input_data, collect_trace=False)
        except RunnerError as error:
            self._fail(
                name, f"Run failed for {label}: {error}", size=size, distribution=distribution
            )
            return
        finally:
            self._report(name, phase, size, distribution, completed=True)
        if samples is None:
            return
        if self._settings.verify_outputs:
            message = self._verification_failure(input_data, result.output)
            if message is not None:
                self._fail(
                    name,
                    f"Verification failed for {label}: {message}",
                    size=size,
                    distribution=distribution,
                )
                return
        samples[name].append(result.wall_seconds)

    def _verification_failure(self, input_data: Any, output: Any) -> str | None:
        """Return why ``output`` was rejected, or ``None`` when it passed."""
        try:
            verification = self._problem.verify(input_data, output)
        except Exception as error:
            return f"verification raised {describe_error(error)}"
        return None if verification.passed else verification.message

    def _count_operations(
        self, names: list[str], input_data: Any, label: str, *, size: int, distribution: str
    ) -> tuple[dict[str, Mapping[str, int]], dict[str, OperationIssue]]:
        """Run each of ``names`` once with a trace and read its operation counts.

        Return the counts of the implementations that reported some and the
        issue of each one that could not. A run that fails, or a problem hook
        that raises, is recorded in ``failures`` like a failed timed run; an
        output that does not verify and a malformed trace only cost the counts.
        """
        counts: dict[str, Mapping[str, int]] = {}
        issues: dict[str, OperationIssue] = {}
        phase = BenchmarkPhase.OPERATION_COUNT
        for name in names:
            if self._is_stopped(name, distribution):
                continue
            self._report(name, phase, size, distribution, completed=False)
            try:
                reported = self._counting_run(name, input_data)
            except RunnerError as error:
                message = f"Run failed for {label} while counting operations: {error}"
                self._fail(name, message, size=size, distribution=distribution)
                issues[name] = OperationIssue(OperationIssueKind.COUNTING_FAILED, message)
                continue
            except Exception as error:
                message = (
                    f"Counting operations failed for {label}: "
                    f"operation_counts raised {describe_error(error)}"
                )
                self._fail(name, message, size=size, distribution=distribution)
                issues[name] = OperationIssue(OperationIssueKind.COUNTING_FAILED, message)
                continue
            finally:
                self._report(name, phase, size, distribution, completed=True)
            if isinstance(reported, OperationIssue):
                issues[name] = reported
            elif reported is not None:
                counts[name] = reported
        return counts, issues

    def _counting_run(
        self, name: str, input_data: Any
    ) -> Mapping[str, int] | OperationIssue | None:
        """Run once with a trace; return the counts, the reason there are none, or ``None``."""
        result = self._runners[name].run(input_data, collect_trace=True)
        if self._settings.verify_outputs:
            message = self._verification_failure(input_data, result.output)
            if message is not None:
                return OperationIssue(OperationIssueKind.UNVERIFIED_OUTPUT, message)
        if result.trace_error is not None:
            return OperationIssue(OperationIssueKind.MALFORMED_TRACE, result.trace_error)
        if result.trace is None:
            return None
        counts = self._problem.operation_counts(input_data, result.output, result.trace)
        return None if counts is None else dict(counts)

    def _report(
        self,
        name: str,
        phase: BenchmarkPhase,
        size: int | None,
        distribution: str | None,
        *,
        completed: bool,
    ) -> None:
        if self._on_progress is not None:
            self._on_progress(BenchmarkProgress(name, phase, size, completed, distribution))
