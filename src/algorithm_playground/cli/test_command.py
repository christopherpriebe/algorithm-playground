"""`algorithm-playground test` — run an executable against curated fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from algorithm_playground.core.registry import get_problem
from algorithm_playground.core.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    Runner,
    RunnerError,
)


def test_command(
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
    timeout_seconds: Annotated[
        float,
        typer.Option(
            "--timeout",
            "-t",
            min=0.001,
            help="Per-fixture timeout in seconds.",
        ),
    ] = DEFAULT_TIMEOUT_SECONDS,
    keep_temporary_files: Annotated[
        bool,
        typer.Option(
            "--keep-temporary-files",
            help="Keep the per-run scratch directory after the run (for inspection).",
        ),
    ] = False,
) -> None:
    """Run every registered test fixture for ``problem_name`` against ``executable``."""
    console = Console()
    try:
        problem = get_problem(problem_name)
    except KeyError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=2) from error

    runner = Runner(
        problem,
        executable,
        timeout_seconds=timeout_seconds,
        keep_temporary_files=keep_temporary_files,
    )

    table = Table(title=f"test results — {problem_name}")
    table.add_column("case", style="bold")
    table.add_column("status")
    table.add_column("details")

    failure_count = 0
    for case in problem.test_cases():
        try:
            result = runner.run(case.input_data, collect_trace=False)
        except RunnerError as error:
            failure_count += 1
            table.add_row(case.name, "[red]ERROR[/red]", str(error).splitlines()[0])
            continue

        verification = problem.verify(case.input_data, result.output)
        if verification.passed:
            table.add_row(case.name, "[green]PASS[/green]", "")
        else:
            failure_count += 1
            table.add_row(case.name, "[red]FAIL[/red]", verification.message)

    console.print(table)
    total = sum(1 for _ in problem.test_cases())
    passed = total - failure_count
    summary_color = "green" if failure_count == 0 else "red"
    console.print(f"[{summary_color}]{passed}/{total} fixtures passed[/{summary_color}]")
    if failure_count:
        raise typer.Exit(code=failure_count)
