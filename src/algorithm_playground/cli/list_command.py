"""`algorithm-playground list`: print the registered problems, or the details of one problem."""

import shlex
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from algorithm_playground.cli.context import CommandContext
from algorithm_playground.cli.options import ConfigurationOption, ProblemModuleOption
from algorithm_playground.core.problem import AnyProblem, has_input_reader, has_trace_format
from algorithm_playground.core.registry import problem_descriptions, problem_sources

__all__ = ["list_command"]


def _describe_input_files(problem: AnyProblem) -> str:
    if has_input_reader(problem):
        return "Input files: readable, so 'debug --input-file' can run a saved input."
    return (
        "Input files: the problem does not implement deserialize_input, so "
        "'debug --input-file' cannot run a saved input."
    )


def _describe_trace_format(problem: AnyProblem) -> str:
    if not has_trace_format(problem):
        return "Trace format: none. Implementations cannot write a trace for this problem."
    elif problem.operation_names:
        operations = ", ".join(escape(name) for name in problem.operation_names)
        return (
            "Trace format: yes. Operations counted from a trace by "
            f"'benchmark --count-operations': {operations}."
        )
    else:
        return (
            "Trace format: yes. The problem does not say which operations a trace counts, "
            "so 'benchmark --count-operations' shows whatever the trace holds."
        )


def _print_problem_header(context: CommandContext, problem: AnyProblem) -> None:
    source = problem_sources()[problem.name].describe()
    context.console.print(
        f"[bold cyan]{escape(problem.name)}[/bold cyan]: {escape(problem.description)} "
        f"[dim]({escape(source)})[/dim]",
        soft_wrap=True,
    )


def _print_fixtures(context: CommandContext, problem: AnyProblem) -> None:
    fixtures = context.call_hook("fixtures", lambda: list(problem.fixtures()))
    table = Table(title=f"Fixtures ({len(fixtures)})")
    table.add_column("name", style="bold")
    table.add_column("description")
    for fixture in fixtures:
        table.add_row(escape(fixture.name), escape(fixture.description))
    context.console.print(table)


def _print_distributions(context: CommandContext, problem: AnyProblem) -> None:
    generators = context.call_hook("generators", lambda: list(problem.generators()))
    table = Table(
        title=f"Distributions ({len(generators)})",
        caption=(f"Sizes start at {problem.minimum_size}." if problem.minimum_size else None),
    )
    table.add_column("name", style="bold")
    table.add_column("description")
    table.add_column("used as")
    for position, generator in enumerate(generators):
        roles = [
            *(["default"] if position == 0 else []),
            *(["debug"] if generator.name == problem.debug_generator else []),
        ]
        table.add_row(escape(generator.name), escape(generator.description), ", ".join(roles))
    context.console.print(table)


def _print_problem(context: CommandContext, problem_name: str) -> None:
    """Show what a problem offers: the cases, the distributions, and the trace support."""
    problem = context.get_problem(problem_name)
    _print_problem_header(context, problem)
    _print_fixtures(context, problem)
    _print_distributions(context, problem)
    context.console.print(_describe_trace_format(problem), soft_wrap=True)
    context.console.print(_describe_input_files(problem), soft_wrap=True)


def _print_registered_problems(context: CommandContext) -> None:
    descriptions = problem_descriptions()
    sources = problem_sources()
    if not descriptions:
        context.error_console.print("[yellow]No problems are registered.[/yellow]")
        return
    table = Table(title="Registered problems")
    table.add_column("name", style="bold cyan")
    table.add_column("description")
    table.add_column("source")
    for name, description in descriptions.items():
        table.add_row(escape(name), escape(description), escape(sources[name].describe()))
    context.console.print(table)


def _print_configured_implementations(context: CommandContext, problem_name: str | None) -> None:
    """Show the implementations of the configuration file, if there is one.

    Only those of ``problem_name`` are shown unless it is ``None``.
    """
    configuration = context.configuration
    if configuration is None:
        return
    shown_path = escape(configuration.display_path)
    entries = [
        entry
        for entry in configuration.configured_implementations
        if problem_name is None or entry.problem_name == problem_name
    ]
    if not entries:
        context.error_console.print(
            f"[yellow]{shown_path} configures no implementations"
            f"{'' if problem_name is None else f' for {escape(problem_name)}'}.[/yellow]",
            soft_wrap=True,
        )
        return
    table = Table(title=f"Configured implementations ({shown_path})")
    table.add_column("problem", style="bold cyan")
    table.add_column("name", style="bold")
    table.add_column("command")
    for entry in entries:
        table.add_row(
            escape(entry.problem_name),
            escape(entry.implementation.name),
            escape(shlex.join(entry.implementation.command)),
        )
    context.console.print(table)


def list_command(
    problem_name: Annotated[
        str | None,
        typer.Argument(
            metavar="[PROBLEM]",
            help=(
                "Show the details of this problem: its fixtures, distributions, trace format, "
                "and operations. Without it, list every registered problem."
            ),
        ),
    ] = None,
    configuration_path: ConfigurationOption = None,
    problem_modules: ProblemModuleOption = None,
) -> None:
    """Print the registered problems and the implementations in the configuration file.

    With a problem name, print what that problem offers instead.

    Args:
        problem_name: The problem to show the details of, if any.
        configuration_path: The configuration file to read.
        problem_modules: Python modules or files that register problems.
    """
    context = CommandContext(configuration_path, problem_modules)
    if problem_name is None:
        _print_registered_problems(context)
    else:
        _print_problem(context, problem_name)
    _print_configured_implementations(context, problem_name)
