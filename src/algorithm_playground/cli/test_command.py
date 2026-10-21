"""`algorithm-playground test` — run implementations against fixtures and generated cases."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from algorithm_playground.cli.context import CommandContext
from algorithm_playground.cli.implementation_selection import selection_arguments
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
from algorithm_playground.cli.test_rendering import (
    description_limit,
    print_failure_details,
    print_matrix,
    print_summaries,
)
from algorithm_playground.core.cases import (
    DEFAULT_MAXIMUM_SIZE,
    DEFAULT_RANDOM_CASE_COUNT,
    Case,
    CaseError,
    CasePlan,
    FixtureOrigin,
    build_cases,
    select_generators,
)
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.report import correctness_report_to_json
from algorithm_playground.core.runner import DEFAULT_TIMEOUT_SECONDS
from algorithm_playground.core.saved_inputs import SavedInputs, save_failing_inputs
from algorithm_playground.core.testing import CasePhase, CaseProgress, run_tests

DEFAULT_MAXIMUM_FAILURES = 5


def test_command(
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
        int | None,
        typer.Option(
            "--maximum-size",
            min=0,
            help=(
                "Largest size of a generated case; small sizes are favored "
                f"(default: {DEFAULT_MAXIMUM_SIZE})."
            ),
        ),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Seed that determines the generated cases (default: 0)."),
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
        float, timeout_option("Per-case timeout in seconds.")
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
        Path | None, json_option("Write the full test report to this JSON file.")
    ] = None,
) -> None:
    """Run the cases of ``problem_name`` against each selected implementation."""
    context = CommandContext(configuration_path, problem_modules)
    problem = context.get_problem(problem_name)
    context.check_json_path(json_path)
    context.check_directory_path(save_failing_inputs_directory, "--save-failing-inputs")

    cases, plan = _select_cases(
        context,
        problem,
        random_cases=random_cases,
        maximum_size=maximum_size,
        seed=seed,
        distributions=distributions or (),
        no_fixtures=no_fixtures,
        fixture_names=fixture_names or (),
        case_identifiers=case_identifiers or (),
    )
    selected = context.select_implementations(
        problem_name,
        selectors=selectors,
        command_texts=command_texts,
        command_names=command_names,
        inherit_environment=inherit_environment,
    )
    outcome = context.build(selected, build=build)

    with progress_display(context.error_console, with_bar=False) as progress:
        task_identifier = progress.add_task("testing", total=len(cases) * len(outcome.ready))

        def show_progress(event: CaseProgress) -> None:
            if event.phase is CasePhase.COMPLETED:
                progress.update(task_identifier, advance=1)
                return
            verb = "shrinking" if event.phase is CasePhase.SHRINKING else "testing"
            description = f"{verb} {event.implementation_name} on {event.case_identifier}"
            progress.update(task_identifier, description=escape(description))

        report = run_tests(
            problem,
            outcome.ready,
            cases,
            timeout_seconds=timeout_seconds,
            keep_temporary_files=keep_temporary_files,
            shrink=shrink,
            description_limit=description_limit(context.console),
            on_progress=show_progress,
        )

    saved = SavedInputs()
    if save_failing_inputs_directory is not None:
        saved = save_failing_inputs(problem, report, save_failing_inputs_directory)
        context.warn(*saved.errors)

    names = [implementation.name for implementation in selected]
    reproduce = _reproduction_builder(
        problem_name,
        {
            implementation.name: selection_arguments(
                problem_name, implementation, context.configuration
            )
            for implementation in selected
        },
        [
            *([] if configuration_path is None else ["--configuration", str(configuration_path)]),
            *(
                argument
                for module in problem_modules or ()
                for argument in ("--problem-module", module)
            ),
            *(
                []
                if timeout_seconds == DEFAULT_TIMEOUT_SECONDS
                else ["--timeout", f"{timeout_seconds:g}"]
            ),
            *([] if build else ["--no-build"]),
        ],
    )
    print_matrix(
        context.console, report, names, outcome.failures, outcome.unrunnable, verbose=verbose
    )
    print_failure_details(
        context.console,
        report,
        names,
        outcome.unavailable,
        maximum_failures=maximum_failures,
        reproduce=reproduce,
        saved=saved,
    )
    print_summaries(context.console, report, names, outcome.failures, outcome.unrunnable)

    if json_path is not None:
        document = correctness_report_to_json(
            report,
            implementations=selected,
            plan=plan,
            build_failures={name: str(error) for name, error in outcome.failures.items()},
            unrunnable=outcome.unrunnable,
            saved_inputs=saved,
        )
        context.write_json(json_path, document, label="test report")

    if outcome.unavailable or not report.passed:
        raise typer.Exit(code=1)


def _select_cases(
    context: CommandContext,
    problem: Problem[Any, Any, Any],
    *,
    random_cases: int | None,
    maximum_size: int | None,
    seed: int | None,
    distributions: Sequence[str],
    no_fixtures: bool,
    fixture_names: Sequence[str],
    case_identifiers: Sequence[str],
) -> tuple[tuple[Case[Any], ...], CasePlan | None]:
    """Return the cases to run and the plan they came from.

    The cases are the ones named explicitly (the plan is then ``None``), or
    else the planned ones.
    """
    if fixture_names or case_identifiers:
        planning_options = [
            option
            for option, given in (
                ("--random-cases", random_cases is not None),
                ("--maximum-size", maximum_size is not None),
                ("--seed", seed is not None),
                ("--distribution", bool(distributions)),
                ("--no-fixtures", no_fixtures),
            )
            if given
        ]
        if planning_options:
            context.fail(
                "--fixture and --case select exact cases, so they cannot be combined with "
                + ", ".join(planning_options)
            )
        resolved: dict[str, Case[Any]] = {}
        for identifier in [
            *(FixtureOrigin(name).identifier for name in fixture_names),
            *case_identifiers,
        ]:
            case = context.resolve_case(problem, identifier)
            resolved.setdefault(case.identifier, case)
        return tuple(resolved.values()), None

    try:
        plan = CasePlan(
            include_fixtures=not no_fixtures,
            random_case_count=DEFAULT_RANDOM_CASE_COUNT if random_cases is None else random_cases,
            maximum_size=DEFAULT_MAXIMUM_SIZE if maximum_size is None else maximum_size,
            generator_names=tuple(
                generator.name for generator in select_generators(problem, distributions)
            ),
            seed=0 if seed is None else seed,
        )
        cases = build_cases(problem, plan)
    except CaseError as error:
        context.fail(str(error))
    if not cases:
        context.fail(
            "There are no cases to run: --no-fixtures needs --random-cases greater than 0."
        )
    return cases, plan


def _reproduction_builder(
    problem_name: str,
    selections: Mapping[str, tuple[str, ...]],
    option_arguments: Sequence[str],
) -> Callable[[str, str], str]:
    """Return a function that writes the command that reruns one case of one implementation.

    ``option_arguments`` are the options of this run that change what the
    command finds or how it judges, such as ``--timeout``.
    """

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
