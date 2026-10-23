"""The frames the debug stepper shows for a sorting trace and for an input and output.

A trace with events has one frame for the starting array and one more per
event, each drawn after the event with the touched bars colored: compared,
swapped, or written. The caption names the event, the values it touched, and
the operations done so far. A trace with only snapshots has one frame per
snapshot, with the positions that changed since the previous one colored.

The bars show ranks, not values. Random i32 values differ by billions, which
makes nearly every bar look equally tall once the axis is scaled to the
largest, so a bar's height is the rank of its value among the distinct values
of the starting array (the smallest has height 1). A value that is not among
them, such as one a faulty write stored, takes the height of the next larger
rank. The caption carries the actual values.
"""

from bisect import bisect_left
from collections.abc import Sequence

# The charts are drawn through the package, so code that watches what is drawn
# (a test) can replace them there.
from algorithm_playground import visualization
from algorithm_playground.core._frames import Frame, FrameSequence
from algorithm_playground.problems.sorting._events import EventLog, EventType
from algorithm_playground.problems.sorting._replay import build_sorting_timeline
from algorithm_playground.problems.sorting._trace import (
    SortingTrace,
    choose_start_values,
)
from algorithm_playground.visualization import BarHighlight

__all__ = [
    "CHANGED_COLOR",
    "CHART_HEIGHT",
    "EVENT_COLORS",
    "MAXIMUM_LISTED_INDICES",
    "MAXIMUM_LISTED_VALUES",
    "draw_sorting_input_output_frame",
    "draw_sorting_trace_frames",
]

CHART_HEIGHT = 18
MAXIMUM_LISTED_INDICES = 12
MAXIMUM_LISTED_VALUES = 4
EVENT_COLORS = {
    EventType.COMPARE: ("yellow", "compared"),
    EventType.SWAP: ("red", "swapped"),
    EventType.WRITE: ("magenta", "written"),
}
CHANGED_COLOR = "red"


def _list_distinct_values(start: Sequence[int]) -> list[int]:
    """List the distinct values of the starting array in ascending order.

    Returns:
        The distinct values, sorted.
    """
    return sorted(set(start))


def _rank_heights(distinct_values: Sequence[int], values: Sequence[int]) -> list[int]:
    """Return the bar height of every value: its rank among the distinct starting values."""
    return [bisect_left(distinct_values, value) + 1 for value in values]


def _describe_values(values: Sequence[int], indices: Sequence[int]) -> str:
    """List the values at ``indices`` as ``[2] = 17, [3] = -4``, shortened when there are many.

    Returns:
        The rank-based heights, one per value.
    """
    listed = ", ".join(
        f"[{index}] = {values[index]}" for index in indices[:MAXIMUM_LISTED_VALUES]
    )
    return listed + (", ..." if len(indices) > MAXIMUM_LISTED_VALUES else "")


def _describe_totals(events: EventLog, position: int) -> str:
    """Describe the operations among the first ``position`` events.

    Returns:
        The text listing the values.
    """
    return (
        f"so far: {events.count_of(EventType.COMPARE, before=position)} compares, "
        f"{events.count_of(EventType.SWAP, before=position)} swaps, "
        f"{events.count_of(EventType.WRITE, before=position)} writes"
    )


def _find_changed_indices(
    snapshots: Sequence[tuple[int, ...]], position: int
) -> tuple[int, ...]:
    """Return the indices that differ from the previous snapshot, if it has the same length."""
    values = snapshots[position]
    if position == 0 or len(snapshots[position - 1]) != len(values):
        return ()
    previous = snapshots[position - 1]
    return tuple(
        index for index in range(len(values)) if values[index] != previous[index]
    )


def _describe_snapshot(
    position: int, values: Sequence[int], changed: tuple[int, ...]
) -> str:
    if position == 0:
        return "first snapshot"
    if not changed:
        return "no position changed since the previous snapshot"
    listed = ", ".join(str(index) for index in changed[:MAXIMUM_LISTED_INDICES])
    more = ", ..." if len(changed) > MAXIMUM_LISTED_INDICES else ""
    return (
        f"changed since the previous snapshot: indices {listed}{more}\n"
        f"values now: {_describe_values(values, changed)}"
    )


def _event_frames(start: tuple[int, ...], events: EventLog) -> FrameSequence:
    timeline = build_sorting_timeline(start, events)
    distinct_values = _list_distinct_values(start)
    event_count = len(events)

    def _build_frame(position: int) -> Frame:
        """Build the frame drawn after the first ``position`` events.

        Returns:
            The frame drawn after the first events.
        """
        values = timeline.state_after(position)
        totals = _describe_totals(events, position)
        title = f"{len(values)} values (bar height = rank)"
        heights = _rank_heights(distinct_values, values)
        if position == 0:
            body = visualization.render_bar_chart(
                heights, title=title, height=CHART_HEIGHT
            )
            return Frame(body, caption=f"start: {event_count} events follow\n{totals}")
        event = events[position - 1]
        color, label = EVENT_COLORS[event.event_type]
        indices = tuple(sorted(set(event.indices())))
        body = visualization.render_bar_chart(
            heights,
            title=title,
            highlights=(BarHighlight(indices, color=color, label=label),),
            height=CHART_HEIGHT,
        )
        return Frame(
            body,
            caption=f"event {position} / {event_count}: {event.describe()}\n"
            f"values now: {_describe_values(values, indices)}\n{totals}",
            highlighted_elements=indices,
        )

    return FrameSequence(event_count + 1, _build_frame)


def _snapshot_frames(trace: SortingTrace) -> FrameSequence:
    snapshots = trace.snapshots
    distinct_values = _list_distinct_values(snapshots[0] if snapshots else ())

    def _build_frame(position: int) -> Frame:
        """Build the frame of the snapshot at ``position``.

        Returns:
            The frame of the snapshot.
        """
        values = snapshots[position]
        title = f"snapshot {position + 1} / {len(snapshots)} (bar height = rank)"
        changed = _find_changed_indices(snapshots, position)
        highlights = (
            (BarHighlight(changed, color=CHANGED_COLOR, label="changed"),)
            if changed
            else ()
        )
        body = visualization.render_bar_chart(
            _rank_heights(distinct_values, values),
            title=title,
            highlights=highlights,
            height=CHART_HEIGHT,
        )
        return Frame(
            body,
            caption=_describe_snapshot(position, values, changed),
            highlighted_elements=changed,
        )

    return FrameSequence(len(snapshots), _build_frame)


def draw_sorting_trace_frames(
    input_values: Sequence[int], trace: SortingTrace
) -> Sequence[Frame]:
    """Build the frames of a trace: one per event plus the start, else one per snapshot.

    Args:
        input_values: The array the events act on when the trace has no snapshot.
        trace: The trace to draw.

    Returns:
        The frames, built on demand.
    """
    if trace.events is not None:
        return _event_frames(choose_start_values(trace, input_values), trace.events)
    return _snapshot_frames(trace)


def draw_sorting_input_output_frame(input_data: list[int], output: list[int]) -> Frame:
    """Draw the input and the output side by side.

    Args:
        input_data: The array that was sorted.
        output: The array the executable produced.

    Returns:
        A frame with two bar charts, or a note when the input is empty.
    """
    if not input_data:
        return Frame("(empty input)")
    distinct_values = _list_distinct_values(input_data)
    body = visualization.render_side_by_side_bar_charts(
        _rank_heights(distinct_values, input_data),
        _rank_heights(distinct_values, output),
        left_title="input",
        right_title="output (sorted)",
    )
    return Frame(
        body, caption="input and output (bar height = rank among the input values)"
    )
