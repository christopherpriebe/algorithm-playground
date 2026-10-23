#!/usr/bin/env python3
"""Instrumented sorters that record compare, swap, and write events plus snapshots.

Importable, for tests that need the events of a known algorithm, and runnable
as an executable of the sorting contract::

    python3 instrumented_sort.py [--events-only] [--wrong-final-snapshot] insertion|merge \\
        INPUT OUTPUT [TRACE]

The trace holds a snapshot section (the input, then the array after each pass of
insertion sort or the final array of merge sort) and an event section, unless
``--events-only`` leaves the snapshots out. ``--wrong-final-snapshot`` records a final
snapshot that the events do not lead to. The encoder here is written from the
documented byte layout and shares no code with the decoder it is used to test.
"""

import struct
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

COMPARE, SWAP, WRITE = 0, 1, 2
Event = tuple[int, int, int]


@dataclass
class Recording:
    """The outcome of an instrumented sort: the sorted values, the events and the snapshots."""

    result: list[int]
    events: list[Event]
    snapshots: list[list[int]]


def insertion_sort(values: Sequence[int]) -> Recording:
    """Sort by insertion with adjacent swaps, taking a snapshot after every pass."""
    data = list(values)
    events: list[Event] = []
    snapshots = [list(data)]
    for end in range(1, len(data)):
        position = end
        while position > 0:
            events.append((COMPARE, position - 1, position))
            if data[position - 1] <= data[position]:
                break
            data[position - 1], data[position] = data[position], data[position - 1]
            events.append((SWAP, position - 1, position))
            position -= 1
        snapshots.append(list(data))
    return Recording(data, events, snapshots)


def merge_sort(values: Sequence[int]) -> Recording:
    """Sort top-down by merging, writing merged runs back, with snapshots of the input and result."""
    data = list(values)
    events: list[Event] = []

    def sort_range(low: int, high: int) -> None:
        if high - low < 2:
            return
        middle = (low + high) // 2
        sort_range(low, middle)
        sort_range(middle, high)
        left, right = data[low:middle], data[middle:high]
        left_index, right_index, write_index = 0, 0, low
        while left_index < len(left) and right_index < len(right):
            events.append((COMPARE, low + left_index, middle + right_index))
            if left[left_index] <= right[right_index]:
                data[write_index] = left[left_index]
                left_index += 1
            else:
                data[write_index] = right[right_index]
                right_index += 1
            events.append((WRITE, write_index, data[write_index] % 2**32))
            write_index += 1
        for rest in (left[left_index:], right[right_index:]):
            for value in rest:
                data[write_index] = value
                events.append((WRITE, write_index, value % 2**32))
                write_index += 1

    sort_range(0, len(data))
    return Recording(data, events, [list(values), list(data)])


ALGORITHMS = {"insertion": insertion_sort, "merge": merge_sort}


def encode_trace(
    snapshots: Iterable[Sequence[int]] | None = None,
    events: Iterable[Event] | None = None,
) -> bytes:
    """Encode the sections of a trace file; leave out a section by passing ``None``."""
    encoded = bytearray()
    if snapshots is not None:
        listed = [list(snapshot) for snapshot in snapshots]
        encoded += struct.pack("<II", 0, len(listed))
        for snapshot in listed:
            encoded += struct.pack(f"<Q{len(snapshot)}i", len(snapshot), *snapshot)
    if events is not None:
        listed_events = list(events)
        encoded += struct.pack("<IQ", 1, len(listed_events))
        for event_type, first, second in listed_events:
            encoded += struct.pack("<BII", event_type, first, second % 2**32)
    return bytes(encoded)


def main(arguments: list[str]) -> int:
    """Run the sorting contract: sort INPUT to OUTPUT and optionally write TRACE.

    Args:
        arguments: The command line, starting with the program name.

    Returns:
        The exit status: zero on success, two for a usage error.
    """
    events_only = "--events-only" in arguments
    wrong_final = "--wrong-final-snapshot" in arguments
    arguments = [argument for argument in arguments if not argument.startswith("--")]
    if len(arguments) not in (4, 5) or arguments[1] not in ALGORITHMS:
        sys.stdout.write(
            "usage: instrumented_sort.py [--events-only] insertion|merge INPUT OUTPUT [TRACE]\n"
        )
        return 2
    raw = Path(arguments[2]).read_bytes()
    (count,) = struct.unpack_from("<Q", raw)
    recording = ALGORITHMS[arguments[1]](struct.unpack_from(f"<{count}i", raw, 8))
    Path(arguments[3]).write_bytes(struct.pack(f"<Q{count}i", count, *recording.result))
    if len(arguments) == 5:
        snapshots = recording.snapshots
        if wrong_final:
            snapshots = [*snapshots[:-1], snapshots[0]]
        trace = encode_trace(None if events_only else snapshots, recording.events)
        Path(arguments[4]).write_bytes(trace)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
