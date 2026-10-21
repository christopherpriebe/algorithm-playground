"""Replaying a trace's events to recover the array after each of them.

The events of a trace say what the executable did, the snapshots say what the
array looked like; replaying the events from the start must reproduce the
snapshots, which :func:`replay_warnings` checks. It also checks that the
snapshots start from an array as long as the input. The replay itself is the
generic :class:`~algorithm_playground.core.replay.StateTimeline`.
"""

from __future__ import annotations

from collections.abc import Sequence

from algorithm_playground.core.replay import DEFAULT_CHECKPOINT_INTERVAL, StateTimeline
from algorithm_playground.problems.sorting.events import EventLog, SortingEvent
from algorithm_playground.problems.sorting.trace import SortingTrace, start_values


def sorting_timeline(
    start: Sequence[int], events: EventLog
) -> StateTimeline[tuple[int, ...], SortingEvent]:
    """Return the timeline of the array ``start`` under ``events``.

    A checkpoint is kept every ``max(256, len(start))`` events, which keeps the
    memory proportional to the number of events while a lookup replays only a
    short stretch.
    """
    return StateTimeline(
        tuple(start),
        events,
        _apply_events,
        checkpoint_interval=max(DEFAULT_CHECKPOINT_INTERVAL, len(start)),
    )


def replay_warnings(trace: SortingTrace, input_values: Sequence[int]) -> list[str]:
    """Return what is inconsistent inside ``trace``, run on ``input_values``.

    A first snapshot whose length differs from the input is reported. When the
    trace also has events and at least two snapshots (the first is where the
    replay starts, the last is what it must reach), the replayed events are
    compared with the final snapshot and the first difference is reported.
    """
    warnings: list[str] = []
    if trace.snapshots:
        first, input_length = len(trace.snapshots[0]), len(input_values)
        if first != input_length:
            warnings.append(
                f"The first snapshot has {first} values, but the input has {input_length}. "
                "A snapshot should show the whole array."
            )
    if trace.events is not None and len(trace.snapshots) >= 2:
        warnings.extend(_replay_difference(trace, trace.events, input_values))
    return warnings


def _apply_events(values: tuple[int, ...], events: Sequence[SortingEvent]) -> tuple[int, ...]:
    log = events if isinstance(events, EventLog) else EventLog.from_events(events)
    updated = list(values)
    log.apply_to(updated)
    return tuple(updated)


def _replay_difference(
    trace: SortingTrace, events: EventLog, input_values: Sequence[int]
) -> list[str]:
    replayed = sorting_timeline(start_values(trace, input_values), events).final_state
    final = trace.snapshots[-1]
    if replayed == final:
        return []
    prefix = (
        f"Replaying the {len(events)} events from the first snapshot does not give "
        "the final snapshot"
    )
    if len(replayed) != len(final):
        return [
            f"{prefix}: the replayed array has {len(replayed)} values, the snapshot {len(final)}."
        ]
    position = next(index for index in range(len(final)) if replayed[index] != final[index])
    return [
        f"{prefix}: first difference at index {position} (replayed {replayed[position]}, "
        f"snapshot {final[position]}). The events and the snapshots disagree, so one of "
        "them is recorded wrongly."
    ]
