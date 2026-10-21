"""Terminal output that more than one command produces."""

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

__all__ = [
    "create_progress_display",
    "create_progress_display_with_bar",
    "print_table",
]


def _description_columns() -> list[ProgressColumn]:
    return [SpinnerColumn(), TextColumn("[progress.description]{task.description}")]


def _counter_columns() -> list[ProgressColumn]:
    return [TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn()]


def _create_transient_progress(error_console: Console, columns: list[ProgressColumn]) -> Progress:
    return Progress(*columns, console=error_console, transient=True)


def create_progress_display(error_console: Console) -> Progress:
    """Create a progress display without a bar that disappears when done.

    Args:
        error_console: The console on standard error to draw on.

    Returns:
        A progress display showing a spinner, the description, and the count.
    """
    return _create_transient_progress(error_console, [*_description_columns(), *_counter_columns()])


def create_progress_display_with_bar(error_console: Console) -> Progress:
    """Create a progress display with a bar that disappears when done.

    Args:
        error_console: The console on standard error to draw on.

    Returns:
        A progress display showing a spinner, the description, a bar, and the count.
    """
    return _create_transient_progress(
        error_console, [*_description_columns(), BarColumn(), *_counter_columns()]
    )


def print_table(console: Console, title: str, table: Table) -> None:
    """Print a table under a bold title on a line of its own, left aligned.

    The title of a Rich table is centered and wrapped to the width of the table,
    which breaks a short title over a narrow table; a line above it does not.

    Args:
        console: The console to print on.
        title: The title, printed literally.
        table: The table to print under the title.
    """
    console.print(f"[bold]{escape(title)}[/bold]", soft_wrap=True)
    console.print(table)
