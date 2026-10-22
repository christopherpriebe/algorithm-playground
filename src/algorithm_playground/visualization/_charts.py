"""Thin wrappers around ``plotext`` for the charts the playground draws.

These helpers keep plotext usage isolated so problem implementations and CLI
commands do not need to import plotext directly. The ``render_`` functions
return a chart as text, which is what a problem puts in a frame;
:func:`render_line_chart` prints a chart to standard output.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import cast

import plotext

__all__ = [
    "BAR_WIDTH",
    "GAP_COLUMNS",
    "MAXIMUM_BAR_LABELS",
    "PLAIN_BAR_COLOR",
    "AxisScale",
    "BarHighlight",
    "ChartSeries",
    "render_bar_chart",
    "render_line_chart",
    "render_side_by_side_bar_charts",
]

PLAIN_BAR_COLOR = "blue"
GAP_COLUMNS = 2
BAR_WIDTH = 4 / 5
MAXIMUM_BAR_LABELS = 20


def _draw_bars(
    values: Sequence[int | float],
    positions: list[int],
    color: str,
    *,
    label: str | None = None,
) -> None:
    """Draw the bars at ``positions`` only, as wide as the bars of a chart with all positions.

    plotext sizes the bars of a series from the spread of its positions, so a
    series that leaves some out is widened to compensate.
    """
    if not positions:
        return
    options: dict[str, object] = {}
    if len(positions) > 1:
        options["width"] = (
            BAR_WIDTH * (len(positions) - 1) / (positions[-1] - positions[0])
        )
    if label is not None:
        options["label"] = label
    plotext.bar(
        positions, [values[index] for index in positions], color=color, **options
    )


def _claim_bars(count: int, index_groups: Sequence[Iterable[int]]) -> list[list[int]]:
    """Give every bar to the first group that names it, dropping indices outside the bars.

    Returns:
        The sorted bars each group claimed, in the order of the groups.
    """
    claimed: set[int] = set()
    claims: list[list[int]] = []
    for group in index_groups:
        chosen = sorted(index for index in set(group) - claimed if 0 <= index < count)
        claimed.update(chosen)
        claims.append(chosen)
    return claims


class AxisScale(Enum):
    """How the values of one axis of a line chart are spaced."""

    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"


@dataclass(frozen=True, slots=True)
class BarHighlight:
    """Bars drawn in another color, with a legend entry saying why."""

    indices: tuple[int, ...]
    color: str
    label: str


@dataclass(frozen=True, slots=True)
class ChartSeries:
    """One named line of a line chart.

    Raises:
        ValueError: If there are not as many y values as x values.
    """

    name: str
    x_values: tuple[int | float, ...]
    y_values: tuple[int | float, ...]

    def __post_init__(self) -> None:
        if len(self.x_values) != len(self.y_values):
            message = (
                f"Series '{self.name}' has {len(self.x_values)} x values "
                f"but {len(self.y_values)} y values"
            )
            raise ValueError(message)


def render_bar_chart(
    values: Sequence[int | float],
    *,
    title: str,
    highlights: Sequence[BarHighlight] = (),
    width: int | None = None,
    height: int | None = None,
) -> str:
    """Draw a bar chart as text with terminal color codes.

    A bar named by several highlights takes the color of the first one, and
    an index outside the values is ignored.

    Args:
        values: The height of each bar.
        title: The title above the chart.
        highlights: Bars to draw in another color, each with a legend entry.
        width: The number of text columns of the whole chart (default: the
            width of the terminal).
        height: The number of text lines of the whole chart (default: the
            height of the terminal).

    Returns:
        The chart.
    """
    plotext.clear_figure()
    if width is not None or height is not None:
        plotext.plotsize(
            width or plotext.terminal_width(), height or plotext.terminal_height()
        )
    count = len(values)
    claims = _claim_bars(count, [highlight.indices for highlight in highlights])
    claimed = {index for chosen in claims for index in chosen}
    _draw_bars(
        values,
        [index for index in range(count) if index not in claimed],
        PLAIN_BAR_COLOR,
    )
    for chosen, highlight in zip(claims, highlights, strict=True):
        _draw_bars(values, chosen, highlight.color, label=highlight.label)
    if count:
        plotext.xlim(-0.5, count - 0.5)
        plotext.xticks(list(range(0, count, math.ceil(count / MAXIMUM_BAR_LABELS))))
    plotext.title(title)
    plotext.theme("clear")
    return cast(str, plotext.build())


def render_side_by_side_bar_charts(  # noqa: PLR0913  two charts need two sets of values and titles
    left_values: Sequence[int | float],
    right_values: Sequence[int | float],
    *,
    left_title: str,
    right_title: str,
    height: int | None = None,
    highlights: Sequence[BarHighlight] = (),
) -> str:
    """Draw two bar charts next to each other as text with terminal color codes.

    Each chart is drawn on its own, because plotext carries the axis limits of
    a subplot figure over to the next one and can then fail to finish.

    Args:
        left_values: The height of each bar of the left chart.
        right_values: The height of each bar of the right chart.
        left_title: The title above the left chart.
        right_title: The title above the right chart.
        height: The number of text lines of each chart (default: the height of
            the terminal).
        highlights: Bars to draw in another color in both charts, as in
            :func:`render_bar_chart`.

    Returns:
        The two charts, each half the width of the terminal.
    """
    width = (plotext.terminal_width() - GAP_COLUMNS) // 2
    left = render_bar_chart(
        left_values, title=left_title, highlights=highlights, width=width, height=height
    ).splitlines()
    right = render_bar_chart(
        right_values,
        title=right_title,
        highlights=highlights,
        width=width,
        height=height,
    ).splitlines()
    return "\n".join(
        f"{one}{' ' * GAP_COLUMNS}{other}"
        for one, other in zip(left, right, strict=True)
    )


def render_line_chart(  # noqa: PLR0913  the series, title, two labels and two scales are all needed
    series: Sequence[ChartSeries],
    *,
    title: str,
    x_label: str,
    y_label: str,
    x_scale: AxisScale = AxisScale.LINEAR,
    y_scale: AxisScale = AxisScale.LINEAR,
) -> None:
    """Print every series as a line on one chart to standard output, with a legend naming them.

    Args:
        series: The lines to draw.
        title: The title above the chart.
        x_label: The label of the x axis.
        y_label: The label of the y axis.
        x_scale: How the x axis is spaced.
        y_scale: How the y axis is spaced.
    """
    plotext.clear_figure()
    for line in series:
        plotext.plot(
            list(line.x_values), list(line.y_values), marker="braille", label=line.name
        )
    plotext.title(title)
    plotext.xlabel(x_label)
    plotext.ylabel(y_label)
    if x_scale is AxisScale.LOGARITHMIC:
        plotext.xscale("log")
    if y_scale is AxisScale.LOGARITHMIC:
        plotext.yscale("log")
    plotext.theme("clear")
    plotext.show()
