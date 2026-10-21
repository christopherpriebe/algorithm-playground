"""`algorithm-playground benchmark` — measure wall time across sizes and distributions."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from algorithm_playground.cli.benchmark_rendering import (
    plot_medians,
    print_comparison_table,
    print_failures,
    print_footer,
    print_operation_issues,
    print_operation_tables,
    print_single_table,
)
from algorithm_playground.cli.context import CommandContext
from algorithm_playground.cli.options import (
    BuildOption,
    CommandOption,
    ConfigurationOption,
    ImplementationsArgument,
    InheritEnvironmentOption,
    NameOption,
    ProblemModuleOption,
    json_option,
    timeout_option,
)
from algorithm_playground.cli.rendering import progress_display
from algorithm_playground.core.benchmarking import (
    BenchmarkFailure,
    BenchmarkPhase,
    BenchmarkProgress,
    BenchmarkSettings,
    FailureStage,
    include_failed_implementations,
    run_benchmark,
    total_runs,
)
from algorithm_playground.core.cases import CaseError, check_sizes, select_generators
from algorithm_playground.core.problem import Problem, has_trace_format
from algorithm_playground.core.report import benchmark_report_to_json
from algorithm_playground.core.runner import DEFAULT_TIMEOUT_SECONDS


def benchmark_command(
    problem_name: Annotated[
        str, typer.Argument(metavar="PROBLEM", help="Name of the registered problem.")
    ],
    selectors: ImplementationsArgument = None,
    command_texts: CommandOption = None,
    command_names: NameOption = None,
    configuration_path: ConfigurationOption = None,
    problem_modules: ProblemModuleOption = None,
    build: BuildOption = True,
    inherit_environment: InheritEnvironmentOption = False,
    reference: Annotated[
        str | None,
        typer.Option(
            "--reference",
            help=(
                "Name of the implementation that ratios are computed against when several "
                "are compared (default: the first one that is built and can be started)."
            ),
        ),
    ] = None,
    distributions: Annotated[
        list[str] | None,
        typer.Option(
            "--distribution",
            help=(
                "Name of an input distribution to measure. May be repeated "
                "(default: the problem's default distribution only)."
            ),
        ),
    ] = None,
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
            help="Comma-separated list of input sizes (for example 1000,10000,100000).",
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
        float, timeout_option("Per-invocation timeout in seconds.")
    ] = DEFAULT_TIMEOUT_SECONDS,
    verify_outputs: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Verify each measured run's output. Disable to remove verification overhead.",
        ),
    ] = True,
    json_path: Annotated[
        Path | None, json_option("Write the full benchmark report to this JSON file.")
    ] = None,
    plot: Annotated[
        bool,
        typer.Option(
            "--plot/--no-plot",
            help="Draw a terminal plot of size against median time (only on a terminal).",
        ),
    ] = True,
    count_operations: Annotated[
        bool,
        typer.Option(
            "--count-operations",
            help=(
                "After the timed runs of every distribution and size, run each implementation "
                "once more with a trace file, untimed, and report the operations it counted "
                "(for sorting: compares, swaps, writes) with their growth. An implementation "
                "that writes no trace shows 'not reported'. Has no effect for a problem "
                "without a trace format."
            ),
        ),
    ] = False,
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
    """Benchmark each selected implementation against ``problem_name`` across multiple sizes."""
    context = CommandContext(configuration_path, problem_modules)
    problem = context.get_problem(problem_name)
    context.check_json_path(json_path)

    parsed_sizes = _parse_sizes(sizes)
    try:
        check_sizes(problem, parsed_sizes)
    except CaseError as error:
        context.fail(str(error))
    counting_operations = count_operations and has_trace_format(problem)
    if count_operations and not counting_operations:
        context.warn(
            f"The problem '{problem.name}' does not define operation counts (it has no trace "
            "format), so --count-operations has no effect."
        )
    settings = BenchmarkSettings(
        seed=seed,
        sizes=parsed_sizes,
        repetitions=repetitions,
        warmup=warmup,
        timeout_seconds=timeout_seconds,
        verify_outputs=verify_outputs,
        subtract_startup_time=subtract_startup_time,
        distributions=_distribution_names(context, problem, distributions or ()),
        count_operations=counting_operations,
    )
    selected = context.select_implementations(
        problem_name,
        selectors=selectors,
        command_texts=command_texts,
        command_names=command_names,
        inherit_environment=inherit_environment,
    )
    names = [implementation.name for implementation in selected]
    if reference is not None and reference not in names:
        listing = ", ".join(f"'{name}'" for name in names)
        context.fail(f"Unknown reference '{reference}'. Selected implementations: {listing}.")
    outcome = context.build(selected, build=build)
    reference_name = reference if reference is not None else outcome.ready[0].name

    with progress_display(context.error_console, with_bar=True) as progress:
        task_identifier = progress.add_task(
            "benchmarking", total=total_runs(settings, len(outcome.ready))
        )

        def show_progress(event: BenchmarkProgress) -> None:
            if event.completed:
                progress.update(task_identifier, advance=1)
                return
            if event.phase is BenchmarkPhase.STARTUP:
                where = "startup"
            else:
                where = f"{event.distribution}, size {event.size:,}"
                if event.phase is BenchmarkPhase.OPERATION_COUNT:
                    where += ", counting operations"
            description = f"benchmarking {event.implementation_name} ({where})"
            progress.update(task_identifier, description=escape(description))

        measured_report = run_benchmark(problem, outcome.ready, settings, on_progress=show_progress)
    report = include_failed_implementations(
        measured_report,
        selected,
        {
            **{
                name: BenchmarkFailure(FailureStage.BUILD, str(error))
                for name, error in outcome.failures.items()
            },
            **{
                name: BenchmarkFailure(FailureStage.CANNOT_RUN, f"Cannot run: {reason}")
                for name, reason in outcome.unrunnable.items()
            },
        },
    )

    console = context.console
    if len(report.implementations) == 1:
        print_single_table(console, report)
    else:
        print_comparison_table(console, report, reference_name)
    if settings.count_operations:
        print_operation_tables(console, report)
        print_operation_issues(console, report)
    print_footer(console, report)
    print_failures(console, report, excluded=outcome.unavailable)
    if plot and console.is_terminal:
        plot_medians(report)

    if json_path is not None:
        context.write_json(json_path, benchmark_report_to_json(report), label="benchmark report")

    if not report.passed:
        raise typer.Exit(code=1)


def _distribution_names(
    context: CommandContext, problem: Problem[Any, Any, Any], names: Sequence[str]
) -> tuple[str, ...]:
    """Return the distribution names to measure, each once; exit if the problem lacks one."""
    unique = tuple(dict.fromkeys(names))
    try:
        select_generators(problem, unique)
    except CaseError as error:
        context.fail(str(error))
    return unique


def _parse_sizes(raw: str) -> tuple[int, ...]:
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
    repeated = sorted({size for size in sizes if sizes.count(size) > 1})
    if repeated:
        listing = ", ".join(str(size) for size in repeated)
        raise typer.BadParameter(f"Sizes must be unique, but these were repeated: {listing}")
    return tuple(sizes)
