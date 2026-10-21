"""`algorithm-playground benchmark` — measure wall time across sizes with a seeded RNG."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from algorithm_playground.core.problem import Problem
from algorithm_playground.core.registry import get_problem
from algorithm_playground.core.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    Runner,
    RunnerError,
)
from algorithm_playground.core.statistics import (
    TimingSummary,
    format_duration,
    subtract_baseline,
    summarize,
)
from algorithm_playground.visualization import line_chart

STARTUP_ROW_LABEL = "startup (empty input)"


def benchmark_command(
    problem_name: Annotated[
        str, typer.Argument(metavar="PROBLEM", help="Name of the registered problem.")
    ],
    executable: Annotated[
        Path,
        typer.Argument(
            metavar="EXECUTABLE",
            help="Path to the executable that implements the problem's binary contract.",
            exists=True,
            dir_okay=False,
            file_okay=True,
            resolve_path=True,
        ),
    ],
    seed: Annotated[
        int,
        typer.Option(
            "--seed",
            help="Random seed used for all generated benchmark inputs.",
        ),
    ] = 0,
    sizes: Annotated[
        str,
        typer.Option(
            "--sizes",
            help="Comma-separated list of input sizes (e.g. 1000,10000,100000).",
        ),
    ] = "1000,10000,100000",
    repetitions: Annotated[
        int,
        typer.Option(
            "--repetitions",
            min=1,
            help="Number of measured iterations per size.",
        ),
    ] = 5,
    warmup: Annotated[
        int,
        typer.Option(
            "--warmup",
            min=0,
            help="Number of discarded warmup iterations per size.",
        ),
    ] = 1,
    timeout_seconds: Annotated[
        float,
        typer.Option(
            "--timeout",
            min=0.001,
            help="Per-invocation timeout in seconds.",
        ),
    ] = DEFAULT_TIMEOUT_SECONDS,
    verify_outputs: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Verify each measured run's output. Disable to remove verification overhead.",
        ),
    ] = True,
    json_path: Annotated[
        Path | None,
        typer.Option(
            "--json",
            help="Write the full benchmark report to this JSON file.",
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    plot: Annotated[
        bool,
        typer.Option("--plot/--no-plot", help="Draw a terminal plot of size vs. median time."),
    ] = True,
    subtract_startup_time: Annotated[
        bool,
        typer.Option(
            "--subtract-startup-time",
            help=(
                "Subtract the mean wall time of an empty-input run from every sample, "
                "so the results estimate algorithm work rather than process startup."
            ),
        ),
    ] = False,
) -> None:
    """Benchmark ``executable`` against ``problem_name`` across multiple sizes."""
    console = Console()
    try:
        problem = get_problem(problem_name)
    except KeyError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=2) from error

    size_values = _parse_sizes(sizes)
    runner = Runner(problem, executable, timeout_seconds=timeout_seconds)

    table = Table(title=f"benchmark — {problem_name}")
    table.add_column("size", justify="right", no_wrap=True)
    table.add_column("minimum", justify="right")
    table.add_column("median", justify="right")
    table.add_column("standard deviation", justify="right")
    table.add_column("samples", justify="right")

    per_size_results: list[dict[str, Any]] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:

        def measure(input_data: Any, label: str) -> list[float]:
            return _measure_wall_seconds(
                runner,
                problem,
                input_data,
                label=label,
                warmup=warmup,
                repetitions=repetitions,
                verify_outputs=verify_outputs,
                progress=progress,
                console=console,
            )

        startup_case = problem.baseline_case(seed=seed)
        startup_summary = summarize(measure(startup_case.input_data, STARTUP_ROW_LABEL))
        _add_summary_row(table, f"[dim]{STARTUP_ROW_LABEL}[/dim]", startup_summary)
        table.add_section()

        for size in size_values:
            case = problem.benchmark_case(seed=seed, size=size)
            raw_samples = measure(case.input_data, f"size={size}")
            reported_samples = (
                subtract_baseline(raw_samples, startup_summary.mean)
                if subtract_startup_time
                else raw_samples
            )
            summary = summarize(reported_samples)
            per_size_results.append(_size_record(size, case.name, summary, raw_samples))
            _add_summary_row(table, f"{size:,}", summary)

    console.print(table)
    if subtract_startup_time:
        console.print(
            f"Startup time ({format_duration(startup_summary.mean)}, mean of "
            f"{startup_summary.count} empty-input runs) was subtracted from every sample. "
            "Negative values mean the work is below the measurement noise."
        )
    else:
        console.print(
            f"Every sample includes about {format_duration(startup_summary.mean)} of startup "
            "time (the empty-input row). Pass --subtract-startup-time to remove it."
        )

    plottable_results = [
        record for record in per_size_results if record["size"] > 0 and record["median_seconds"] > 0
    ]
    if plot and len(plottable_results) >= 2:
        y_label = "median seconds"
        if subtract_startup_time:
            y_label += " (startup subtracted)"
        line_chart(
            [record["size"] for record in plottable_results],
            [record["median_seconds"] for record in plottable_results],
            title=f"{problem_name}: median wall time vs. size",
            x_label="size",
            y_label=y_label,
            log_x=True,
            log_y=True,
        )

    if json_path is not None:
        report = _build_report(
            problem_name=problem_name,
            executable=executable,
            seed=seed,
            sizes=size_values,
            repetitions=repetitions,
            warmup=warmup,
            timeout_seconds=timeout_seconds,
            subtract_startup_time=subtract_startup_time,
            startup_record=_summary_fields(startup_summary),
            per_size_results=per_size_results,
        )
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True))
        console.print(f"[green]Wrote benchmark report to {json_path}[/green]")


def _parse_sizes(raw: str) -> list[int]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise typer.BadParameter("At least one size must be provided.")
    sizes: list[int] = []
    for part in parts:
        try:
            value = int(part.replace("_", ""))
        except ValueError as error:
            raise typer.BadParameter(f"Could not parse size: {part!r}") from error
        if value < 0:
            raise typer.BadParameter(f"Sizes must be non-negative, got {value}")
        sizes.append(value)
    return sizes


def _measure_wall_seconds(
    runner: Runner[Any, Any, Any],
    problem: Problem[Any, Any, Any],
    input_data: Any,
    *,
    label: str,
    warmup: int,
    repetitions: int,
    verify_outputs: bool,
    progress: Progress,
    console: Console,
) -> list[float]:
    """Run ``warmup`` discarded and ``repetitions`` measured iterations on one input."""
    task_id = progress.add_task(label, total=warmup + repetitions)
    samples: list[float] = []
    try:
        for _ in range(warmup):
            runner.run(input_data, collect_trace=False)
            progress.update(task_id, advance=1)
        for _ in range(repetitions):
            result = runner.run(input_data, collect_trace=False)
            if verify_outputs:
                verification = problem.verify(input_data, result.output)
                if not verification.passed:
                    console.print(
                        f"[red]Verification failed for {label}: {verification.message}[/red]"
                    )
                    raise typer.Exit(code=1)
            samples.append(result.wall_seconds)
            progress.update(task_id, advance=1)
    except RunnerError as error:
        console.print(f"[red]Runner error for {label}:[/red] {error}")
        raise typer.Exit(code=1) from error
    return samples


def _add_summary_row(table: Table, label: str, summary: TimingSummary) -> None:
    table.add_row(
        label,
        format_duration(summary.minimum),
        format_duration(summary.median),
        format_duration(summary.standard_deviation),
        str(summary.count),
    )


def _summary_fields(summary: TimingSummary) -> dict[str, Any]:
    return {
        "samples_seconds": list(summary.samples),
        "minimum_seconds": summary.minimum,
        "median_seconds": summary.median,
        "mean_seconds": summary.mean,
        "standard_deviation_seconds": summary.standard_deviation,
    }


def _size_record(
    size: int, case_name: str, summary: TimingSummary, raw_samples: list[float]
) -> dict[str, Any]:
    # The summary fields describe the reported samples (startup subtracted when
    # requested); raw_samples_seconds always holds the unadjusted wall times.
    return {
        "size": size,
        "case_name": case_name,
        **_summary_fields(summary),
        "raw_samples_seconds": sorted(raw_samples),
    }


def _build_report(
    *,
    problem_name: str,
    executable: Path,
    seed: int,
    sizes: list[int],
    repetitions: int,
    warmup: int,
    timeout_seconds: float,
    subtract_startup_time: bool,
    startup_record: dict[str, Any],
    per_size_results: list[dict[str, Any]],
) -> dict[str, Any]:
    from algorithm_playground import __version__ as package_version

    return {
        "problem": problem_name,
        "executable": {
            "path": str(executable),
            "sha256": _sha256_of_file(executable),
        },
        "configuration": {
            "seed": seed,
            "sizes": sizes,
            "repetitions": repetitions,
            "warmup": warmup,
            "timeout_seconds": timeout_seconds,
            "subtract_startup_time": subtract_startup_time,
        },
        "startup": startup_record,
        "results": per_size_results,
        "host": {
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version,
        },
        "metadata": {
            "algorithm_playground_version": package_version,
            "generated_at": _datetime.datetime.now(tz=_datetime.UTC).isoformat(),
        },
    }


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
