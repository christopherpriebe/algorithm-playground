"""Terminal output that more than one command produces."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table


def progress_display(error_console: Console, *, with_bar: bool) -> Progress:
    """Return a progress display that disappears when done, drawn on standard error."""
    columns: list[ProgressColumn] = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ]
    if with_bar:
        columns.append(BarColumn())
    columns.extend([TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn()])
    return Progress(*columns, console=error_console, transient=True)


def print_table(console: Console, title: str, table: Table) -> None:
    """Print ``table`` under a bold title on a line of its own, left aligned.

    The title of a Rich table is centered and wrapped to the width of the table,
    which breaks a short title over a narrow table; a line above it does not.
    """
    console.print(f"[bold]{escape(title)}[/bold]", soft_wrap=True)
    console.print(table)
