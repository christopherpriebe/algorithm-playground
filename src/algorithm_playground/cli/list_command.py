"""`algorithm-playground list` — print the registered problems, or the details of one problem."""

from __future__ import annotations

import shlex
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from algorithm_playground.cli.context import CommandContext
from algorithm_playground.cli.options import ConfigurationOption, ProblemModuleOption
from algorithm_playground.core.configuration import Configuration
from algorithm_playground.core.problem import Problem, has_input_reader, has_trace_format
from algorithm_playground.core.registry import problem_descriptions, problem_sources


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
    """
    context = CommandContext(configuration_path, problem_modules)
    console, error_console = context.console, context.error_console

    if problem_name is not None:
        _print_problem(context, problem_name)
        if context.configuration is not None:
            _print_configured_implementations(
                console, error_console, context.configuration, problem_name=problem_name
            )
        return

    descriptions = problem_descriptions()
    sources = problem_sources()
    if not descriptions:
        error_console.print("[yellow]No problems are registered.[/yellow]")
    else:
        table = Table(title="Registered problems")
        table.add_column("name", style="bold cyan")
        table.add_column("description")
        table.add_column("source")
        for name, description in descriptions.items():
            table.add_row(escape(name), escape(description), escape(sources[name].describe()))
        console.print(table)

    if context.configuration is not None:
        _print_configured_implementations(console, error_console, context.configuration)


def _print_problem(context: CommandContext, problem_name: str) -> None:
    """Show what a problem offers: the cases, the distributions, and the trace support."""
    problem = context.get_problem(problem_name)
    console = context.console
    source = problem_sources()[problem_name].describe()
    console.print(
        f"[bold cyan]{escape(problem_name)}[/bold cyan]: {escape(problem.description)} "
        f"[dim]({escape(source)})[/dim]",
        soft_wrap=True,
    )

    fixtures = context.call_hook("fixtures", lambda: list(problem.fixtures()))
    fixture_table = Table(title=f"Fixtures ({len(fixtures)})")
    fixture_table.add_column("name", style="bold")
    fixture_table.add_column("description")
    for fixture in fixtures:
        fixture_table.add_row(escape(fixture.name), escape(fixture.description))
    console.print(fixture_table)

    generators = context.call_hook("generators", lambda: list(problem.generators()))
    generator_table = Table(
        title=f"Distributions ({len(generators)})",
        caption=(f"Sizes start at {problem.minimum_size}." if problem.minimum_size else None),
    )
    generator_table.add_column("name", style="bold")
    generator_table.add_column("description")
    generator_table.add_column("used as")
    for position, generator in enumerate(generators):
        roles = [
            *(["default"] if position == 0 else []),
            *(["debug"] if generator.name == problem.debug_generator else []),
        ]
        generator_table.add_row(
            escape(generator.name), escape(generator.description), ", ".join(roles)
        )
    console.print(generator_table)

    console.print(_trace_summary(problem), soft_wrap=True)
    console.print(_input_file_summary(problem), soft_wrap=True)


def _input_file_summary(problem: Problem[Any, Any, Any]) -> str:
    if has_input_reader(problem):
        return "Input files: readable, so 'debug --input-file' can run a saved input."
    return (
        "Input files: the problem does not implement deserialize_input, so "
        "'debug --input-file' cannot run a saved input."
    )


def _trace_summary(problem: Problem[Any, Any, Any]) -> str:
    if not has_trace_format(problem):
        return "Trace format: none. Implementations cannot write a trace for this problem."
    if problem.operation_names:
        operations = ", ".join(escape(name) for name in problem.operation_names)
        return (
            "Trace format: yes. Operations counted from a trace by "
            f"'benchmark --count-operations': {operations}."
        )
    return (
        "Trace format: yes. The problem does not say which operations a trace counts, "
        "so 'benchmark --count-operations' shows whatever the trace holds."
    )


def _print_configured_implementations(
    console: Console,
    error_console: Console,
    configuration: Configuration,
    *,
    problem_name: str | None = None,
) -> None:
    shown_path = escape(configuration.display_path)
    entries = [
        entry
        for entry in configuration.configured_implementations
        if problem_name is None or entry.problem_name == problem_name
    ]
    if not entries:
        error_console.print(
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
    console.print(table)
