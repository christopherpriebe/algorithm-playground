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

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Sequence

from algorithm_playground.core.frames import Frame, FrameSequence
from algorithm_playground.problems.sorting.events import EventLog, EventType
from algorithm_playground.problems.sorting.replay import sorting_timeline
from algorithm_playground.problems.sorting.trace import SortingTrace, start_values
from algorithm_playground.visualization import (
    BarHighlight,
    render_bar_chart,
    render_side_by_side_bar_charts,
)

CHART_HEIGHT = 18
MAXIMUM_LISTED_INDICES = 12
MAXIMUM_LISTED_VALUES = 4
EVENT_COLORS = {
    EventType.COMPARE: ("yellow", "compared"),
    EventType.SWAP: ("red", "swapped"),
    EventType.WRITE: ("magenta", "written"),
}
CHANGED_COLOR = "red"


class _Ranks:
    """Bar heights: the rank of a value among the distinct values of the starting array."""

    def __init__(self, start: Iterable[int]) -> None:
        self._universe = sorted(set(start))

    def heights(self, values: Sequence[int]) -> list[int]:
        return [bisect_left(self._universe, value) + 1 for value in values]


def _describe_values(values: Sequence[int], indices: Sequence[int]) -> str:
    """List the values at ``indices`` as ``[2] = 17, [3] = -4``, shortened when there are many."""
    listed = ", ".join(f"[{index}] = {values[index]}" for index in indices[:MAXIMUM_LISTED_VALUES])
    return listed + (", ..." if len(indices) > MAXIMUM_LISTED_VALUES else "")


def sorting_trace_frames(input_values: Sequence[int], trace: SortingTrace) -> Sequence[Frame]:
    """Return the frames of ``trace``: one per event plus the start, else one per snapshot.

    ``input_values`` is the array the events act on when the trace has no snapshot.
    """
    if trace.events is not None:
        return _event_frames(start_values(trace, input_values), trace.events)
    return _snapshot_frames(trace)


def sorting_input_output_frame(input_data: list[int], output: list[int]) -> Frame:
    """Return the input and the output side by side."""
    if not input_data:
        return Frame("(empty input)")
    ranks = _Ranks(input_data)
    body = render_side_by_side_bar_charts(
        ranks.heights(input_data),
        ranks.heights(output),
        left_title="input",
        right_title="output (sorted)",
    )
    return Frame(body, caption="input and output (bar height = rank among the input values)")


def _event_frames(start: tuple[int, ...], events: EventLog) -> FrameSequence:
    timeline = sorting_timeline(start, events)
    ranks = _Ranks(start)
    event_count = len(events)

    def build(position: int) -> Frame:
        values = timeline.state_after(position)
        totals = (
            f"so far: {events.count_of(EventType.COMPARE, before=position)} compares, "
            f"{events.count_of(EventType.SWAP, before=position)} swaps, "
            f"{events.count_of(EventType.WRITE, before=position)} writes"
        )
        title = f"{len(values)} values (bar height = rank)"
        heights = ranks.heights(values)
        if position == 0:
            body = render_bar_chart(heights, title=title, height=CHART_HEIGHT)
            return Frame(body, f"start: {event_count} events follow\n{totals}")
        event = events[position - 1]
        color, label = EVENT_COLORS[event.event_type]
        indices = tuple(sorted(set(event.indices())))
        body = render_bar_chart(
            heights,
            title=title,
            highlights=(BarHighlight(indices, color, label),),
            height=CHART_HEIGHT,
        )
        return Frame(
            body,
            f"event {position} / {event_count}: {event.describe()}\n"
            f"values now: {_describe_values(values, indices)}\n{totals}",
            indices,
        )

    return FrameSequence(event_count + 1, build)


def _snapshot_frames(trace: SortingTrace) -> FrameSequence:
    snapshots = trace.snapshots
    ranks = _Ranks(snapshots[0] if snapshots else ())

    def build(position: int) -> Frame:
        values = snapshots[position]
        title = f"snapshot {position + 1} / {len(snapshots)} (bar height = rank)"
        changed: tuple[int, ...] = ()
        if position > 0 and len(snapshots[position - 1]) == len(values):
            previous = snapshots[position - 1]
            changed = tuple(
                index for index in range(len(values)) if values[index] != previous[index]
            )
        highlights = (BarHighlight(changed, CHANGED_COLOR, "changed"),) if changed else ()
        body = render_bar_chart(
            ranks.heights(values), title=title, highlights=highlights, height=CHART_HEIGHT
        )
        return Frame(body, _snapshot_caption(position, values, changed), changed)

    return FrameSequence(len(snapshots), build)


def _snapshot_caption(position: int, values: Sequence[int], changed: tuple[int, ...]) -> str:
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
