"""`algorithm-playground list` — print every registered problem."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from algorithm_playground.core.registry import REGISTRY, list_problems


def list_command() -> None:
    """Print a table of registered problem names and descriptions."""
    console = Console()
    names = list_problems()
    if not names:
        console.print("[yellow]No problems are registered.[/yellow]")
        return

    table = Table(title="Registered problems")
    table.add_column("name", style="bold cyan")
    table.add_column("description")
    for name in names:
        problem_class = REGISTRY[name]
        description = getattr(problem_class, "description", "")
        table.add_row(name, description)
    console.print(table)
