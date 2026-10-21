"""Thin wrappers around ``plotext`` for the charts the playground draws.

These helpers keep plotext usage isolated so problem implementations and CLI
commands do not need to import plotext directly. The ``render_`` functions
return a chart as text, which is what a problem puts in a frame;
:func:`line_chart` prints a chart to standard output.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import plotext

PLAIN_BAR_COLOR = "blue"
GAP_COLUMNS = 2
BAR_WIDTH = 4 / 5
MAXIMUM_BAR_LABELS = 20


@dataclass(frozen=True)
class BarHighlight:
    """Bars drawn in another color, with a legend entry saying why."""

    indices: tuple[int, ...]
    color: str
    label: str


def render_bar_chart(
    values: Sequence[int | float],
    *,
    title: str,
    highlights: Sequence[BarHighlight] = (),
    width: int | None = None,
    height: int | None = None,
) -> str:
    """Return a bar chart of ``values`` as text with terminal color codes.

    A bar named by several highlights takes the color of the first one, and
    an index outside the values is ignored. ``width`` and ``height`` are the
    number of text columns and lines of the whole chart (default: the size of
    the terminal).
    """
    plotext.clear_figure()
    if width is not None or height is not None:
        plotext.plotsize(width or plotext.terminal_width(), height or plotext.terminal_height())
    count = len(values)
    claimed: set[int] = set()
    highlighted: list[tuple[list[int], BarHighlight]] = []
    for highlight in highlights:
        chosen = sorted(index for index in set(highlight.indices) - claimed if 0 <= index < count)
        claimed.update(chosen)
        if chosen:
            highlighted.append((chosen, highlight))
    _draw_bars(values, [index for index in range(count) if index not in claimed], PLAIN_BAR_COLOR)
    for chosen, highlight in highlighted:
        _draw_bars(values, chosen, highlight.color, label=highlight.label)
    if count:
        plotext.xlim(-0.5, count - 0.5)
        plotext.xticks(list(range(0, count, math.ceil(count / MAXIMUM_BAR_LABELS))))
    plotext.title(title)
    plotext.theme("clear")
    return plotext.build()


def _draw_bars(
    values: Sequence[int | float], positions: list[int], color: str, *, label: str | None = None
) -> None:
    """Draw the bars at ``positions`` only, as wide as the bars of a chart with all positions.

    plotext sizes the bars of a series from the spread of its positions, so a
    series that leaves some out is widened to compensate.
    """
    if not positions:
        return
    options: dict[str, object] = {}
    if len(positions) > 1:
        options["width"] = BAR_WIDTH * (len(positions) - 1) / (positions[-1] - positions[0])
    if label is not None:
        options["label"] = label
    plotext.bar(positions, [values[index] for index in positions], color=color, **options)


def render_side_by_side_bar_charts(
    left_values: Sequence[int | float],
    right_values: Sequence[int | float],
    *,
    left_title: str,
    right_title: str,
    height: int | None = None,
    highlights: Sequence[BarHighlight] = (),
) -> str:
    """Return two bar charts next to each other as text with terminal color codes.

    ``height`` is the number of text lines of each chart (default: the height of
    the terminal) and ``highlights`` are drawn in both charts, as in
    :func:`render_bar_chart`. Each chart is drawn on its own, because plotext
    carries the axis limits of a subplot figure over to the next one and can
    then fail to finish.
    """
    width = (plotext.terminal_width() - GAP_COLUMNS) // 2
    left = render_bar_chart(
        left_values, title=left_title, highlights=highlights, width=width, height=height
    ).splitlines()
    right = render_bar_chart(
        right_values, title=right_title, highlights=highlights, width=width, height=height
    ).splitlines()
    return "\n".join(
        f"{one}{' ' * GAP_COLUMNS}{other}" for one, other in zip(left, right, strict=True)
    )


@dataclass(frozen=True)
class ChartSeries:
    """One named line of a line chart."""

    name: str
    x_values: tuple[int | float, ...]
    y_values: tuple[int | float, ...]

    def __post_init__(self) -> None:
        if len(self.x_values) != len(self.y_values):
            raise ValueError(
                f"Series '{self.name}' has {len(self.x_values)} x values "
                f"but {len(self.y_values)} y values"
            )


def line_chart(
    series: Sequence[ChartSeries],
    *,
    title: str,
    x_label: str,
    y_label: str,
    logarithmic_x: bool = False,
    logarithmic_y: bool = False,
) -> None:
    """Render every series as a line on one chart, with a legend naming them."""
    plotext.clear_figure()
    for line in series:
        plotext.plot(list(line.x_values), list(line.y_values), marker="braille", label=line.name)
    plotext.title(title)
    plotext.xlabel(x_label)
    plotext.ylabel(y_label)
    if logarithmic_x:
        plotext.xscale("log")
    if logarithmic_y:
        plotext.yscale("log")
    plotext.theme("clear")
    plotext.show()
