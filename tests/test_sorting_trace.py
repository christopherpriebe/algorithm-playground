"""Tests for decoding sorting traces, counting their operations, and replaying their events."""

from __future__ import annotations

import random
import struct
from collections.abc import Callable
from pathlib import Path

import pytest
from instrumented_sort import (
    COMPARE,
    SWAP,
    WRITE,
    Recording,
    encode_trace,
    insertion_sort,
    merge_sort,
)

from algorithm_playground.core.binary_format import BinaryFormatError
from algorithm_playground.problems.sorting import (
    EVENT_TRACE_KIND,
    SNAPSHOT_TRACE_KIND,
    EventLog,
    EventType,
    SortingEvent,
    SortingProblem,
    SortingTrace,
)
from algorithm_playground.problems.sorting.replay import replay_warnings, sorting_timeline
from algorithm_playground.problems.sorting.trace import count_operations, read_trace, start_values


def write_trace(directory: Path, content: bytes) -> Path:
    path = directory / "trace.bin"
    path.write_bytes(content)
    return path


def decode(directory: Path, content: bytes, input_values: list[int] | None = None) -> SortingTrace:
    trace = read_trace(write_trace(directory, content), input_values or [])
    assert trace is not None
    return trace


class TestSnapshotSections:
    def test_state_snapshot_trace_decodes(self, tmp_path: Path) -> None:
        snapshots = [[3, 1, 2], [1, 3, 2], [1, 2, 3]]
        trace = decode(tmp_path, encode_trace(snapshots=snapshots))
        assert trace.snapshots == ((3, 1, 2), (1, 3, 2), (1, 2, 3))
        assert trace.events is None

    def test_the_single_kind_zero_file_of_version_one_is_still_valid(self, tmp_path: Path) -> None:
        raw = struct.pack("<II", SNAPSHOT_TRACE_KIND, 1) + struct.pack("<Q2i", 2, 5, 4)
        assert decode(tmp_path, raw).snapshots == ((5, 4),)

    def test_trace_with_an_absurd_snapshot_length_raises(self, tmp_path: Path) -> None:
        raw = struct.pack("<IIQ", SNAPSHOT_TRACE_KIND, 1, 2**64 - 1)
        with pytest.raises(BinaryFormatError, match="Declared"):
            read_trace(write_trace(tmp_path, raw), [])

    def test_an_empty_file_is_no_trace(self, tmp_path: Path) -> None:
        assert read_trace(write_trace(tmp_path, b""), [1, 2]) is None

    def test_a_snapshot_section_without_snapshots_is_no_trace(self, tmp_path: Path) -> None:
        assert read_trace(write_trace(tmp_path, encode_trace(snapshots=[])), []) is None

    def test_unknown_trace_kind_raises(self, tmp_path: Path) -> None:
        with pytest.raises(BinaryFormatError, match="Unsupported trace kind: 99"):
            read_trace(write_trace(tmp_path, struct.pack("<I", 99)), [])

    def test_a_truncated_section_header_raises(self, tmp_path: Path) -> None:
        raw = encode_trace(snapshots=[[1]]) + b"\x01\x00"
        with pytest.raises(BinaryFormatError, match="end of stream"):
            read_trace(write_trace(tmp_path, raw), [1])

    def test_a_trace_without_events_counts_no_operations(self, tmp_path: Path) -> None:
        assert count_operations(decode(tmp_path, encode_trace(snapshots=[[1]]))) is None


class TestEventSections:
    def test_events_decode_with_signed_write_values(self, tmp_path: Path) -> None:
        events = [(COMPARE, 0, 1), (SWAP, 0, 1), (WRITE, 2, -3)]
        trace = decode(tmp_path, encode_trace(events=events), input_values=[5, 4, 9])
        assert trace.events is not None
        assert list(trace.events) == [
            SortingEvent(EventType.COMPARE, 0, 1),
            SortingEvent(EventType.SWAP, 0, 1),
            SortingEvent(EventType.WRITE, 2, -3),
        ]

    def test_without_snapshots_the_events_start_from_the_input(self, tmp_path: Path) -> None:
        trace = decode(tmp_path, encode_trace(events=[(SWAP, 0, 1)]), input_values=[5, 4])
        assert trace.snapshots == ()
        assert start_values(trace, [5, 4]) == (5, 4)

    def test_with_snapshots_the_events_start_from_the_first_one(self, tmp_path: Path) -> None:
        raw = encode_trace(snapshots=[[7, 8], [8, 7]], events=[(SWAP, 0, 1)])
        assert start_values(decode(tmp_path, raw, input_values=[1, 2]), [1, 2]) == (7, 8)

    def test_an_event_section_with_no_events_is_a_trace_that_did_nothing(
        self, tmp_path: Path
    ) -> None:
        trace = decode(tmp_path, encode_trace(events=[]), input_values=[1])
        assert trace.events == EventLog.from_events([])
        assert count_operations(trace) == {"compares": 0, "swaps": 0, "writes": 0}

    def test_sections_may_repeat_and_are_joined_in_file_order(self, tmp_path: Path) -> None:
        raw = (
            encode_trace(snapshots=[[2, 1]], events=[(COMPARE, 0, 1)])
            + encode_trace(events=[(SWAP, 0, 1)])
            + encode_trace(snapshots=[[1, 2]])
        )
        trace = decode(tmp_path, raw)
        assert trace.snapshots == ((2, 1), (1, 2))
        assert trace.events is not None
        assert [event.describe() for event in trace.events] == ["compare(0, 1)", "swap(0, 1)"]

    def test_an_event_section_may_come_before_the_snapshots_that_give_the_length(
        self, tmp_path: Path
    ) -> None:
        raw = encode_trace(events=[(SWAP, 0, 2)]) + encode_trace(snapshots=[[3, 2, 1]])
        assert start_values(decode(tmp_path, raw), []) == (3, 2, 1)

    def test_a_count_larger_than_the_file_raises_before_reading(self, tmp_path: Path) -> None:
        raw = struct.pack("<IQ", EVENT_TRACE_KIND, 2**64 - 1)
        with pytest.raises(BinaryFormatError, match="Declared 18446744073709551615 events"):
            read_trace(write_trace(tmp_path, raw), [])

    def test_a_count_that_needs_more_bytes_than_remain_raises(self, tmp_path: Path) -> None:
        raw = struct.pack("<IQ", EVENT_TRACE_KIND, 2) + struct.pack("<BII", 0, 0, 1) + b"\x00" * 8
        with pytest.raises(BinaryFormatError, match=r"Declared 2 events \(18 bytes\)"):
            read_trace(write_trace(tmp_path, raw), [1, 2])

    def test_an_unknown_event_type_raises_naming_the_event(self, tmp_path: Path) -> None:
        raw = encode_trace(events=[(COMPARE, 0, 1), (9, 0, 1)])
        with pytest.raises(BinaryFormatError, match="event 1 has the unknown type 9"):
            read_trace(write_trace(tmp_path, raw), [1, 2])

    def test_an_index_outside_the_input_raises_naming_the_event(self, tmp_path: Path) -> None:
        raw = encode_trace(events=[(COMPARE, 0, 1), (SWAP, 1, 2)])
        with pytest.raises(BinaryFormatError, match="event 1 names index 2, but the array has 2"):
            read_trace(write_trace(tmp_path, raw), [5, 6])

    def test_indices_are_checked_against_the_snapshot_not_the_input(self, tmp_path: Path) -> None:
        raw = encode_trace(snapshots=[[1, 2]], events=[(SWAP, 0, 2)])
        with pytest.raises(BinaryFormatError, match="array has 2 elements"):
            read_trace(write_trace(tmp_path, raw), [1, 2, 3])

    def test_a_write_value_may_be_any_i32_bit_pattern(self, tmp_path: Path) -> None:
        trace = decode(tmp_path, encode_trace(events=[(WRITE, 0, 2**31 + 5)]), input_values=[1])
        assert trace.events is not None
        assert trace.events[0].second == 5 - 2**31

    def test_the_problem_passes_the_input_to_the_decoder(self, tmp_path: Path) -> None:
        path = write_trace(tmp_path, encode_trace(events=[(SWAP, 0, 1)]))
        trace = SortingProblem().deserialize_trace(path, [2, 1])
        assert isinstance(trace, SortingTrace)
        with pytest.raises(BinaryFormatError, match="array has 1 elements"):
            SortingProblem().deserialize_trace(path, [2])


class TestOperationCounts:
    @pytest.mark.parametrize("algorithm", [insertion_sort, merge_sort])
    def test_counts_match_the_events_that_were_written(
        self, tmp_path: Path, algorithm: Callable[[list[int]], Recording]
    ) -> None:
        values = random.Random(5).sample(range(1000), 30)
        recording = algorithm(values)
        trace = decode(
            tmp_path, encode_trace(recording.snapshots, recording.events), input_values=values
        )
        assert count_operations(trace) == {
            "compares": sum(event[0] == COMPARE for event in recording.events),
            "swaps": sum(event[0] == SWAP for event in recording.events),
            "writes": sum(event[0] == WRITE for event in recording.events),
        }

    def test_the_problem_reports_the_counts(self, tmp_path: Path) -> None:
        trace = decode(tmp_path, encode_trace(events=[(COMPARE, 0, 1), (COMPARE, 1, 2)]), [3, 2, 1])
        assert SortingProblem().operation_counts([3, 2, 1], [1, 2, 3], trace) == {
            "compares": 2,
            "swaps": 0,
            "writes": 0,
        }

    def test_insertion_sort_of_sorted_input_compares_each_neighbor_once(self) -> None:
        recording = insertion_sort(list(range(10)))
        assert [event[0] for event in recording.events] == [COMPARE] * 9


class TestReplay:
    @pytest.mark.parametrize("algorithm", [insertion_sort, merge_sort])
    def test_replaying_the_events_sorts_the_input(
        self, algorithm: Callable[[list[int]], Recording]
    ) -> None:
        values = random.Random(2).sample(range(-500, 500), 40)
        recording = algorithm(values)
        timeline = sorting_timeline(values, EventLog.from_events(_events(recording)))
        assert timeline.final_state == tuple(sorted(values))

    def test_every_prefix_is_recovered_across_checkpoints(self) -> None:
        values = random.Random(9).sample(range(100), 30)
        recording = insertion_sort(values)
        log = EventLog.from_events(_events(recording))
        assert len(log) > 2 * 256
        timeline = sorting_timeline(values, log)
        for count in (0, 1, 255, 256, 257, 512, len(log) // 2, len(log)):
            expected = list(values)
            log.apply_to(expected, 0, count)
            assert timeline.state_after(count) == tuple(expected)

    def test_asking_for_more_events_than_exist_raises(self) -> None:
        timeline = sorting_timeline([1], EventLog.from_events([]))
        with pytest.raises(IndexError):
            timeline.state_after(1)

    def test_consistent_events_and_snapshots_give_no_warning(self, tmp_path: Path) -> None:
        values = [3, 1, 2]
        recording = insertion_sort(values)
        trace = decode(tmp_path, encode_trace(recording.snapshots, recording.events), values)
        assert replay_warnings(trace, values) == []
        assert SortingProblem().trace_warnings(values, sorted(values), trace) == []

    def test_a_disagreement_with_the_final_snapshot_is_a_warning_with_the_first_difference(
        self, tmp_path: Path
    ) -> None:
        raw = encode_trace(snapshots=[[3, 1, 2], [1, 2, 3]], events=[(SWAP, 0, 1)])
        warnings = replay_warnings(decode(tmp_path, raw, input_values=[3, 1, 2]), [3, 1, 2])
        assert len(warnings) == 1
        assert "first difference at index 1 (replayed 3, snapshot 2)" in warnings[0]
        assert "1 events" in warnings[0]

    def test_snapshots_of_different_lengths_are_reported_as_such(self, tmp_path: Path) -> None:
        raw = encode_trace(snapshots=[[2, 1], [1]], events=[(SWAP, 0, 1)])
        assert (
            "the replayed array has 2 values, the snapshot 1"
            in replay_warnings(decode(tmp_path, raw, input_values=[2, 1]), [2, 1])[0]
        )

    def test_a_first_snapshot_of_another_length_than_the_input_is_a_warning(
        self, tmp_path: Path
    ) -> None:
        trace = decode(tmp_path, encode_trace(snapshots=[[1, 2, 3]]), input_values=[9])
        assert replay_warnings(trace, [9]) == [
            "The first snapshot has 3 values, but the input has 1. "
            "A snapshot should show the whole array."
        ]

    def test_a_matching_input_and_snapshot_do_not_disagree(self) -> None:
        assert replay_warnings(SortingTrace(((1, 2, 3),)), [3, 2, 1]) == []

    @pytest.mark.parametrize(
        "content",
        [
            encode_trace(snapshots=[[2, 1], [1, 2]]),
            encode_trace(snapshots=[[2, 1]], events=[(SWAP, 0, 1)]),
            encode_trace(events=[(SWAP, 0, 1)]),
        ],
        ids=["no events", "a single snapshot", "no snapshots"],
    )
    def test_there_is_nothing_to_compare_without_events_and_a_first_and_last_snapshot(
        self, tmp_path: Path, content: bytes
    ) -> None:
        assert replay_warnings(decode(tmp_path, content, input_values=[2, 1]), [2, 1]) == []


def _events(recording: Recording) -> list[SortingEvent]:
    return [
        SortingEvent(EventType(kind), first, second) for kind, first, second in recording.events
    ]
