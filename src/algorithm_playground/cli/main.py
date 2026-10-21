"""Top-level Typer application that wires up the subcommands."""

from __future__ import annotations

import typer

# Importing the problems package triggers built-in problem registration.
import algorithm_playground.problems  # noqa: F401
from algorithm_playground.cli.benchmark_command import benchmark_command
from algorithm_playground.cli.debug_command import debug_command
from algorithm_playground.cli.list_command import list_command
from algorithm_playground.cli.test_command import test_command

app = typer.Typer(
    name="algorithm-playground",
    help=(
        "A learning and benchmarking sandbox for algorithms. Drive any executable "
        "that implements a problem's binary I/O contract."
    ),
    no_args_is_help=True,
    add_completion=False,
)

app.command("list", help="List all registered problems.")(list_command)
app.command(
    "test",
    help="Run an executable against a problem's curated test fixtures.",
)(test_command)
app.command(
    "benchmark",
    help="Benchmark an executable on seeded random inputs across configurable sizes.",
)(benchmark_command)
app.command(
    "debug",
    help="Step through an executable's trace output for a single input.",
)(debug_command)


if __name__ == "__main__":
    app()
