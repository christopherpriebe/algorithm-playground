"""`algorithm-playground benchmark`: measure wall time across sizes and distributions."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
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
from algorithm_playground.cli.context import FAILURE_EXIT_CODE, BuildOutcome, CommandContext
from algorithm_playground.cli.options import (
    BuildOption,
    CommandOption,
    ConfigurationOption,
    ImplementationsArgument,
    InheritEnvironmentOption,
    NameOption,
    ProblemModuleOption,
    build_json_option,
    build_timeout_option,
    choose_environment_policy,
)
from algorithm_playground.cli.rendering import create_progress_display_with_bar
from algorithm_playground.core.benchmarking import (
    BenchmarkFailure,
    BenchmarkPhase,
    BenchmarkProgress,
    BenchmarkReport,
    BenchmarkSettings,
    FailureStage,
    include_failed_implementations,
    run_benchmark,
    total_runs,
)
from algorithm_playground.core.cases import CaseError, check_sizes, select_generators
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import AnyProblem, has_trace_format
from algorithm_playground.core.report import benchmark_report_to_json
from algorithm_playground.core.runner import DEFAULT_TIMEOUT_SECONDS

__all__ = ["benchmark_command"]


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


def _check_problem_sizes(
    context: CommandContext, problem: AnyProblem, sizes: Sequence[int]
) -> None:
    try:
        check_sizes(problem, sizes)
    except CaseError as error:
        context.fail(str(error))


def _select_distribution_names(
    context: CommandContext, problem: AnyProblem, names: Sequence[str]
) -> tuple[str, ...]:
    """Return the distribution names to measure, each once; exit if the problem lacks one."""
    unique = tuple(dict.fromkeys(names))
    try:
        select_generators(problem, unique)
    except CaseError as error:
        context.fail(str(error))
    return unique


def _check_reference(
    context: CommandContext, reference: str | None, selected: Sequence[Implementation]
) -> None:
    names = [implementation.name for implementation in selected]
    if reference is not None and reference not in names:
        listing = ", ".join(f"'{name}'" for name in names)
        context.fail(f"Unknown reference '{reference}'. Selected implementations: {listing}.")


def _describe_progress(event: BenchmarkProgress) -> str:
    if event.phase is BenchmarkPhase.STARTUP:
        where = "startup"
    else:
        where = f"{event.distribution}, size {event.size:,}"
        if event.phase is BenchmarkPhase.OPERATION_COUNT:
            where += ", counting operations"
    return f"benchmarking {event.implementation_name} ({where})"


def _measure_with_progress(
    context: CommandContext,
    problem: AnyProblem,
    *,
    implementations: Sequence[Implementation],
    settings: BenchmarkSettings,
) -> BenchmarkReport:
    with create_progress_display_with_bar(context.error_console) as progress:
        task_identifier = progress.add_task(
            "benchmarking", total=total_runs(settings, len(implementations))
        )

        def show_progress(event: BenchmarkProgress) -> None:
            if event.completed:
                progress.update(task_identifier, advance=1)
            else:
                progress.update(task_identifier, description=escape(_describe_progress(event)))

        return run_benchmark(problem, implementations, settings, on_progress=show_progress)


def _include_failures(
    report: BenchmarkReport, selected: Sequence[Implementation], outcome: BuildOutcome
) -> BenchmarkReport:
    """Add the implementations that did not build or cannot start to the measured report."""
    failures = {
        **{
            name: BenchmarkFailure(FailureStage.BUILD, str(error))
            for name, error in outcome.failures.items()
        },
        **{
            name: BenchmarkFailure(FailureStage.CANNOT_RUN, f"Cannot run: {reason}")
            for name, reason in outcome.unrunnable.items()
        },
    }
    return include_failed_implementations(report, selected, failures)


def _print_report(
    console: Console, report: BenchmarkReport, *, reference_name: str, outcome: BuildOutcome
) -> None:
    if len(report.implementations) == 1:
        print_single_table(console, report)
    else:
        print_comparison_table(console, report, reference_name)
    if report.settings.count_operations:
        print_operation_tables(console, report)
        print_operation_issues(console, report)
    print_footer(console, report)
    print_failures(console, report, excluded=outcome.unavailable)


def _build_settings(
    context: CommandContext, problem: AnyProblem, options: "_MeasurementOptions"
) -> BenchmarkSettings:
    """Check the options against the problem and turn them into the settings of the benchmark."""
    sizes = _parse_sizes(options.sizes)
    _check_problem_sizes(context, problem, sizes)
    counting_operations = options.count_operations and has_trace_format(problem)
    if options.count_operations and not counting_operations:
        context.warn(
            f"The problem '{problem.name}' does not define operation counts (it has no trace "
            "format), so --count-operations has no effect."
        )
    return BenchmarkSettings(
        seed=options.seed,
        sizes=sizes,
        repetitions=options.repetitions,
        warmup=options.warmup,
        timeout_seconds=options.timeout_seconds,
        verify_outputs=options.verify_outputs,
        subtract_startup_time=options.subtract_startup_time,
        distributions=_select_distribution_names(context, problem, options.distributions),
        count_operations=counting_operations,
    )


@dataclass(frozen=True)
class _MeasurementOptions:
    """The options that say what is measured and how, as the user typed them."""

    seed: int
    sizes: str
    repetitions: int
    warmup: int
    timeout_seconds: float
    verify_outputs: bool
    subtract_startup_time: bool
    distributions: tuple[str, ...]
    count_operations: bool


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
        float, build_timeout_option("Per-invocation timeout in seconds.")
    ] = DEFAULT_TIMEOUT_SECONDS,
    verify_outputs: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Verify each measured run's output. Disable to remove verification overhead.",
        ),
    ] = True,
    json_path: Annotated[
        Path | None, build_json_option("Write the full benchmark report to this JSON file.")
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
    """Benchmark each selected implementation against a problem across multiple sizes.

    Args:
        problem_name: The name of the registered problem.
        selectors: The names or paths of the implementations to benchmark.
        command_texts: The ``--command`` values naming implementations.
        command_names: The ``--name`` values for the commands.
        configuration_path: The configuration file to read.
        problem_modules: Python modules or files that register problems.
        build: Whether to run each implementation's build command first.
        inherit_environment: Whether to give implementations the full environment.
        reference: The implementation that ratios are computed against.
        distributions: The input distributions to measure.
        seed: The seed of the generated inputs.
        sizes: The comma-separated input sizes.
        repetitions: The measured iterations per size.
        warmup: The discarded warmup iterations per size.
        timeout_seconds: The timeout of each invocation.
        verify_outputs: Whether to verify the output of each measured run.
        json_path: Where to write the full report as JSON.
        plot: Whether to draw a terminal plot of the medians.
        count_operations: Whether to count operations from a trace in an extra run.
        subtract_startup_time: Whether to subtract the startup time from every sample.

    Raises:
        typer.Exit: With the failure code if any implementation failed.
    """
    context = CommandContext(configuration_path, problem_modules)
    problem = context.get_problem(problem_name)
    context.check_json_path(json_path)
    settings = _build_settings(
        context,
        problem,
        _MeasurementOptions(
            seed=seed,
            sizes=sizes,
            repetitions=repetitions,
            warmup=warmup,
            timeout_seconds=timeout_seconds,
            verify_outputs=verify_outputs,
            subtract_startup_time=subtract_startup_time,
            distributions=tuple(distributions or ()),
            count_operations=count_operations,
        ),
    )
    selected = context.select_implementations(
        problem_name,
        selectors=selectors,
        command_texts=command_texts,
        command_names=command_names,
        environment_policy=choose_environment_policy(inherit_environment),
    )
    _check_reference(context, reference, selected)
    outcome = context.build_and_check(selected) if build else context.check_startable(selected)

    measured_report = _measure_with_progress(
        context, problem, implementations=outcome.ready, settings=settings
    )
    report = _include_failures(measured_report, selected, outcome)
    reference_name = reference if reference is not None else outcome.ready[0].name
    _print_report(context.console, report, reference_name=reference_name, outcome=outcome)
    if plot and context.console.is_terminal:
        plot_medians(report)
    if json_path is not None:
        context.write_json(json_path, benchmark_report_to_json(report), label="benchmark report")

    if not report.has_passed:
        raise typer.Exit(code=FAILURE_EXIT_CODE)
