"""`algorithm-playground debug` — step through an executable's trace output."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from algorithm_playground.core.problem import Problem
from algorithm_playground.core.registry import get_problem
from algorithm_playground.core.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    Runner,
    RunnerError,
)

NO_TRACE_HINT = (
    "The executable did not produce a usable trace file. To enable debug "
    "visualization, accept an optional 4th argument and write the problem's "
    "binary trace format to it. Falling back to input/output visualization."
)


def debug_command(
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
            help="Random seed used to generate the input (ignored when --from-test is set).",
        ),
    ] = 0,
    size: Annotated[
        int,
        typer.Option(
            "--size",
            min=0,
            help="Input size to generate (ignored when --from-test is set).",
        ),
    ] = 16,
    from_test: Annotated[
        str | None,
        typer.Option(
            "--from-test",
            help="Use the named test fixture as the input instead of generating one.",
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
        float,
        typer.Option(
            "--timeout",
            min=0.001,
            help="Per-invocation timeout in seconds.",
        ),
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run ``executable`` on a single input and step through its trace output."""
    console = Console()
    try:
        problem = get_problem(problem_name)
    except KeyError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=2) from error

    if from_test is not None:
        case_input = _find_test_case(problem, console, from_test)
    else:
        case_input = problem.benchmark_case(seed=seed, size=size).input_data

    runner = Runner(problem, executable, timeout_seconds=timeout_seconds)
    try:
        result = runner.run(case_input, collect_trace=True)
    except RunnerError as error:
        console.print(f"[red]Runner error:[/red] {error}")
        raise typer.Exit(code=1) from error

    verification = problem.verify(case_input, result.output)
    if verification.passed:
        console.print("[green]Output verified.[/green]")
    else:
        console.print(f"[red]Output did not verify:[/red] {verification.message}")

    if result.trace is None:
        if result.trace_error is not None:
            console.print(f"[red]Trace file is malformed:[/red] {result.trace_error}")
        console.print(f"[yellow]{NO_TRACE_HINT}[/yellow]")
        problem.visualize_io(case_input, result.output)
        return

    problem.visualize_trace(
        result.trace,
        auto_advance=auto_advance,
        delay_milliseconds=delay_milliseconds,
    )


def _find_test_case(problem: Problem[Any, Any, Any], console: Console, name: str) -> Any:
    for case in problem.test_cases():
        if case.name == name:
            return case.input_data
    available = ", ".join(case.name for case in problem.test_cases())
    console.print(f"[red]No test case named '{name}'. Available cases:[/red] {available}")
    raise typer.Exit(code=2)
