"""`algorithm-playground debug`: step through an implementation's trace output."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from algorithm_playground.cli._context import FAILURE_EXIT_CODE, CommandContext
from algorithm_playground.cli._dependencies import CommandDependencies
from algorithm_playground.cli._options import (
    BuildOption,
    CommandOption,
    ConfigurationOption,
    ImplementationArgument,
    InheritEnvironmentOption,
    NameOption,
    ProblemModuleOption,
    build_timeout_option,
    choose_environment_policy,
)
from algorithm_playground.cli._test_rendering import (
    description_limit,
    print_failure_detail,
)
from algorithm_playground.core._cases import (
    CaseError,
    FixtureOrigin,
    check_sizes,
    generate_case,
    select_generators,
)
from algorithm_playground.core._description import describe_error
from algorithm_playground.core._frames import Frame
from algorithm_playground.core._problem import AnyProblem, has_trace_format
from algorithm_playground.core._runner import (
    DEFAULT_TIMEOUT_SECONDS,
    Runner,
    RunnerLike,
    RunResult,
)
from algorithm_playground.core._single_run import (
    CaseStatus,
    SingleRun,
    run_single,
    run_single_with_trace,
)
from algorithm_playground.core._testing import describe_failure
from algorithm_playground.visualization._stepper import (
    StepperOptions,
    show_frame,
)

__all__ = ["debug_command"]

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


def _read_input_file(
    context: CommandContext, problem: AnyProblem, path: Path
) -> object:
    """Read a saved input with the problem's ``deserialize_input``; a failure is a usage error.

    Returns:
        The deserialized input.
    """
    try:
        return problem.deserialize_input(path)
    except NotImplementedError as error:
        context.fail(f"--input-file cannot be used: {error}.")
    # The hook is the problem's own code, so whatever it raises means the file cannot be read.
    except Exception as error:  # noqa: BLE001  the hook is the problem's own code
        context.fail(
            f"Could not read {path} as an input of problem '{problem.name}': "
            f"{describe_error(error)}"
        )


def _run_implementation(
    problem: AnyProblem, runner: RunnerLike, case_input: object
) -> SingleRun:
    """Run once, collecting the trace when the problem has a trace format.

    Returns:
        The single run, with its trace when the problem has a trace format.
    """
    if has_trace_format(problem):
        return run_single_with_trace(problem, runner, case_input)
    return run_single(problem, runner, case_input)


def _require_result(
    context: CommandContext, run: SingleRun
) -> RunResult[object, object]:
    """Return the result of the run; exit if the implementation produced none.

    Returns:
        The result of the run.

    Raises:
        typer.Exit: With the failure code if the run produced no result.
    """
    if run.result is None:
        context.error_console.print(
            f"[red]Runner error:[/red] {escape(run.message)}", soft_wrap=True
        )
        raise typer.Exit(code=FAILURE_EXIT_CODE)
    return run.result


def _check_input_options(context: CommandContext, request: "_InputRequest") -> None:
    naming = request.naming_options()
    if len(naming) > 1:
        context.fail(f"{' and '.join(naming)} cannot be used together.")
    generating = request.generating_options()
    if naming and generating:
        context.fail(
            f"{naming[0]} selects an exact input, so it cannot be combined with "
            + ", ".join(generating)
        )


def _generate_input(
    context: CommandContext, problem: AnyProblem, request: "_InputRequest"
) -> object:
    """Generate an input from the named distribution, else the problem's ``debug_generator``.

    Without either, the problem's default generator is used.

    Returns:
        The generated input.
    """
    size = (
        max(DEFAULT_SIZE, problem.minimum_size)
        if request.size is None
        else request.size
    )
    name = (
        request.distribution
        if request.distribution is not None
        else problem.debug_generator
    )
    try:
        generator = select_generators(problem, (name,) if name is not None else ())[0]
        check_sizes(problem, (size,))
        return generate_case(generator, size=size, seed=request.seed or 0).input_data
    except CaseError as error:
        context.fail(str(error))


def _select_input(
    context: CommandContext, problem: AnyProblem, request: "_InputRequest"
) -> object:
    """Return the input to run: the named fixture, case or file, else a generated one.

    The options that generate an input cannot be combined with those that name one.

    Returns:
        The input to run.
    """
    _check_input_options(context, request)
    if request.fixture is not None:
        return context.resolve_case(
            problem, FixtureOrigin(request.fixture).identifier
        ).input_data
    if request.case_identifier is not None:
        return context.resolve_case(problem, request.case_identifier).input_data
    if request.input_file is not None:
        return _read_input_file(context, problem, request.input_file)
    return _generate_input(context, problem, request)


@dataclass(frozen=True, slots=True)
class _InputRequest:
    """The options that choose or generate the input to run."""

    fixture: str | None
    case_identifier: str | None
    input_file: Path | None
    size: int | None
    seed: int | None
    distribution: str | None

    def naming_options(self) -> list[str]:
        """Return the options given that name an exact input."""
        return [
            option
            for option, value in (
                ("--fixture", self.fixture),
                ("--case", self.case_identifier),
                ("--input-file", self.input_file),
            )
            if value is not None
        ]

    def generating_options(self) -> list[str]:
        """Return the options given that shape a generated input."""
        return [
            option
            for option, value in (
                ("--seed", self.seed),
                ("--size", self.size),
                ("--distribution", self.distribution),
            )
            if value is not None
        ]


@dataclass(frozen=True, slots=True)
class _DebugSession:
    """The problem and the input of one debug run, and how to show what the run produced."""

    context: CommandContext
    problem: AnyProblem
    case_input: object

    def print_verification(self, run: SingleRun) -> None:
        """Say whether the output verified and, if not, describe the failure.

        Args:
            run: The run that was made.
        """
        if run.status is CaseStatus.PASSED:
            self.context.console.print("[green]Output verified.[/green]")
            return
        error_console = self.context.error_console
        label = (
            "Output did not verify"
            if run.status is CaseStatus.FAILED
            else "Output not checked"
        )
        error_console.print(
            f"[red]{label}:[/red] {escape(run.message)}", soft_wrap=True
        )
        print_failure_detail(
            error_console,
            describe_failure(
                self.problem, self.case_input, run, description_limit(error_console)
            ),
        )

    def show_result(
        self, result: RunResult[object, object], stepper_options: StepperOptions
    ) -> None:
        """Step through the trace, or show the input and the output when there is no usable trace.

        Args:
            result: The result of the run.
            stepper_options: How to advance through the frames.
        """
        if not has_trace_format(self.problem):
            notice = NO_TRACE_FORMAT_NOTICE.format(problem_name=self.problem.name)
            self.context.error_console.print(
                f"[yellow]{escape(notice)}[/yellow]", soft_wrap=True
            )
            self._show_input_output(result.output)
        elif result.trace is None:
            self._show_unusable_trace(result)
        else:
            self._step_through(result.output, result.trace, stepper_options)

    def _collect_frames(
        self, output: object, trace: object
    ) -> tuple[Sequence[Frame], int]:
        frames = self.problem.trace_frames(self.case_input, output, trace)
        return frames, len(frames)

    def _collect_notices(self, output: object, trace: object) -> list[str]:
        return [
            f"Trace warning: {warning}"
            for warning in self.problem.trace_warnings(self.case_input, output, trace)
        ]

    def _show_input_output(self, output: object) -> None:
        """Show the problem's view of the input and the output, when it has one."""

        def show() -> None:
            frame = self.problem.input_output_frame(self.case_input, output)
            if frame is not None:
                show_frame(self.context.console, frame)

        self.context.call_hook("input_output_frame", show)

    def _show_unusable_trace(self, result: RunResult[object, object]) -> None:
        error_console = self.context.error_console
        if result.trace_error is not None:
            error_console.print(
                f"[red]Trace file is malformed:[/red] {escape(result.trace_error)}",
                soft_wrap=True,
            )
        error_console.print(f"[yellow]{NO_TRACE_HINT}[/yellow]")
        self._show_input_output(result.output)

    def _step_through(
        self, output: object, trace: object, stepper_options: StepperOptions
    ) -> None:
        frames, frame_count = self.context.call_hook(
            "trace_frames", lambda: self._collect_frames(output, trace)
        )
        if frame_count == 0:
            self.context.error_console.print(f"[yellow]{NO_FRAMES_HINT}[/yellow]")
            self._show_input_output(output)
            return
        notices = self.context.call_hook(
            "trace_warnings", lambda: self._collect_notices(output, trace)
        )
        try:
            self.context.dependencies.step_through(
                frames,
                options=stepper_options,
                header=f"{self.problem.name} trace",
                notices=notices,
            )
        # The frames come from the problem's own code, so drawing one can raise anything.
        except Exception as error:  # noqa: BLE001  drawing runs the problem's own code
            self.context.fail(
                f"A frame of the trace could not be drawn: the problem's trace_frames hook "
                f"raised {describe_error(error)}.",
                code=FAILURE_EXIT_CODE,
            )


def debug_command(  # noqa: PLR0913  every Typer option is a parameter
    click_context: typer.Context,
    problem_name: Annotated[
        str, typer.Argument(metavar="PROBLEM", help="Name of the registered problem.")
    ],
    *,
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
        float, build_timeout_option("Per-invocation timeout in seconds.")
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run one implementation on a single input and step through its trace output.

    Args:
        click_context: The Click context; its object holds the collaborators to call.
        problem_name: The name of the registered problem.
        implementation_selector: The name or path of the implementation to run.
        command_texts: The ``--command`` value naming the implementation.
        command_names: The ``--name`` value for the command.
        configuration_path: The configuration file to read.
        problem_modules: Python modules or files that register problems.
        build: Whether to run the implementation's build command first.
        inherit_environment: Whether to give the implementation the full environment.
        seed: The seed of a generated input.
        size: The size of a generated input.
        distribution: The distribution of a generated input.
        fixture: The fixture to use as the input.
        case_identifier: The case to use as the input.
        input_file: A saved binary input to use as the input.
        auto_advance: Whether to advance through trace frames automatically.
        delay_milliseconds: The delay between frames when advancing automatically.
        timeout_seconds: The timeout of the run.

    Raises:
        typer.Exit: With a nonzero code if the run or its verification failed.
    """
    context = CommandContext(
        configuration_path,
        problem_modules,
        dependencies=click_context.ensure_object(CommandDependencies),
    )
    problem = context.get_problem(problem_name)
    selected = context.select_implementations(
        problem_name,
        selectors=[implementation_selector]
        if implementation_selector is not None
        else None,
        command_texts=command_texts,
        command_names=command_names,
        environment_policy=choose_environment_policy(
            inherit_environment=inherit_environment
        ),
    )
    implementation = context.require_single(selected, command_name="debug")
    case_input = _select_input(
        context,
        problem,
        _InputRequest(
            fixture=fixture,
            case_identifier=case_identifier,
            input_file=input_file,
            size=size,
            seed=seed,
            distribution=distribution,
        ),
    )
    if build:
        context.build_and_check(selected)
    else:
        context.check_startable(selected)

    runner = Runner(problem, implementation, timeout_seconds=timeout_seconds)
    run = _run_implementation(problem, runner, case_input)
    result = _require_result(context, run)
    session = _DebugSession(context, problem, case_input)
    session.print_verification(run)
    session.show_result(
        result,
        StepperOptions(
            auto_advance=auto_advance, delay_milliseconds=delay_milliseconds
        ),
    )
    if run.status is not CaseStatus.PASSED:
        raise typer.Exit(code=FAILURE_EXIT_CODE)
