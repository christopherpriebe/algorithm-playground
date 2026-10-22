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

from algorithm_playground.core._dimensions import Size

__all__ = [
    "create_progress_display",
    "create_progress_display_with_bar",
    "format_score",
    "format_size",
    "print_table",
]


def format_size(size: Size) -> str:
    """Write a size for a table cell or a message.

    Args:
        size: The size.

    Returns:
        The bare value with thousands separators for a size with one dimension,
        else ``name=value`` for each dimension, joined by spaces.
    """
    if len(size) == 1:
        return f"{next(iter(size.values())):,}"
    return " ".join(f"{name}={value:,}" for name, value in size.items())


def format_score(value: float) -> str:
    """Write a score for a table cell or a message.

    Args:
        value: The score.

    Returns:
        A whole number without decimals, anything else with two decimals, both
        with thousands separators.
    """
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _description_columns() -> list[ProgressColumn]:
    return [SpinnerColumn(), TextColumn("[progress.description]{task.description}")]


def _counter_columns() -> list[ProgressColumn]:
    return [TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn()]


def _create_transient_progress(
    error_console: Console, columns: list[ProgressColumn]
) -> Progress:
    return Progress(*columns, console=error_console, transient=True)


def create_progress_display(error_console: Console) -> Progress:
    """Create a progress display without a bar that disappears when done.

    Args:
        error_console: The console on standard error to draw on.

    Returns:
        A progress display showing a spinner, the description, and the count.
    """
    return _create_transient_progress(
        error_console, [*_description_columns(), *_counter_columns()]
    )


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
