"""Terminal-based visualization helpers (plotext charts, rich UI).

The charts are what a problem uses to draw its frames. The interactive stepper
and the key input it reads are what the ``debug`` command uses to step through
those frames.
"""

import importlib
from typing import TYPE_CHECKING

from algorithm_playground.visualization._charts import (
    AxisScale,
    BarHighlight,
    ChartSeries,
    render_bar_chart,
    render_line_chart,
    render_side_by_side_bar_charts,
)

if TYPE_CHECKING:
    from algorithm_playground.visualization._keys import (
        Key,
        KeyPress,
        KeySource,
        LineKeySource,
        TerminalKeySource,
        decode_key,
        decode_line,
        open_terminal_key_source,
    )
    from algorithm_playground.visualization._stepper import (
        StepperOptions,
        StepperState,
        compute_next_state,
        parse_jump_target,
        show_frame,
        step_through,
    )

__all__ = [
    "AxisScale",
    "BarHighlight",
    "ChartSeries",
    "Key",
    "KeyPress",
    "KeySource",
    "LineKeySource",
    "StepperOptions",
    "StepperState",
    "TerminalKeySource",
    "compute_next_state",
    "decode_key",
    "decode_line",
    "open_terminal_key_source",
    "parse_jump_target",
    "render_bar_chart",
    "render_line_chart",
    "render_side_by_side_bar_charts",
    "show_frame",
    "step_through",
]

# The stepper and its key input are imported on first use, so a problem that
# only draws charts does not load them; only the ``debug`` command needs them.
_LAZY_MODULES = {
    **dict.fromkeys(
        (
            "Key",
            "KeyPress",
            "KeySource",
            "LineKeySource",
            "TerminalKeySource",
            "decode_key",
            "decode_line",
            "open_terminal_key_source",
        ),
        "algorithm_playground.visualization._keys",
    ),
    **dict.fromkeys(
        (
            "StepperOptions",
            "StepperState",
            "compute_next_state",
            "parse_jump_target",
            "show_frame",
            "step_through",
        ),
        "algorithm_playground.visualization._stepper",
    ),
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_MODULES.get(name)
    if module_name is None:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
