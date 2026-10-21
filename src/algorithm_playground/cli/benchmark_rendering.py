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
for every implementation and the message is printed once. Everything here only prints; the report
comes from :func:`~algorithm_playground.core.benchmarking.run_benchmark`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from statistics import median

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from algorithm_playground.cli.rendering import print_table
from algorithm_playground.core.benchmarking import (
    BenchmarkReport,
    CellStatus,
    FailureStage,
    ImplementationBenchmark,
    OperationIssueKind,
    SizeMeasurement,
)
from algorithm_playground.core.statistics import Growth, TimingSummary, format_duration
from algorithm_playground.visualization import ChartSeries, line_chart

STARTUP_ROW_LABEL = "startup"
GROWTH_ROW_LABEL = "growth"
FAILED_CELL = "[red]failed[/red]"
SKIPPED_CELL = "[dim]skipped[/dim]"
UNAVAILABLE_CELL = "[dim]-[/dim]"
NOT_REPORTED_CELL = "[dim]not reported[/dim]"
UNRELIABLE_MARK = "*"


@dataclass(frozen=True)
class _TimeUnit:
    """The unit the times of one table are shown in."""

    name: str
    seconds: float

    def format(self, seconds: float) -> str:
        return f"{seconds / self.seconds:,.3f}"


_TIME_UNITS = (
    _TimeUnit("s", 1.0),
    _TimeUnit("ms", 1e-3),
    _TimeUnit("us", 1e-6),
    _TimeUnit("ns", 1e-9),
)


def _time_unit(seconds: Collection[float]) -> _TimeUnit:
    """Choose the largest unit in which the typical (median) time is at least one."""
    positive = [abs(value) for value in seconds if value != 0]
    typical = median(positive) if positive else 1.0
    return next((unit for unit in _TIME_UNITS if typical >= unit.seconds), _TIME_UNITS[-1])


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


def _add_distribution_header(table: Table, report: BenchmarkReport, distribution: str) -> None:
    """Start a section for ``distribution`` with a header row, when there are several."""
    table.add_section()
    if len(report.settings.distributions) > 1:
        cells = [f"[bold]{escape(distribution)}[/bold]"]
        table.add_row(*cells, *[""] * (len(table.columns) - 1))


def _format_growth(growth: Growth | None, *, reliable: bool = True) -> str:
    if growth is None:
        return UNAVAILABLE_CELL
    return escape(growth.describe()) + ("" if reliable else UNRELIABLE_MARK)


def _print_reliability_note(console: Console, report: BenchmarkReport) -> None:
    if any(
        benchmark.growth(distribution) is not None
        and not benchmark.growth_is_reliable(distribution)
        for benchmark in report.implementations
        for distribution in report.settings.distributions
    ):
        console.print(
            f"{UNRELIABLE_MARK} The medians of this series are too close to the startup time to "
            "tell how the time grows; use larger sizes."
        )


def print_single_table(console: Console, report: BenchmarkReport) -> None:
    result = report.implementations[0]
    if result.startup is None:
        return
    unit = _time_unit(
        [
            result.startup.minimum,
            result.startup.median,
            *(measurement.summary.median for measurement in result.measurements),
        ]
    )
    table = Table()
    table.add_column("size", justify="right", no_wrap=True)
    for header in ("minimum", "median", "standard deviation"):
        table.add_column(f"{header} ({unit.name})", justify="right")
    table.add_column("samples", justify="right")
    _add_summary_row(table, f"[dim]{STARTUP_ROW_LABEL}[/dim]", result.startup, unit)
    for distribution in report.settings.distributions:
        _add_distribution_header(table, report, distribution)
        for measurement in result.measurements_for(distribution):
            _add_summary_row(table, f"{measurement.size:,}", measurement.summary, unit)
        growth = result.growth(distribution)
        if growth is not None:
            table.add_row(
                GROWTH_ROW_LABEL,
                "",
                _format_growth(growth, reliable=result.growth_is_reliable(distribution)),
                "",
                "",
            )
    print_table(console, _table_title(report), table)
    _print_caption(console, report)
    _print_reliability_note(console, report)


def print_comparison_table(console: Console, report: BenchmarkReport, reference_name: str) -> None:
    reference_benchmark = next(
        benchmark
        for benchmark in report.implementations
        if benchmark.implementation.name == reference_name
    )
    unit = _time_unit(
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
    table = Table()
    table.add_column("size", justify="right", no_wrap=True)
    for benchmark in report.implementations:
        table.add_column(escape(benchmark.implementation.name), justify="right")

    reference_startup = (
        reference_benchmark.startup.median if reference_benchmark.startup is not None else None
    )
    table.add_row(
        f"[dim]{STARTUP_ROW_LABEL}[/dim]",
        *(
            _comparison_cell(
                benchmark.startup.median if benchmark.startup is not None else None,
                reference_startup,
                benchmark.startup_status(),
                unit,
            )
            for benchmark in report.implementations
        ),
    )
    for distribution in report.settings.distributions:
        _add_distribution_header(table, report, distribution)
        for size in report.settings.sizes:
            reference_median = _median_at(reference_benchmark, distribution, size)
            table.add_row(
                f"{size:,}",
                *(
                    _comparison_cell(
                        _median_at(benchmark, distribution, size),
                        reference_median,
                        benchmark.status_at(distribution, size),
                        unit,
                    )
                    for benchmark in report.implementations
                ),
            )
        growths = [benchmark.growth(distribution) for benchmark in report.implementations]
        if any(growth is not None for growth in growths):
            table.add_row(
                GROWTH_ROW_LABEL,
                *(
                    _format_growth(growth, reliable=benchmark.growth_is_reliable(distribution))
                    for benchmark, growth in zip(report.implementations, growths, strict=True)
                ),
            )
    print_table(console, _table_title(report), table)
    _print_caption(console, report, f"median in {unit.name}, ratio to {reference_name}")
    _print_reliability_note(console, report)


def print_operation_tables(console: Console, report: BenchmarkReport) -> None:
    """Print the operation counts: a table per operation with a column per implementation."""
    names = tuple(
        dict.fromkeys(
            name for benchmark in report.implementations for name in benchmark.operation_names()
        )
    )
    if not names:
        console.print(
            "[yellow]No implementation reported operation counts.[/yellow] To report them, "
            "accept the optional third path and write the problem's trace format to it; "
            "see the documentation of the problem."
        )
        return
    for operation in names:
        table = Table()
        table.add_column("size", justify="right", no_wrap=True)
        for benchmark in report.implementations:
            table.add_column(escape(benchmark.implementation.name), justify="right")
        for distribution in report.settings.distributions:
            _add_distribution_header(table, report, distribution)
            for size in report.settings.sizes:
                table.add_row(
                    f"{size:,}",
                    *(
                        _operation_cell(benchmark, distribution, size, operation)
                        for benchmark in report.implementations
                    ),
                )
            growths = [
                benchmark.operation_growth(distribution).get(operation)
                for benchmark in report.implementations
            ]
            if any(growth is not None for growth in growths):
                table.add_row(GROWTH_ROW_LABEL, *(_format_growth(growth) for growth in growths))
        print_table(console, f"{operation} — {report.problem_name}", table)
    console.print(
        "Counted in one extra untimed run per implementation, distribution and size with a "
        "trace file; the growth row is the fitted growth of the count with the size."
    )


def print_operation_issues(console: Console, report: BenchmarkReport) -> None:
    """Explain each measurement whose counts were left out: a bad trace or an unverified output.

    A counting run that failed is described with the other failures.
    """
    for benchmark in report.implementations:
        for measurement in benchmark.measurements:
            issue = measurement.operation_issue
            if issue is None or issue.kind is OperationIssueKind.COUNTING_FAILED:
                continue
            console.print(
                f"[yellow]{escape(benchmark.implementation.name)} "
                f"({escape(measurement.distribution)}, size {measurement.size:,}): "
                f"no operation counts, {issue.kind.value}:[/yellow] {escape(issue.message)}",
                soft_wrap=True,
            )


def _operation_cell(
    benchmark: ImplementationBenchmark, distribution: str, size: int, operation: str
) -> str:
    """Format one count of one measurement, or say why there is none."""
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


def _median_at(benchmark: ImplementationBenchmark, distribution: str, size: int) -> float | None:
    measurement = benchmark.measurement_at(distribution, size)
    return None if measurement is None else measurement.summary.median


def _comparison_cell(
    median_seconds: float | None,
    reference_median: float | None,
    status: CellStatus,
    unit: _TimeUnit,
) -> str:
    """Format a median with its ratio to the reference.

    A cell that was not measured says ``failed`` when it is where the
    implementation failed, and ``skipped`` when it was never reached.
    """
    if median_seconds is None:
        return FAILED_CELL if status is CellStatus.FAILED else SKIPPED_CELL
    duration = unit.format(median_seconds)
    if reference_median is None or reference_median <= 0 or median_seconds <= 0:
        return duration
    return f"{duration} ({median_seconds / reference_median:.2f}x)"


def print_footer(console: Console, report: BenchmarkReport) -> None:
    startups = [
        benchmark.startup for benchmark in report.implementations if benchmark.startup is not None
    ]
    if not startups:
        return
    if len(report.implementations) == 1:
        if not report.implementations[0].measurements:
            return
        startup = startups[0]
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
    elif report.settings.subtract_startup_time:
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


def print_failures(console: Console, report: BenchmarkReport, *, excluded: Collection[str]) -> None:
    """Print each failure message; failed builds were already reported when they happened.

    The failure of a distribution, which every implementation records, is
    printed once.
    """
    shown_distribution_failures: set[tuple[str | None, str]] = set()
    for benchmark in report.implementations:
        if benchmark.implementation.name in excluded:
            continue
        for failure in benchmark.failures:
            if failure.stage is FailureStage.DISTRIBUTION:
                if (failure.distribution, failure.message) not in shown_distribution_failures:
                    shown_distribution_failures.add((failure.distribution, failure.message))
                    console.print(f"[red]{escape(failure.message)}[/red]", soft_wrap=True)
                continue
            console.print(
                f"[red]{escape(benchmark.implementation.name)} failed:[/red] "
                f"{escape(failure.message)}",
                soft_wrap=True,
            )


def plot_medians(report: BenchmarkReport) -> None:
    distributions = report.settings.distributions
    series: list[ChartSeries] = []
    for benchmark in report.implementations:
        for distribution in distributions:
            points = _plottable_points(benchmark.measurements_for(distribution))
            if points:
                name = benchmark.implementation.name
                series.append(
                    ChartSeries(
                        name=name if len(distributions) == 1 else f"{name} ({distribution})",
                        x_values=tuple(size for size, _ in points),
                        y_values=tuple(median for _, median in points),
                    )
                )
    if not any(len(line.x_values) >= 2 for line in series):
        return
    y_label = "median seconds"
    if report.settings.subtract_startup_time:
        y_label += " (startup subtracted)"
    line_chart(
        series,
        title=f"{report.problem_name}: median wall time against size",
        x_label="size",
        y_label=y_label,
        logarithmic_x=True,
        logarithmic_y=True,
    )


def _plottable_points(measurements: tuple[SizeMeasurement, ...]) -> list[tuple[int, float]]:
    return [
        (measurement.size, measurement.summary.median)
        for measurement in measurements
        if measurement.size > 0 and measurement.summary.median > 0
    ]


def _add_summary_row(table: Table, label: str, summary: TimingSummary, unit: _TimeUnit) -> None:
    table.add_row(
        label,
        unit.format(summary.minimum),
        unit.format(summary.median),
        unit.format(summary.standard_deviation),
        str(summary.count),
    )
