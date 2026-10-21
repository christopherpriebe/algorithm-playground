"""Terminal-based visualization helpers (plotext charts, rich UI).

This package exports the charts, which a problem uses to draw its frames. The
interactive stepper and its key input are in
:mod:`algorithm_playground.visualization.stepper` and
:mod:`algorithm_playground.visualization.keys`; they are imported only by the
``debug`` command, so a problem that draws charts does not load them.
"""

from algorithm_playground.visualization.charts import (
    AxisScale,
    BarHighlight,
    ChartSeries,
    line_chart,
    render_bar_chart,
    render_side_by_side_bar_charts,
)

__all__ = [
    "AxisScale",
    "BarHighlight",
    "ChartSeries",
    "line_chart",
    "render_bar_chart",
    "render_side_by_side_bar_charts",
]
