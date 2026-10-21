"""`algorithm-playground debug` — step through an implementation's trace output."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from algorithm_playground.cli.context import FAILURE_EXIT_CODE, CommandContext
from algorithm_playground.cli.options import (
    BuildOption,
    CommandOption,
    ConfigurationOption,
    ImplementationArgument,
    InheritEnvironmentOption,
    NameOption,
    ProblemModuleOption,
    timeout_option,
)
from algorithm_playground.cli.test_rendering import description_limit, print_failure_detail
from algorithm_playground.core._support import describe_error
from algorithm_playground.core.cases import (
    CaseError,
    FixtureOrigin,
    check_sizes,
    generate_case,
    select_generators,
)
from algorithm_playground.core.frames import Frame
from algorithm_playground.core.problem import Problem, has_trace_format
from algorithm_playground.core.runner import DEFAULT_TIMEOUT_SECONDS, Runner
from algorithm_playground.core.single_run import CaseStatus, run_single
from algorithm_playground.core.testing import describe_failure
from algorithm_playground.visualization.stepper import StepperOptions, show_frame, step_through

DEFAULT_SIZE = 16

NO_TRACE_FORMAT_NOTICE = (
    "The problem '{problem_name}' has no trace format, so there is no trace to step through. "
    "Showing the input and the output instead."
)
NO_TRACE_HINT = (
    "The implementation did not produce a usable trace file. To enable debug "
    "visualization, accept an optional third path after the input and output "
    "paths and write the problem's binary trace format to it. Falling back to "
    "input/output visualization."
)
NO_FRAMES_HINT = (
    "The trace has no frames to step through (an empty trace, or a problem that "
    "draws none). Falling back to input/output visualization."
)


def debug_command(
    problem_name: Annotated[
        str, typer.Argument(metavar="PROBLEM", help="Name of the registered problem.")
    ],
    implementation_selector: ImplementationArgument = None,
    command_texts: CommandOption = None,
    command_names: NameOption = None,
    configuration_path: ConfigurationOption = None,
    problem_modules: ProblemModuleOption = None,
    build: BuildOption = True,
    inherit_environment: InheritEnvironmentOption = False,
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed",
            help=(
                "Random seed used to generate the input (default: 0). Cannot be combined with "
                "--fixture, --case or --input-file."
            ),
        ),
    ] = None,
    size: Annotated[
        int | None,
        typer.Option(
            "--size",
            min=0,
            help=(
                f"Input size to generate (default: {DEFAULT_SIZE}, or the problem's smallest size "
                "if that is larger). Cannot be combined with --fixture, --case or --input-file."
            ),
        ),
    ] = None,
    distribution: Annotated[
        str | None,
        typer.Option(
            "--distribution",
            help=(
                "Name of the input distribution to generate from (default: the one the problem "
                "prefers for debugging, else its default). Cannot be combined with --fixture, "
                "--case or --input-file."
            ),
        ),
    ] = None,
    fixture: Annotated[
        str | None,
        typer.Option(
            "--fixture",
            help="Use the named fixture as the input instead of generating one.",
        ),
    ] = None,
    case_identifier: Annotated[
        str | None,
        typer.Option(
            "--case",
            help=(
                "Use the case with this identifier, for example "
                "generated:uniform:size=37:seed=1234567, as the input."
            ),
        ),
    ] = None,
    input_file: Annotated[
        Path | None,
        typer.Option(
            "--input-file",
            metavar="PATH",
            help=(
                "Use the input in this file, in the problem's binary input format (written by "
                "'test --save-failing-inputs'), as the input. The problem must be able to read it."
            ),
            exists=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    auto_advance: Annotated[
        bool,
        typer.Option(
            "--auto-advance",
            help="Advance through trace frames automatically (with --delay-milliseconds).",
        ),
    ] = False,
    delay_milliseconds: Annotated[
        int,
        typer.Option(
            "--delay-milliseconds",
            min=0,
            help="Delay between frames when --auto-advance is set.",
        ),
    ] = 250,
    timeout_seconds: Annotated[
        float, timeout_option("Per-invocation timeout in seconds.")
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run one implementation on a single input and step through its trace output."""
    context = CommandContext(configuration_path, problem_modules)
    problem = context.get_problem(problem_name)

    selected = context.select_implementations(
        problem_name,
        selectors=[implementation_selector] if implementation_selector is not None else None,
        command_texts=command_texts,
        command_names=command_names,
        inherit_environment=inherit_environment,
    )
    implementation = context.require_single(selected, command_name="debug")
    case_input = _input_data(
        context,
        problem,
        fixture=fixture,
        case_identifier=case_identifier,
        input_file=input_file,
        size=size,
        seed=seed,
        distribution=distribution,
    )
    context.build(selected, build=build)

    has_trace = has_trace_format(problem)
    runner = Runner(problem, implementation, timeout_seconds=timeout_seconds)
    run = run_single(problem, runner, case_input, collect_trace=has_trace)
    result = run.result
    if result is None:
        context.error_console.print(
            f"[red]Runner error:[/red] {escape(run.message)}", soft_wrap=True
        )
        raise typer.Exit(code=1)

    if run.status is CaseStatus.PASSED:
        context.console.print("[green]Output verified.[/green]")
    else:
        label = "Output did not verify" if run.status is CaseStatus.FAILED else "Output not checked"
        context.error_console.print(f"[red]{label}:[/red] {escape(run.message)}", soft_wrap=True)
        print_failure_detail(
            context.error_console,
            describe_failure(problem, case_input, run, description_limit(context.error_console)),
        )

    output = result.output
    if not has_trace:
        notice = NO_TRACE_FORMAT_NOTICE.format(problem_name=problem.name)
        context.error_console.print(f"[yellow]{escape(notice)}[/yellow]", soft_wrap=True)
        _show_input_output(context, problem, case_input, output)
    elif result.trace is None:
        if result.trace_error is not None:
            context.error_console.print(
                f"[red]Trace file is malformed:[/red] {escape(result.trace_error)}", soft_wrap=True
            )
        context.error_console.print(f"[yellow]{NO_TRACE_HINT}[/yellow]")
        _show_input_output(context, problem, case_input, output)
    else:
        trace = result.trace

        def collect_frames() -> tuple[Sequence[Frame], int]:
            frames = problem.trace_frames(case_input, output, trace)
            return frames, len(frames)

        frames, frame_count = context.call_hook("trace_frames", collect_frames)
        if frame_count == 0:
            context.error_console.print(f"[yellow]{NO_FRAMES_HINT}[/yellow]")
            _show_input_output(context, problem, case_input, output)
        else:
            notices = context.call_hook(
                "trace_warnings",
                lambda: [
                    f"Trace warning: {warning}"
                    for warning in problem.trace_warnings(case_input, output, trace)
                ],
            )
            try:
                step_through(
                    frames,
                    options=StepperOptions(
                        auto_advance=auto_advance, delay_milliseconds=delay_milliseconds
                    ),
                    header=f"{problem.name} trace",
                    notices=notices,
                )
            except Exception as error:
                context.fail(
                    f"A frame of the trace could not be drawn: the problem's trace_frames hook "
                    f"raised {describe_error(error)}.",
                    code=FAILURE_EXIT_CODE,
                )

    if run.status is not CaseStatus.PASSED:
        raise typer.Exit(code=FAILURE_EXIT_CODE)


def _show_input_output(
    context: CommandContext, problem: Problem[Any, Any, Any], input_data: Any, output: Any
) -> None:
    """Show the problem's view of the input and the output, when it has one."""

    def show() -> None:
        frame = problem.input_output_frame(input_data, output)
        if frame is not None:
            show_frame(context.console, frame)

    context.call_hook("input_output_frame", show)


def _input_data(
    context: CommandContext,
    problem: Problem[Any, Any, Any],
    *,
    fixture: str | None,
    case_identifier: str | None,
    input_file: Path | None,
    size: int | None,
    seed: int | None,
    distribution: str | None,
) -> Any:
    """Return the input to run: the named fixture, case or file, else a generated one.

    A generated input comes from the named distribution, else from the problem's
    ``debug_generator``, else from its default generator. The options that
    generate an input cannot be combined with those that name one.
    """
    given = [
        option
        for option, value in (
            ("--fixture", fixture),
            ("--case", case_identifier),
            ("--input-file", input_file),
        )
        if value is not None
    ]
    if len(given) > 1:
        context.fail(f"{' and '.join(given)} cannot be used together.")
    if given:
        generating = [
            option
            for option, value in (
                ("--seed", seed),
                ("--size", size),
                ("--distribution", distribution),
            )
            if value is not None
        ]
        if generating:
            context.fail(
                f"{given[0]} selects an exact input, so it cannot be combined with "
                + ", ".join(generating)
            )
    if fixture is not None:
        return context.resolve_case(problem, FixtureOrigin(fixture).identifier).input_data
    if case_identifier is not None:
        return context.resolve_case(problem, case_identifier).input_data
    if input_file is not None:
        return _read_input_file(context, problem, input_file)
    chosen_size = max(DEFAULT_SIZE, problem.minimum_size) if size is None else size
    name = distribution if distribution is not None else problem.debug_generator
    try:
        generator = select_generators(problem, (name,) if name is not None else ())[0]
        check_sizes(problem, (chosen_size,))
        return generate_case(generator, size=chosen_size, seed=seed or 0).input_data
    except CaseError as error:
        context.fail(str(error))


def _read_input_file(context: CommandContext, problem: Problem[Any, Any, Any], path: Path) -> Any:
    """Read a saved input with the problem's ``deserialize_input``; a failure is a usage error."""
    try:
        return problem.deserialize_input(path)
    except NotImplementedError as error:
        context.fail(f"--input-file cannot be used: {error}.")
    except Exception as error:
        context.fail(
            f"Could not read {path} as an input of problem '{problem.name}': "
            f"{describe_error(error)}"
        )
