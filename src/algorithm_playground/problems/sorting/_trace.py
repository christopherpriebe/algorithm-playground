"""The sorting trace: sections of array snapshots and operation events.

A trace file is a sequence of sections read until the end of the file. Each
section is a ``u32`` kind followed by its body: kind ``0`` holds state
snapshots and kind ``1`` holds events. Sections may repeat, and their contents
are joined in file order. See :doc:`/problems/sorting` for the byte layout.
"""

from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass
from pathlib import Path
from typing import BinaryIO

from algorithm_playground.core._binary_format import (
    BinaryFormatError,
    read_i32_array,
    read_record_bytes,
    read_sections,
    read_u32,
    read_u64,
)
from algorithm_playground.problems.sorting._events import (
    EVENT_RECORD_BYTES,
    EventLog,
    EventType,
)

__all__ = [
    "EVENT_TRACE_KIND",
    "SNAPSHOT_TRACE_KIND",
    "SortingTrace",
    "choose_start_values",
    "count_operations",
    "read_trace",
]

SNAPSHOT_TRACE_KIND = 0
EVENT_TRACE_KIND = 1


def _read_snapshots(stream: BinaryIO) -> list[tuple[int, ...]]:
    snapshot_count = read_u32(stream)
    return [
        tuple(read_i32_array(stream, read_u64(stream))) for _ in range(snapshot_count)
    ]


def _read_event_records(stream: BinaryIO) -> bytes:
    event_count = read_u64(stream)
    return read_record_bytes(stream, event_count, EVENT_RECORD_BYTES, "events")


def _check_events(events: EventLog, array_length: int) -> None:
    """Raise unless every event names an index inside the array it acts on.

    Raises:
        BinaryFormatError: If an event is invalid for the array.
    """
    problem = events.check(array_length)
    if problem is not None:
        message = f"Invalid event trace: {problem}"
        raise BinaryFormatError(message)


@dataclass(frozen=True, slots=True)
class SortingTrace:
    """What an executable recorded about one run.

    ``snapshots`` are the array states of every snapshot section, in order.
    ``events`` is ``None`` when the trace has no event section and an
    :class:`~algorithm_playground.problems.sorting.EventLog` (possibly empty) when it has. The events act on the
    first snapshot when there is one and on the input otherwise (see
    :func:`~algorithm_playground.problems.sorting.choose_start_values`).
    """

    snapshots: tuple[tuple[int, ...], ...]
    _: KW_ONLY
    events: EventLog | None = None


def choose_start_values(
    trace: SortingTrace, input_values: Sequence[int]
) -> tuple[int, ...]:
    """Return the array the events of a trace act on: the first snapshot, else the input.

    Args:
        trace: The trace whose events are replayed.
        input_values: The input of the run that recorded the trace.

    Returns:
        The array before the first event.
    """
    if trace.snapshots:
        return trace.snapshots[0]
    return tuple(input_values)


def read_trace(path: Path, input_values: Sequence[int]) -> SortingTrace | None:
    """Read a trace file.

    A section kind that is unknown, a section that is truncated, a count that
    promises more than the file holds, an unknown event type, or an event index
    outside the array raises a
    :class:`~algorithm_playground.core.BinaryFormatError`.

    Args:
        path: The trace file.
        input_values: The input of the run. Its length is what event indices
            are checked against when there is no snapshot.

    Returns:
        The trace, or ``None`` when the file holds no snapshots and no events.
    """
    with path.open("rb") as stream:
        sections = read_sections(
            stream,
            {
                SNAPSHOT_TRACE_KIND: _read_snapshots,
                EVENT_TRACE_KIND: _read_event_records,
            },
        )
    snapshots = tuple(
        snapshot for _, body in sections if isinstance(body, list) for snapshot in body
    )
    event_records = [body for _, body in sections if isinstance(body, bytes)]
    events = EventLog.from_records(b"".join(event_records)) if event_records else None
    if not snapshots and events is None:
        return None
    trace = SortingTrace(snapshots, events=events)
    if events is not None:
        _check_events(events, len(choose_start_values(trace, input_values)))
    return trace


def count_operations(trace: SortingTrace) -> dict[str, int] | None:
    """Count the compares, swaps, and writes of a trace.

    Args:
        trace: The trace to count.

    Returns:
        The counts by operation name, or ``None`` when the trace has no event section.
    """
    if trace.events is None:
        return None
    return {
        "compares": trace.events.count_of(EventType.COMPARE),
        "swaps": trace.events.count_of(EventType.SWAP),
        "writes": trace.events.count_of(EventType.WRITE),
    }
