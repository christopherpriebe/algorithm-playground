"""`algorithm-playground test`: run implementations against fixtures and generated cases."""

# ruff: noqa: PT028  `test_command` is a Typer command, not a test, and Typer needs the defaults

import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from algorithm_playground.cli._context import (
    FAILURE_EXIT_CODE,
    BuildOutcome,
    CommandContext,
)
from algorithm_playground.cli._dependencies import CommandDependencies
from algorithm_playground.cli._implementation_selection import build_selection_arguments
from algorithm_playground.cli._options import (
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
from algorithm_playground.cli._rendering import create_progress_display
from algorithm_playground.cli._test_rendering import (
    description_limit,
    print_expanded_matrix,
    print_failure_details,
    print_matrix,
    print_summaries,
)
from algorithm_playground.core._cases import (
    DEFAULT_RANDOM_CASE_COUNT,
    AnyCase,
    CaseError,
    CasePlan,
    FixtureOrigin,
    build_cases,
    select_generators,
)
from algorithm_playground.core._configuration import Configuration
from algorithm_playground.core._dimensions import build_default_maximum_size
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._problem import AnyProblem
from algorithm_playground.core._report import convert_correctness_report_to_json
from algorithm_playground.core._runner import (
    DEFAULT_TIMEOUT_SECONDS,
    TemporaryFilePolicy,
)
from algorithm_playground.core._saved_inputs import SavedInputs, save_failing_inputs
from algorithm_playground.core._testing import (
    CasePhase,
    CaseProgress,
    ShrinkOptions,
    TestReport,
    TestRunOptions,
)

__all__ = ["DEFAULT_MAXIMUM_FAILURES", "test_command"]

DEFAULT_MAXIMUM_FAILURES = 5


def _describe_progress(event: CaseProgress) -> str:
    verb = "shrinking" if event.phase is CasePhase.SHRINKING else "testing"
    return f"{verb} {event.implementation_name} on {event.case_identifier}"


def _run_with_progress(
    context: CommandContext,
    problem: AnyProblem,
    *,
    implementations: Sequence[Implementation],
    cases: Sequence[AnyCase],
    options: TestRunOptions,
) -> TestReport:
    with create_progress_display(context.error_console) as progress:
        task_identifier = progress.add_task(
            "testing", total=len(cases) * len(implementations)
        )

        def show_progress(event: CaseProgress) -> None:
            if event.phase is CasePhase.COMPLETED:
                progress.update(task_identifier, advance=1)
            else:
                progress.update(
                    task_identifier, description=escape(_describe_progress(event))
                )

        return context.dependencies.run_tests(
            problem, implementations, cases, options=options, on_progress=show_progress
        )


def _save_inputs(
    context: CommandContext,
    problem: AnyProblem,
    report: TestReport,
    *,
    directory: Path | None,
) -> SavedInputs:
    """Write the inputs of the failing cases under ``directory``, when one is given.

    Returns:
        The saved inputs, empty when no directory is given.
    """
    if directory is None:
        return SavedInputs()
    saved = save_failing_inputs(problem, report, directory)
    context.warn(*saved.errors)
    return saved


def _build_selections(
    problem_name: str,
    implementations: Sequence[Implementation],
    configuration: Configuration | None,
) -> dict[str, tuple[str, ...]]:
    """Map each implementation name to the arguments that select it again.

    Returns:
        The selection arguments of each implementation, by name.
    """
    return {
        implementation.name: build_selection_arguments(
            problem_name, implementation, configuration
        )
        for implementation in implementations
    }


def _resolve_exact_cases(
    context: CommandContext, problem: AnyProblem, selection: "_CaseSelection"
) -> tuple[AnyCase, ...]:
    planning_options = selection.planning_options()
    if planning_options:
        context.fail(
            "--fixture and --case select exact cases, so they cannot be combined with "
            + ", ".join(planning_options)
        )
    resolved: dict[str, AnyCase] = {}
    for identifier in [
        *(FixtureOrigin(name).identifier for name in selection.fixture_names),
        *selection.case_identifiers,
    ]:
        case = context.resolve_case(problem, identifier)
        resolved.setdefault(case.identifier, case)
    return tuple(resolved.values())


def _plan_cases(
    context: CommandContext, problem: AnyProblem, selection: "_CaseSelection"
) -> tuple[tuple[AnyCase, ...], CasePlan]:
    try:
        plan = CasePlan(
            include_fixtures=not selection.no_fixtures,
            random_case_count=(
                context.dependencies.default_random_case_count
                if selection.random_cases is None
                else selection.random_cases
            ),
            maximum_size=(
                build_default_maximum_size(problem)
                if selection.maximum_size is None
                else context.parse_size(problem, selection.maximum_size)
            ),
            generator_names=tuple(
                generator.name
                for generator in select_generators(problem, selection.distributions)
            ),
            seed=0 if selection.seed is None else selection.seed,
        )
        cases = build_cases(problem, plan)
    except CaseError as error:
        context.fail(str(error))
    if not cases:
        context.fail(
            "There are no cases to run: --no-fixtures needs --random-cases greater than 0."
        )
    return cases, plan


def _select_cases(
    context: CommandContext, problem: AnyProblem, selection: "_CaseSelection"
) -> tuple[tuple[AnyCase, ...], CasePlan | None]:
    """Return the cases to run and the plan they came from.

    The cases are the ones named explicitly (the plan is then ``None``), or
    else the planned ones.
    """
    if selection.has_exact_cases():
        return _resolve_exact_cases(context, problem, selection), None
    return _plan_cases(context, problem, selection)


def _build_reproduction(
    problem_name: str,
    selections: Mapping[str, tuple[str, ...]],
    settings: "_RunSettings",
) -> Callable[[str, str], str]:
    """Return a function that writes the command that reruns one case of one implementation."""
    option_arguments = settings.reproduction_arguments()

    def reproduce(implementation_name: str, case_identifier: str) -> str:
        return shlex.join(
            [
                "algorithm-playground",
                "test",
                problem_name,
                *selections[implementation_name],
                *option_arguments,
                "--case",
                case_identifier,
            ]
        )

    return reproduce


def _print_report(
    context: CommandContext, completed: "_CompletedRun", display: "_ReportDisplay"
) -> None:
    console = context.console
    report, names, outcome = completed.report, completed.names, completed.outcome
    if display.verbose:
        print_expanded_matrix(
            console,
            report,
            names,
            build_failures=outcome.failures,
            unrunnable=outcome.unrunnable,
        )
    else:
        print_matrix(
            console,
            report,
            names,
            build_failures=outcome.failures,
            unrunnable=outcome.unrunnable,
        )
    print_failure_details(
        console,
        report,
        names,
        unavailable=outcome.unavailable,
        maximum_failures=display.maximum_failures,
        reproduce=display.reproduce,
        saved=completed.saved,
    )
    print_summaries(
        console,
        report,
        names,
        build_failures=outcome.failures,
        unrunnable=outcome.unrunnable,
    )


def _write_json_report(
    context: CommandContext, path: Path, completed: "_CompletedRun"
) -> None:
    document = convert_correctness_report_to_json(
        completed.report,
        implementations=completed.implementations,
        plan=completed.plan,
        build_failures={
            name: str(error) for name, error in completed.outcome.failures.items()
        },
        unrunnable=completed.outcome.unrunnable,
        saved_inputs=completed.saved,
    )
    context.write_json(path, document, label="test report")


@dataclass(frozen=True, slots=True)
class _CaseSelection:
    """The options that choose which cases to run."""

    random_cases: int | None
    maximum_size: str | None
    seed: int | None
    distributions: tuple[str, ...]
    no_fixtures: bool
    fixture_names: tuple[str, ...]
    case_identifiers: tuple[str, ...]

    def has_exact_cases(self) -> bool:
        """Return whether fixtures or cases are named, instead of planned."""
        return bool(self.fixture_names or self.case_identifiers)

    def planning_options(self) -> list[str]:
        """Return the options given that shape a plan of cases."""
        return [
            option
            for option, given in (
                ("--random-cases", self.random_cases is not None),
                ("--maximum-size", self.maximum_size is not None),
                ("--seed", self.seed is not None),
                ("--distribution", bool(self.distributions)),
                ("--no-fixtures", self.no_fixtures),
            )
            if given
        ]


@dataclass(frozen=True, slots=True)
class _RunSettings:
    """The options that say how the cases are run."""

    configuration_path: Path | None
    problem_modules: tuple[str, ...]
    build: bool
    timeout_seconds: float
    keep_temporary_files: bool
    shrink: bool

    def build_run_options(self, maximum_description_length: int) -> TestRunOptions:
        """Return the options of :func:`run_tests` for these settings.

        Args:
            maximum_description_length: How long a description of an input or output may be.

        Returns:
            The options.
        """
        return TestRunOptions(
            timeout_seconds=self.timeout_seconds,
            temporary_files=(
                TemporaryFilePolicy.KEEP
                if self.keep_temporary_files
                else TemporaryFilePolicy.DELETE
            ),
            shrinking=ShrinkOptions() if self.shrink else None,
            description_limit=maximum_description_length,
        )

    def reproduction_arguments(self) -> list[str]:
        """Return the arguments that give again the options that change what a rerun finds.

        These are the options that change what the command finds or how it judges,
        such as ``--timeout``.
        """
        return [
            *(
                []
                if self.configuration_path is None
                else ["--configuration", str(self.configuration_path)]
            ),
            *(
                argument
                for module in self.problem_modules
                for argument in ("--problem-module", module)
            ),
            *(
                []
                if self.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
                else ["--timeout", f"{self.timeout_seconds:g}"]
            ),
            *([] if self.build else ["--no-build"]),
        ]


@dataclass(frozen=True, slots=True)
class _CompletedRun:
    """Everything a finished run of the cases produced."""

    report: TestReport
    implementations: tuple[Implementation, ...]
    outcome: BuildOutcome
    saved: SavedInputs
    plan: CasePlan | None

    @property
    def names(self) -> list[str]:
        """The names of all the selected implementations, in order."""
        return [implementation.name for implementation in self.implementations]


@dataclass(frozen=True, slots=True)
class _ReportDisplay:
    """How the report is shown."""

    verbose: bool
    maximum_failures: int
    reproduce: Callable[[str, str], str]


def test_command(  # noqa: PLR0913  every Typer option is a parameter
    click_context: typer.Context,
    problem_name: Annotated[
        str, typer.Argument(metavar="PROBLEM", help="Name of the registered problem.")
    ],
    *,
    selectors: ImplementationsArgument = None,
    command_texts: CommandOption = None,
    command_names: NameOption = None,
    configuration_path: ConfigurationOption = None,
    problem_modules: ProblemModuleOption = None,
    build: BuildOption = True,
    inherit_environment: InheritEnvironmentOption = False,
    random_cases: Annotated[
        int | None,
        typer.Option(
            "--random-cases",
            min=0,
            help=(
                "Number of generated cases to run, spread over the distributions "
                f"(default: {DEFAULT_RANDOM_CASE_COUNT})."
            ),
        ),
    ] = None,
    maximum_size: Annotated[
        str | None,
        typer.Option(
            "--maximum-size",
            help=(
                "Largest size of a generated case; small sizes are favored (default: the "
                "default maximum of each dimension, 100 unless the problem says otherwise). "
                "A problem with several dimensions takes name=N parts joined by colons "
                "(for example vertices=50:edges=200)."
            ),
        ),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed", help="Seed that determines the generated cases (default: 0)."
        ),
    ] = None,
    distributions: Annotated[
        list[str] | None,
        typer.Option(
            "--distribution",
            help=(
                "Name of an input distribution to draw generated cases from. May be repeated "
                "(default: all of the problem's distributions)."
            ),
        ),
    ] = None,
    no_fixtures: Annotated[
        bool,
        typer.Option("--no-fixtures", help="Skip the problem's curated fixtures."),
    ] = False,
    fixture_names: Annotated[
        list[str] | None,
        typer.Option(
            "--fixture",
            help="Run only the named fixture, instead of the planned cases. May be repeated.",
        ),
    ] = None,
    case_identifiers: Annotated[
        list[str] | None,
        typer.Option(
            "--case",
            help=(
                "Run only the case with this identifier, for example fixture:empty or "
                "generated:uniform:size=37:seed=1234567, instead of the planned cases. "
                "May be repeated."
            ),
        ),
    ] = None,
    shrink: Annotated[
        bool,
        typer.Option(
            "--shrink/--no-shrink",
            help="Shrink the input of a failing generated case to a smaller one that still fails.",
        ),
    ] = True,
    maximum_failures: Annotated[
        int,
        typer.Option(
            "--maximum-failures",
            min=1,
            help=(
                "Failures to describe in full per implementation; the rest are only listed "
                "by identifier."
            ),
        ),
    ] = DEFAULT_MAXIMUM_FAILURES,
    timeout_seconds: Annotated[
        float, build_timeout_option("Per-case timeout in seconds.")
    ] = DEFAULT_TIMEOUT_SECONDS,
    keep_temporary_files: Annotated[
        bool,
        typer.Option(
            "--keep-temporary-files",
            help="Keep the per-run scratch directory after the run (for inspection).",
        ),
    ] = False,
    save_failing_inputs_directory: Annotated[
        Path | None,
        typer.Option(
            "--save-failing-inputs",
            metavar="DIRECTORY",
            help=(
                "Write the input of every failing case, and its shrunk input, in the problem's "
                "binary input format under DIRECTORY/IMPLEMENTATION/CASE/. Run one again with "
                "'debug --input-file'."
            ),
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Show a row for every fixture in the matrix, not just the ones that failed.",
        ),
    ] = False,
    json_path: Annotated[
        Path | None, build_json_option("Write the full test report to this JSON file.")
    ] = None,
) -> None:
    """Run the cases of a problem against each selected implementation.

    Args:
        click_context: The Click context; its object holds the collaborators to call.
        problem_name: The name of the registered problem.
        selectors: The names or paths of the implementations to run.
        command_texts: The ``--command`` values naming implementations.
        command_names: The ``--name`` values for the commands.
        configuration_path: The configuration file to read.
        problem_modules: Python modules or files that register problems.
        build: Whether to run each implementation's build command first.
        inherit_environment: Whether to give implementations the full environment.
        random_cases: The number of generated cases.
        maximum_size: The text of the largest size of a generated case.
        seed: The seed of the generated cases.
        distributions: The distributions to draw generated cases from.
        no_fixtures: Whether to skip the problem's fixtures.
        fixture_names: The fixtures to run instead of the planned cases.
        case_identifiers: The cases to run instead of the planned cases.
        shrink: Whether to shrink the input of a failing generated case.
        maximum_failures: How many failures to describe in full per implementation.
        timeout_seconds: The timeout of each case.
        keep_temporary_files: Whether to keep the scratch directory of the run.
        save_failing_inputs_directory: Where to write the inputs of failing cases.
        verbose: Whether to show a row for every fixture in the matrix.
        json_path: Where to write the full report as JSON.

    Raises:
        typer.Exit: With the failure code if any case failed or any implementation
            could not run.
    """
    context = CommandContext(
        configuration_path,
        problem_modules,
        dependencies=click_context.ensure_object(CommandDependencies),
    )
    problem = context.get_problem(problem_name)
    context.check_json_path(json_path)
    context.check_directory_path(save_failing_inputs_directory, "--save-failing-inputs")

    cases, plan = _select_cases(
        context,
        problem,
        _CaseSelection(
            random_cases=random_cases,
            maximum_size=maximum_size,
            seed=seed,
            distributions=tuple(distributions or ()),
            no_fixtures=no_fixtures,
            fixture_names=tuple(fixture_names or ()),
            case_identifiers=tuple(case_identifiers or ()),
        ),
    )
    selected = context.select_implementations(
        problem_name,
        selectors=selectors,
        command_texts=command_texts,
        command_names=command_names,
        environment_policy=choose_environment_policy(
            inherit_environment=inherit_environment
        ),
    )
    outcome = (
        context.build_and_check(selected)
        if build
        else context.check_startable(selected)
    )

    settings = _RunSettings(
        configuration_path=configuration_path,
        problem_modules=tuple(problem_modules or ()),
        build=build,
        timeout_seconds=timeout_seconds,
        keep_temporary_files=keep_temporary_files,
        shrink=shrink,
    )
    report = _run_with_progress(
        context,
        problem,
        implementations=outcome.ready,
        cases=cases,
        options=settings.build_run_options(description_limit(context.console)),
    )
    completed = _CompletedRun(
        report=report,
        implementations=selected,
        outcome=outcome,
        saved=_save_inputs(
            context, problem, report, directory=save_failing_inputs_directory
        ),
        plan=plan,
    )

    reproduce = _build_reproduction(
        problem_name,
        _build_selections(problem_name, selected, context.configuration),
        settings,
    )
    _print_report(
        context,
        completed,
        _ReportDisplay(
            verbose=verbose, maximum_failures=maximum_failures, reproduce=reproduce
        ),
    )
    if json_path is not None:
        _write_json_report(context, json_path, completed)

    if outcome.unavailable or not report.has_passed:
        raise typer.Exit(code=FAILURE_EXIT_CODE)
