"""Tests for the snapshot and event sections of sorting traces and their operation counts."""

import random
import struct
from collections.abc import Callable
from pathlib import Path

import pytest

from algorithm_playground.core import BinaryFormatError
from algorithm_playground.problems.sorting import (
    EVENT_TRACE_KIND,
    SNAPSHOT_TRACE_KIND,
    EventLog,
    EventType,
    SortingEvent,
    SortingProblem,
    SortingTrace,
    choose_start_values,
    count_operations,
    read_trace,
)
from helpers.instrumented_sort import (
    COMPARE,
    SWAP,
    WRITE,
    Recording,
    encode_trace,
    insertion_sort,
    merge_sort,
)
from helpers.sorting_traces import decode_trace, write_trace

COMPARE_EVENT, SWAP_EVENT, WRITE_EVENT = (
    EventType.COMPARE,
    EventType.SWAP,
    EventType.WRITE,
)


def test_state_snapshot_trace_decodes(tmp_path: Path) -> None:
    """Test a trace made of state snapshots decodes to those snapshots and no events."""
    snapshots = [[3, 1, 2], [1, 3, 2], [1, 2, 3]]

    trace = decode_trace(tmp_path, encode_trace(snapshots=snapshots))

    assert trace.snapshots == ((3, 1, 2), (1, 3, 2), (1, 2, 3))
    assert trace.events is None


def test_the_single_kind_zero_file_of_version_one_is_still_valid(
    tmp_path: Path,
) -> None:
    """Test a version one trace file with a single snapshot section still decodes."""
    raw = struct.pack("<II", SNAPSHOT_TRACE_KIND, 1) + struct.pack("<Q2i", 2, 5, 4)

    trace = decode_trace(tmp_path, raw)

    assert trace.snapshots == ((5, 4),)


def test_trace_with_an_absurd_snapshot_length_raises(tmp_path: Path) -> None:
    """Test a snapshot that declares more values than the file holds is rejected."""
    raw = struct.pack("<IIQ", SNAPSHOT_TRACE_KIND, 1, 2**64 - 1)
    path = write_trace(tmp_path, raw)

    with pytest.raises(BinaryFormatError, match="Declared"):
        read_trace(path, [])


def test_an_empty_file_is_no_trace(tmp_path: Path) -> None:
    """Test an empty trace file decodes to no trace."""
    path = write_trace(tmp_path, b"")

    assert read_trace(path, [1, 2]) is None


def test_a_snapshot_section_without_snapshots_is_no_trace(tmp_path: Path) -> None:
    """Test a trace file with a snapshot section that holds no snapshots is no trace."""
    path = write_trace(tmp_path, encode_trace(snapshots=[]))

    assert read_trace(path, []) is None


def test_unknown_trace_kind_raises(tmp_path: Path) -> None:
    """Test a section of an unknown kind is rejected."""
    path = write_trace(tmp_path, struct.pack("<I", 99))

    with pytest.raises(BinaryFormatError, match="Unsupported trace kind: 99"):
        read_trace(path, [])


def test_a_truncated_section_header_raises(tmp_path: Path) -> None:
    """Test a file that ends inside a section header is rejected."""
    path = write_trace(tmp_path, encode_trace(snapshots=[[1]]) + b"\x01\x00")

    with pytest.raises(BinaryFormatError, match="end of stream"):
        read_trace(path, [1])


def test_a_trace_without_events_counts_no_operations(tmp_path: Path) -> None:
    """Test a trace without events has no operation counts."""
    trace = decode_trace(tmp_path, encode_trace(snapshots=[[1]]))

    assert count_operations(trace) is None


def test_events_decode_with_signed_write_values(tmp_path: Path) -> None:
    """Test events decode in order with the value of a write read as signed."""
    events = [(COMPARE, 0, 1), (SWAP, 0, 1), (WRITE, 2, -3)]

    trace = decode_trace(tmp_path, encode_trace(events=events), input_values=[5, 4, 9])

    assert trace.events is not None
    assert list(trace.events) == [
        SortingEvent(EventType.COMPARE, 0, 1),
        SortingEvent(EventType.SWAP, 0, 1),
        SortingEvent(EventType.WRITE, 2, -3),
    ]


def test_without_snapshots_the_events_start_from_the_input(tmp_path: Path) -> None:
    """Test a trace without snapshots starts replaying from the input."""
    trace = decode_trace(
        tmp_path, encode_trace(events=[(SWAP, 0, 1)]), input_values=[5, 4]
    )

    assert trace.snapshots == ()
    assert choose_start_values(trace, [5, 4]) == (5, 4)


def test_with_snapshots_the_events_start_from_the_first_one(tmp_path: Path) -> None:
    """Test a trace with snapshots starts replaying from the first snapshot."""
    raw = encode_trace(snapshots=[[7, 8], [8, 7]], events=[(SWAP, 0, 1)])
    trace = decode_trace(tmp_path, raw, input_values=[1, 2])

    assert choose_start_values(trace, [1, 2]) == (7, 8)


def test_an_event_section_with_no_events_is_a_trace_that_did_nothing(
    tmp_path: Path,
) -> None:
    """Test an event section without events decodes to an empty log and zero counts."""
    trace = decode_trace(tmp_path, encode_trace(events=[]), input_values=[1])

    assert trace.events == EventLog.from_events([])
    assert count_operations(trace) == {"compares": 0, "swaps": 0, "writes": 0}


def test_sections_may_repeat_and_are_joined_in_file_order(tmp_path: Path) -> None:
    """Test repeated sections are joined in the order they appear in the file."""
    raw = (
        encode_trace(snapshots=[[2, 1]], events=[(COMPARE, 0, 1)])
        + encode_trace(events=[(SWAP, 0, 1)])
        + encode_trace(snapshots=[[1, 2]])
    )

    trace = decode_trace(tmp_path, raw)

    assert trace.snapshots == ((2, 1), (1, 2))
    assert trace.events is not None
    assert [event.describe() for event in trace.events] == [
        "compare(0, 1)",
        "swap(0, 1)",
    ]


def test_an_event_section_may_come_before_the_snapshots_that_give_the_length(
    tmp_path: Path,
) -> None:
    """Test an event section before the snapshots is checked against their length."""
    raw = encode_trace(events=[(SWAP, 0, 2)]) + encode_trace(snapshots=[[3, 2, 1]])

    trace = decode_trace(tmp_path, raw)

    assert choose_start_values(trace, []) == (3, 2, 1)


def test_a_count_larger_than_the_file_raises_before_reading(tmp_path: Path) -> None:
    """Test an event count larger than the file is rejected before any event is read."""
    path = write_trace(tmp_path, struct.pack("<IQ", EVENT_TRACE_KIND, 2**64 - 1))

    with pytest.raises(BinaryFormatError, match="Declared 18446744073709551615 events"):
        read_trace(path, [])


def test_a_count_that_needs_more_bytes_than_remain_raises(tmp_path: Path) -> None:
    """Test an event count that needs more bytes than remain is rejected."""
    raw = (
        struct.pack("<IQ", EVENT_TRACE_KIND, 2)
        + struct.pack("<BII", 0, 0, 1)
        + b"\x00" * 8
    )
    path = write_trace(tmp_path, raw)

    with pytest.raises(BinaryFormatError, match=r"Declared 2 events \(18 bytes\)"):
        read_trace(path, [1, 2])


def test_an_unknown_event_type_raises_naming_the_event(tmp_path: Path) -> None:
    """Test an event of an unknown type is rejected with the position of the event."""
    path = write_trace(tmp_path, encode_trace(events=[(COMPARE, 0, 1), (9, 0, 1)]))

    with pytest.raises(BinaryFormatError, match="event 1 has the unknown type 9"):
        read_trace(path, [1, 2])


def test_an_index_outside_the_input_raises_naming_the_event(tmp_path: Path) -> None:
    """Test an event naming an index outside the input is rejected with its position."""
    path = write_trace(tmp_path, encode_trace(events=[(COMPARE, 0, 1), (SWAP, 1, 2)]))

    with pytest.raises(
        BinaryFormatError, match="event 1 names index 2, but the array has 2"
    ):
        read_trace(path, [5, 6])


def test_indices_are_checked_against_the_snapshot_not_the_input(tmp_path: Path) -> None:
    """Test event indices are checked against the length of the snapshot."""
    path = write_trace(
        tmp_path, encode_trace(snapshots=[[1, 2]], events=[(SWAP, 0, 2)])
    )

    with pytest.raises(BinaryFormatError, match="array has 2 elements"):
        read_trace(path, [1, 2, 3])


def test_a_write_value_may_be_any_i32_bit_pattern(tmp_path: Path) -> None:
    """Test the value of a write may be any 32-bit pattern, read as signed."""
    trace = decode_trace(
        tmp_path, encode_trace(events=[(WRITE, 0, 2**31 + 5)]), input_values=[1]
    )

    assert trace.events is not None
    assert trace.events[0].second == 5 - 2**31


def test_the_problem_passes_the_input_to_the_decoder(tmp_path: Path) -> None:
    """Test the sorting problem decodes a trace against the input it is given."""
    path = write_trace(tmp_path, encode_trace(events=[(SWAP, 0, 1)]))

    trace = SortingProblem().deserialize_trace(path, [2, 1])

    assert isinstance(trace, SortingTrace)
    with pytest.raises(BinaryFormatError, match="array has 1 elements"):
        SortingProblem().deserialize_trace(path, [2])


@pytest.mark.parametrize("algorithm", [insertion_sort, merge_sort])
def test_counts_match_the_events_that_were_written(
    tmp_path: Path, algorithm: Callable[[list[int]], Recording]
) -> None:
    """Test the operation counts equal the number of events of each type."""
    values = random.Random(5).sample(range(1000), 30)  # noqa: S311  seeded generator for reproducible inputs, not cryptography
    recording = algorithm(values)
    trace = decode_trace(
        tmp_path,
        encode_trace(recording.snapshots, recording.events),
        input_values=values,
    )

    counts = count_operations(trace)

    assert counts == {
        "compares": sum(event[0] == COMPARE for event in recording.events),
        "swaps": sum(event[0] == SWAP for event in recording.events),
        "writes": sum(event[0] == WRITE for event in recording.events),
    }


def test_the_problem_reports_the_counts(tmp_path: Path) -> None:
    """Test the sorting problem reports the operation counts of a trace."""
    trace = decode_trace(
        tmp_path, encode_trace(events=[(COMPARE, 0, 1), (COMPARE, 1, 2)]), [3, 2, 1]
    )

    counts = SortingProblem().operation_counts([3, 2, 1], [1, 2, 3], trace)

    assert counts == {"compares": 2, "swaps": 0, "writes": 0}


def test_insertion_sort_of_sorted_input_compares_each_neighbor_once() -> None:
    """Test the instrumented insertion sort compares each neighbor of a sorted input once."""
    recording = insertion_sort(list(range(10)))

    assert [event[0] for event in recording.events] == [COMPARE] * 9
