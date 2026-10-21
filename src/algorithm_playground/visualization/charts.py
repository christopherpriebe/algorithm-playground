"""Thin wrappers around ``plotext`` for the charts the playground draws.

These helpers keep plotext usage isolated so problem implementations and CLI
commands do not need to import plotext directly. Each function clears the
plot state, configures the requested chart, and prints it to stdout.
"""

from __future__ import annotations

from collections.abc import Sequence

import plotext


def bar_chart(values: Sequence[int | float], *, title: str, width: int | None = None) -> None:
    """Render a bar chart of ``values`` to the terminal."""
    plotext.clear_figure()
    if width is not None:
        plotext.plotsize(width, max(15, min(30, len(values) // 4 + 10)))
    plotext.bar(list(range(len(values))), list(values))
    plotext.title(title)
    plotext.xlabel("index")
    plotext.ylabel("value")
    plotext.theme("clear")
    plotext.show()


def side_by_side_bar_charts(
    left_values: Sequence[int | float],
    right_values: Sequence[int | float],
    *,
    left_title: str,
    right_title: str,
) -> None:
    """Render two bar charts on adjacent subplots."""
    plotext.clear_figure()
    plotext.subplots(1, 2)

    plotext.subplot(1, 1)
    plotext.bar(list(range(len(left_values))), list(left_values))
    plotext.title(left_title)
    plotext.xlabel("index")
    plotext.ylabel("value")

    plotext.subplot(1, 2)
    plotext.bar(list(range(len(right_values))), list(right_values))
    plotext.title(right_title)
    plotext.xlabel("index")
    plotext.ylabel("value")

    plotext.theme("clear")
    plotext.show()


def line_chart(
    x_values: Sequence[int | float],
    y_values: Sequence[int | float],
    *,
    title: str,
    x_label: str,
    y_label: str,
    log_x: bool = False,
    log_y: bool = False,
) -> None:
    """Render a line chart of (``x_values``, ``y_values``) to the terminal."""
    plotext.clear_figure()
    plotext.plot(list(x_values), list(y_values), marker="braille")
    plotext.title(title)
    plotext.xlabel(x_label)
    plotext.ylabel(y_label)
    if log_x:
        plotext.xscale("log")
    if log_y:
        plotext.yscale("log")
    plotext.theme("clear")
    plotext.show()
