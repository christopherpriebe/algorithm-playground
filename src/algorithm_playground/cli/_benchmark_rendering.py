"""How the ``benchmark`` command shows a benchmark report.

One implementation gets a table of timing statistics per size; several get a
table of medians with their ratio to the reference. With several distributions
each one has a header row in the tables; with one, a line under the table names
it. The times of a table share one unit, named in its header. The growth row
gives the best-fitting class and the fitted exponent (``~ n log n (n^1.21)``),
with a star when the times are too close to the startup time to tell. Operation
counts have a table per operation, with a column per implementation. A cell of
an implementation that failed says ``failed``, and the cells it never reached
because of that failure say ``skipped``; when the problem's generator for a
distribution raised, the unmeasured cells of that distribution say ``failed``
for every implementation and the message is printed once. Everything here only
prints; the report comes from
:func:`~algorithm_playground.core.run_benchmark`.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from statistics import median

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from algorithm_playground.cli._rendering import format_size, print_table
from algorithm_playground.core._benchmarking import (
    BenchmarkReport,
    CellStatus,
    FailureStage,
    ImplementationBenchmark,
    OperationIssueKind,
    SizeMeasurement,
)
from algorithm_playground.core._dimensions import Size
from algorithm_playground.core._statistics import Growth, TimingSummary, format_duration
from algorithm_playground.visualization import AxisScale, ChartSeries, render_line_chart

__all__ = [
    "plot_medians",
    "print_comparison_table",
    "print_failures",
    "print_footer",
    "print_operation_issues",
    "print_operation_tables",
    "print_single_table",
]

STARTUP_ROW_LABEL = "startup"
GROWTH_ROW_LABEL = "growth"


def _growth_row_label(report: BenchmarkReport) -> str:
    """Name the growth row, and the dimension it follows when the size has several.

    Returns:
        The label.
    """
    if len(report.dimensions) == 1:
        return GROWTH_ROW_LABEL
    return f"{GROWTH_ROW_LABEL} (n = {report.growth_dimension})"


FAILED_CELL = "[red]failed[/red]"
SKIPPED_CELL = "[dim]skipped[/dim]"
UNAVAILABLE_CELL = "[dim]-[/dim]"
NOT_REPORTED_CELL = "[dim]not reported[/dim]"
UNRELIABLE_MARK = "*"
MINIMUM_POINTS_FOR_LINE = 2


def _choose_time_unit(seconds: Collection[float]) -> "_TimeUnit":
    """Choose the largest unit in which the typical (median) time is at least one.

    Returns:
        The largest unit in which the typical time is at least one.
    """
    positive = [abs(value) for value in seconds if value != 0]
    typical = median(positive) if positive else 1.0
    return next(
        (unit for unit in _TIME_UNITS if typical >= unit.seconds), _TIME_UNITS[-1]
    )


def _table_title(report: BenchmarkReport) -> str:
    return f"benchmark — {report.problem_name}"


def _print_caption(console: Console, report: BenchmarkReport, detail: str = "") -> None:
    """Print what the table shows under it, left aligned: ``detail`` and the distribution.

    The distribution is named here when there is only one (else each has a header row).
    """
    distributions = report.settings.distributions
    parts = [escape(detail)] if detail else []
    if len(distributions) == 1:
        parts.append(f"distribution: {escape(distributions[0])}")
    if parts:
        console.print("; ".join(parts), soft_wrap=True)


def _add_distribution_header(
    table: Table, report: BenchmarkReport, distribution: str
) -> None:
    """Start a section for ``distribution`` with a header row, when there are several."""
    table.add_section()
    if len(report.settings.distributions) > 1:
        cells = [f"[bold]{escape(distribution)}[/bold]"]
        table.add_row(*cells, *[""] * (len(table.columns) - 1))


def _format_growth(growth: Growth | None) -> str:
    return UNAVAILABLE_CELL if growth is None else escape(growth.describe())


def _format_timing_growth(benchmark: ImplementationBenchmark, distribution: str) -> str:
    """Format the growth of the times, starred when they are too close to the startup time.

    Returns:
        The growth text, marked when it is unreliable.
    """
    growth = benchmark.growth(distribution)
    if growth is None or benchmark.is_growth_reliable(distribution):
        return _format_growth(growth)
    return _format_growth(growth) + UNRELIABLE_MARK


def _print_reliability_note(console: Console, report: BenchmarkReport) -> None:
    if any(
        benchmark.growth(distribution) is not None
        and not benchmark.is_growth_reliable(distribution)
        for benchmark in report.implementations
        for distribution in report.settings.distributions
    ):
        console.print(
            f"{UNRELIABLE_MARK} The medians of this series are too close to the startup time to "
            "tell how the time grows; use larger sizes."
        )


def _add_summary_row(
    table: Table, label: str, summary: TimingSummary, *, unit: "_TimeUnit"
) -> None:
    table.add_row(
        label,
        unit.format_seconds(summary.minimum),
        unit.format_seconds(summary.median),
        unit.format_seconds(summary.standard_deviation),
        str(summary.count),
    )


def _build_single_table(
    report: BenchmarkReport, startup: TimingSummary, unit: "_TimeUnit"
) -> Table:
    result = report.implementations[0]
    table = Table()
    table.add_column("size", justify="right", no_wrap=True)
    for header in ("minimum", "median", "standard deviation"):
        table.add_column(f"{header} ({unit.name})", justify="right")
    table.add_column("samples", justify="right")
    _add_summary_row(table, f"[dim]{STARTUP_ROW_LABEL}[/dim]", startup, unit=unit)
    for distribution in report.settings.distributions:
        _add_distribution_header(table, report, distribution)
        for measurement in result.measurements_for(distribution):
            _add_summary_row(
                table, format_size(measurement.size), measurement.summary, unit=unit
            )
        if result.growth(distribution) is not None:
            table.add_row(
                _growth_row_label(report),
                "",
                _format_timing_growth(result, distribution),
                "",
                "",
            )
    return table


def _median_at(
    benchmark: ImplementationBenchmark, distribution: str, size: Size
) -> float | None:
    measurement = benchmark.measurement_at(distribution, size)
    return None if measurement is None else measurement.summary.median


def _comparison_cell(
    median_seconds: float | None,
    reference_median: float | None,
    status: CellStatus,
    *,
    unit: "_TimeUnit",
) -> str:
    """Format a median with its ratio to the reference.

    A cell that was not measured says ``failed`` when it is where the
    implementation failed, and ``skipped`` when it was never reached.

    Returns:
        The markup of the cell.
    """
    if median_seconds is None:
        return FAILED_CELL if status is CellStatus.FAILED else SKIPPED_CELL
    duration = unit.format_seconds(median_seconds)
    if reference_median is None or reference_median <= 0 or median_seconds <= 0:
        return duration
    return f"{duration} ({median_seconds / reference_median:.2f}x)"


def _startup_median(benchmark: ImplementationBenchmark) -> float | None:
    return None if benchmark.startup is None else benchmark.startup.median


def _choose_comparison_unit(report: BenchmarkReport) -> "_TimeUnit":
    return _choose_time_unit(
        [
            *(
                benchmark.startup.median
                for benchmark in report.implementations
                if benchmark.startup is not None
            ),
            *(
                measurement.summary.median
                for benchmark in report.implementations
                for measurement in benchmark.measurements
            ),
        ]
    )


def _operation_names(report: BenchmarkReport) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            name
            for benchmark in report.implementations
            for name in benchmark.operation_names()
        )
    )


def _operation_cell(
    benchmark: ImplementationBenchmark, distribution: str, size: Size, *, operation: str
) -> str:
    """Format one count of one measurement, or say why there is none.

    Returns:
        The markup of the cell.
    """
    measurement = benchmark.measurement_at(distribution, size)
    if measurement is None:
        status = benchmark.status_at(distribution, size)
        return FAILED_CELL if status is CellStatus.FAILED else SKIPPED_CELL
    if measurement.operation_issue is not None:
        return f"[red]{measurement.operation_issue.kind.value}[/red]"
    if measurement.operation_counts is None:
        return NOT_REPORTED_CELL
    count = measurement.operation_counts.get(operation)
    return "-" if count is None else f"{count:,}"


def _build_operation_table(report: BenchmarkReport, operation: str) -> Table:
    table = Table()
    table.add_column("size", justify="right", no_wrap=True)
    for benchmark in report.implementations:
        table.add_column(escape(benchmark.implementation.name), justify="right")
    for distribution in report.settings.distributions:
        _add_distribution_header(table, report, distribution)
        for size in report.settings.sizes:
            table.add_row(
                format_size(size),
                *(
                    _operation_cell(benchmark, distribution, size, operation=operation)
                    for benchmark in report.implementations
                ),
            )
        growths = [
            benchmark.operation_growth(distribution).get(operation)
            for benchmark in report.implementations
        ]
        if any(growth is not None for growth in growths):
            table.add_row(
                _growth_row_label(report),
                *(_format_growth(growth) for growth in growths),
            )
    return table


def _print_single_footer(
    console: Console, report: BenchmarkReport, startup: TimingSummary
) -> None:
    if not report.implementations[0].measurements:
        return
    if report.settings.subtract_startup_time:
        console.print(
            f"Startup time ({format_duration(startup.mean)}, mean of "
            f"{startup.count} empty-input runs) was subtracted from every sample. "
            "Negative values mean the work is below the measurement noise."
        )
    else:
        console.print(
            f"Every sample includes about {format_duration(startup.mean)} of startup "
            "time (the startup row). Pass --subtract-startup-time to remove it."
        )


def _print_comparison_footer(console: Console, report: BenchmarkReport) -> None:
    if report.settings.subtract_startup_time:
        console.print(
            "Each implementation's startup time (the mean of its empty-input runs) was "
            "subtracted from its samples. Negative values mean the work is below the "
            "measurement noise."
        )
    else:
        console.print(
            "Every sample includes its implementation's startup time (the startup row). "
            "Pass --subtract-startup-time to remove it."
        )


def _plottable_points(
    measurements: tuple[SizeMeasurement, ...], growth_dimension: str
) -> list[tuple[int, float]]:
    return [
        (measurement.size[growth_dimension], measurement.summary.median)
        for measurement in measurements
        if measurement.size[growth_dimension] > 0 and measurement.summary.median > 0
    ]


def _build_median_series(report: BenchmarkReport) -> list[ChartSeries]:
    distributions = report.settings.distributions
    series: list[ChartSeries] = []
    for benchmark in report.implementations:
        for distribution in distributions:
            points = _plottable_points(
                benchmark.measurements_for(distribution), report.growth_dimension
            )
            if points:
                name = benchmark.implementation.name
                series.append(
                    ChartSeries(
                        name=name
                        if len(distributions) == 1
                        else f"{name} ({distribution})",
                        x_values=tuple(size for size, _ in points),
                        y_values=tuple(median_seconds for _, median_seconds in points),
                    )
                )
    return series


@dataclass(frozen=True, slots=True)
class _TimeUnit:
    """The unit the times of one table are shown in."""

    name: str
    seconds: float

    def format_seconds(self, seconds: float) -> str:
        """Format a duration in this unit with three decimals.

        Args:
            seconds: The duration in seconds.

        Returns:
            The number of units, without the unit's name.
        """
        return f"{seconds / self.seconds:,.3f}"


_TIME_UNITS = (
    _TimeUnit("s", 1.0),
    _TimeUnit("ms", 1e-3),
    _TimeUnit("us", 1e-6),
    _TimeUnit("ns", 1e-9),
)


@dataclass(frozen=True, slots=True)
class _ComparisonTable:
    """A table of the medians of several implementations, with ratios to a reference."""

    report: BenchmarkReport
    reference: ImplementationBenchmark
    unit: _TimeUnit

    def build(self) -> Table:
        """Build the table: a column per implementation, and the startup row, then the sizes.

        Returns:
            The table.
        """
        table = Table()
        table.add_column("size", justify="right", no_wrap=True)
        for benchmark in self.report.implementations:
            table.add_column(escape(benchmark.implementation.name), justify="right")
        self._add_startup_row(table)
        for distribution in self.report.settings.distributions:
            _add_distribution_header(table, self.report, distribution)
            for size in self.report.settings.sizes:
                self._add_size_row(table, distribution, size)
            self._add_growth_row(table, distribution)
        return table

    def _add_startup_row(self, table: Table) -> None:
        reference_startup = _startup_median(self.reference)
        table.add_row(
            f"[dim]{STARTUP_ROW_LABEL}[/dim]",
            *(
                _comparison_cell(
                    _startup_median(benchmark),
                    reference_startup,
                    benchmark.startup_status(),
                    unit=self.unit,
                )
                for benchmark in self.report.implementations
            ),
        )

    def _add_size_row(self, table: Table, distribution: str, size: Size) -> None:
        reference_median = _median_at(self.reference, distribution, size)
        table.add_row(
            format_size(size),
            *(
                _comparison_cell(
                    _median_at(benchmark, distribution, size),
                    reference_median,
                    benchmark.status_at(distribution, size),
                    unit=self.unit,
                )
                for benchmark in self.report.implementations
            ),
        )

    def _add_growth_row(self, table: Table, distribution: str) -> None:
        benchmarks = self.report.implementations
        if any(benchmark.growth(distribution) is not None for benchmark in benchmarks):
            table.add_row(
                _growth_row_label(self.report),
                *(
                    _format_timing_growth(benchmark, distribution)
                    for benchmark in benchmarks
                ),
            )


def print_single_table(console: Console, report: BenchmarkReport) -> None:
    """Print the timing statistics of the only implementation, per size.

    Nothing is printed when the implementation has no startup measurement.

    Args:
        console: The console to print on.
        report: The benchmark report of one implementation.
    """
    result = report.implementations[0]
    if result.startup is None:
        return
    unit = _choose_time_unit(
        [
            result.startup.minimum,
            result.startup.median,
            *(measurement.summary.median for measurement in result.measurements),
        ]
    )
    print_table(
        console, _table_title(report), _build_single_table(report, result.startup, unit)
    )
    _print_caption(console, report)
    _print_reliability_note(console, report)


def print_comparison_table(
    console: Console, report: BenchmarkReport, reference_name: str
) -> None:
    """Print the median of each implementation per size, with the ratio to a reference.

    Args:
        console: The console to print on.
        report: The benchmark report of several implementations.
        reference_name: The name of the implementation the ratios are computed against.
    """
    reference = next(
        benchmark
        for benchmark in report.implementations
        if benchmark.implementation.name == reference_name
    )
    unit = _choose_comparison_unit(report)
    print_table(
        console, _table_title(report), _ComparisonTable(report, reference, unit).build()
    )
    _print_caption(console, report, f"median in {unit.name}, ratio to {reference_name}")
    _print_reliability_note(console, report)


def print_operation_tables(console: Console, report: BenchmarkReport) -> None:
    """Print the operation counts: a table per operation with a column per implementation.

    Args:
        console: The console to print on.
        report: The benchmark report, measured with operation counting.
    """
    names = _operation_names(report)
    if not names:
        console.print(
            "[yellow]No implementation reported operation counts.[/yellow] To report them, "
            "accept the optional third path and write the problem's trace format to it; "
            "see the documentation of the problem."
        )
        return
    for operation in names:
        print_table(
            console,
            f"{operation} — {report.problem_name}",
            _build_operation_table(report, operation),
        )
    console.print(
        "Counted in one extra untimed run per implementation, distribution and size with a "
        "trace file; the growth row is the fitted growth of the count with the size."
    )


def print_operation_issues(console: Console, report: BenchmarkReport) -> None:
    """Explain each measurement whose counts were left out: a bad trace or an unverified output.

    A counting run that failed is described with the other failures.

    Args:
        console: The console to print on.
        report: The benchmark report, measured with operation counting.
    """
    for benchmark in report.implementations:
        for measurement in benchmark.measurements:
            issue = measurement.operation_issue
            if issue is None or issue.kind is OperationIssueKind.COUNTING_FAILED:
                continue
            console.print(
                f"[yellow]{escape(benchmark.implementation.name)} "
                f"({escape(measurement.distribution)}, {measurement.size}): "
                f"no operation counts, {issue.kind.value}:[/yellow] {escape(issue.message)}",
                soft_wrap=True,
            )


def print_footer(console: Console, report: BenchmarkReport) -> None:
    """Say whether the startup time is included in the samples or was subtracted.

    Nothing is printed when no implementation has a startup measurement.

    Args:
        console: The console to print on.
        report: The benchmark report.
    """
    startups = [
        benchmark.startup
        for benchmark in report.implementations
        if benchmark.startup is not None
    ]
    if not startups:
        return
    if len(report.implementations) == 1:
        _print_single_footer(console, report, startups[0])
    else:
        _print_comparison_footer(console, report)


def print_failures(
    console: Console, report: BenchmarkReport, *, excluded: Collection[str]
) -> None:
    """Print each failure message; failed builds were already reported when they happened.

    The failure of a distribution, which every implementation records, is
    printed once.

    Args:
        console: The console to print on.
        report: The benchmark report.
        excluded: The names of the implementations whose failures are not printed.
    """
    shown_distribution_failures: set[tuple[str | None, str]] = set()
    for benchmark in report.implementations:
        if benchmark.implementation.name in excluded:
            continue
        for failure in benchmark.failures:
            if failure.stage is not FailureStage.DISTRIBUTION:
                console.print(
                    f"[red]{escape(benchmark.implementation.name)} failed:[/red] "
                    f"{escape(failure.message)}",
                    soft_wrap=True,
                )
            elif (
                failure.distribution,
                failure.message,
            ) not in shown_distribution_failures:
                shown_distribution_failures.add((failure.distribution, failure.message))
                console.print(f"[red]{escape(failure.message)}[/red]", soft_wrap=True)


def plot_medians(
    report: BenchmarkReport, *, draw_chart: Callable[..., None] = render_line_chart
) -> None:
    """Draw the median time against the size, one line per implementation and distribution.

    Nothing is drawn when no line has two points.

    Args:
        report: The benchmark report.
        draw_chart: Draws the lines, called like
            :func:`~algorithm_playground.visualization.render_line_chart`.
    """
    series = _build_median_series(report)
    if not any(len(line.x_values) >= MINIMUM_POINTS_FOR_LINE for line in series):
        return
    startup_note = (
        " (startup subtracted)" if report.settings.subtract_startup_time else ""
    )
    draw_chart(
        series,
        title=f"{report.problem_name}: median wall time against size",
        x_label="size" if len(report.dimensions) == 1 else report.growth_dimension,
        y_label=f"median seconds{startup_note}",
        x_scale=AxisScale.LOGARITHMIC,
        y_scale=AxisScale.LOGARITHMIC,
    )
