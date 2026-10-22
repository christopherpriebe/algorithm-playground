"""Replaying a trace's events to recover the array after each of them.

The events of a trace say what the executable did, the snapshots say what the
array looked like; replaying the events from the start must reproduce the
snapshots, which :func:`find_replay_warnings` checks. It also checks that the
snapshots start from an array as long as the input. The replay itself is the
generic :class:`~algorithm_playground.core.StateTimeline`.
"""

from collections.abc import Sequence

from algorithm_playground.core._replay import DEFAULT_CHECKPOINT_INTERVAL, StateTimeline
from algorithm_playground.problems.sorting._events import EventLog, SortingEvent
from algorithm_playground.problems.sorting._trace import (
    SortingTrace,
    choose_start_values,
)

__all__ = ["build_sorting_timeline", "find_replay_warnings"]

MINIMUM_SNAPSHOTS_TO_REPLAY = 2


def _apply_events(
    values: tuple[int, ...], events: Sequence[SortingEvent]
) -> tuple[int, ...]:
    log = events if isinstance(events, EventLog) else EventLog.from_events(events)
    updated = list(values)
    log.apply_to(updated)
    return tuple(updated)


def _warn_about_first_snapshot(trace: SortingTrace, input_length: int) -> list[str]:
    """Report a first snapshot whose length differs from the input.

    Returns:
        The warnings, empty when the first snapshot has the input length.
    """
    snapshot_length = len(trace.snapshots[0])
    if snapshot_length == input_length:
        return []
    return [
        (
            f"The first snapshot has {snapshot_length} values, but the input has "
            f"{input_length}. A snapshot should show the whole array."
        )
    ]


def _warn_about_replay(
    trace: SortingTrace, events: EventLog, input_values: Sequence[int]
) -> list[str]:
    """Report the first difference between the replayed events and the final snapshot.

    Returns:
        The warnings, empty when the replay matches the final snapshot.
    """
    replayed = build_sorting_timeline(
        choose_start_values(trace, input_values), events
    ).final_state
    final = trace.snapshots[-1]
    if replayed == final:
        return []
    prefix = (
        f"Replaying the {len(events)} events from the first snapshot does not give "
        "the final snapshot"
    )
    if len(replayed) != len(final):
        return [
            (
                f"{prefix}: the replayed array has {len(replayed)} values, "
                f"the snapshot {len(final)}."
            )
        ]
    position = next(
        index for index in range(len(final)) if replayed[index] != final[index]
    )
    return [
        (
            f"{prefix}: first difference at index {position} "
            f"(replayed {replayed[position]}, snapshot {final[position]}). "
            "The events and the snapshots disagree, so one of them is recorded wrongly."
        )
    ]


def build_sorting_timeline(
    start: Sequence[int], events: EventLog
) -> StateTimeline[tuple[int, ...], SortingEvent]:
    """Build the timeline of an array under a sequence of events.

    A checkpoint is kept every ``max(256, len(start))`` events, which keeps the
    memory proportional to the number of events while a lookup replays only a
    short stretch.

    Args:
        start: The array before the first event.
        events: The events to replay.

    Returns:
        A timeline that gives the array after any number of events.
    """
    return StateTimeline(
        tuple(start),
        events,
        _apply_events,
        checkpoint_interval=max(DEFAULT_CHECKPOINT_INTERVAL, len(start)),
    )


def find_replay_warnings(trace: SortingTrace, input_values: Sequence[int]) -> list[str]:
    """Report what is inconsistent inside a trace.

    A first snapshot whose length differs from the input is reported. When the
    trace also has events and at least two snapshots (the first is where the
    replay starts, the last is what it must reach), the replayed events are
    compared with the final snapshot and the first difference is reported.

    Args:
        trace: The trace to check.
        input_values: The input of the run that recorded the trace.

    Returns:
        One message for each inconsistency; empty when the trace is consistent.
    """
    warnings: list[str] = []
    if trace.snapshots:
        warnings.extend(_warn_about_first_snapshot(trace, len(input_values)))
    if trace.events is not None and len(trace.snapshots) >= MINIMUM_SNAPSHOTS_TO_REPLAY:
        warnings.extend(_warn_about_replay(trace, trace.events, input_values))
    return warnings
