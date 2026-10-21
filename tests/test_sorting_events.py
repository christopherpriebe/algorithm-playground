"""Tests for the compact event log and the event objects it hands out."""

from __future__ import annotations

import struct

import pytest

from algorithm_playground.problems.sorting import EventLog, EventType, SortingEvent

COMPARE, SWAP, WRITE = EventType.COMPARE, EventType.SWAP, EventType.WRITE


def record(event_type: int, first: int, second: int) -> bytes:
    return struct.pack("<BII", event_type, first, second)


class TestSortingEvent:
    def test_describes_itself_by_type_and_fields(self) -> None:
        assert SortingEvent(SWAP, 2, 3).describe() == "swap(2, 3)"
        assert SortingEvent(WRITE, 4, -7).describe() == "write(4, -7)"

    def test_a_write_touches_one_index_and_the_others_two(self) -> None:
        assert SortingEvent(WRITE, 4, 99).indices() == (4,)
        assert SortingEvent(COMPARE, 1, 6).indices() == (1, 6)


class TestEventLog:
    def test_records_decode_to_events_in_order(self) -> None:
        log = EventLog.from_records(record(0, 1, 2) + record(1, 3, 4) + record(2, 5, 6))
        assert list(log) == [
            SortingEvent(COMPARE, 1, 2),
            SortingEvent(SWAP, 3, 4),
            SortingEvent(WRITE, 5, 6),
        ]
        assert len(log) == 3

    def test_a_write_value_is_a_signed_bit_pattern(self) -> None:
        log = EventLog.from_records(record(2, 0, 0xFFFFFFFF) + record(2, 1, 0x80000000))
        assert [event.second for event in log] == [-1, -(2**31)]

    def test_a_swap_index_above_the_i32_range_is_not_made_negative(self) -> None:
        assert EventLog.from_records(record(1, 0, 0xFFFFFFFF))[0].second == 0xFFFFFFFF

    def test_events_built_from_objects_round_trip(self) -> None:
        events = [SortingEvent(WRITE, 2, -5), SortingEvent(SWAP, 0, 1), SortingEvent(COMPARE, 1, 2)]
        log = EventLog.from_events(events)
        assert list(log) == events
        assert log == EventLog.from_records(
            record(2, 2, 2**32 - 5) + record(1, 0, 1) + record(0, 1, 2)
        )

    def test_a_length_that_is_not_a_whole_number_of_records_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="whole number"):
            EventLog.from_records(record(0, 1, 2) + b"\x00")

    def test_indexing_and_slicing(self) -> None:
        log = EventLog.from_events(
            [SortingEvent(COMPARE, position, position + 1) for position in range(5)]
        )
        assert log[-1] == SortingEvent(COMPARE, 4, 5)
        assert list(log[1:3]) == [SortingEvent(COMPARE, 1, 2), SortingEvent(COMPARE, 2, 3)]
        with pytest.raises(IndexError):
            log[5]

    def test_logs_with_the_same_events_are_equal(self) -> None:
        events = [SortingEvent(SWAP, 0, 1)]
        assert EventLog.from_events(events) == EventLog.from_events(events)
        assert EventLog.from_events(events) != EventLog.from_events([SortingEvent(SWAP, 0, 2)])
        assert EventLog.from_events([]) != []

    def test_counts_one_type_among_the_first_events(self) -> None:
        log = EventLog.from_events(
            [SortingEvent(COMPARE, 0, 1), SortingEvent(SWAP, 0, 1), SortingEvent(COMPARE, 1, 2)]
        )
        assert log.count_of(COMPARE) == 2
        assert log.count_of(COMPARE, before=1) == 1
        assert log.count_of(WRITE) == 0

    def test_applying_events_swaps_and_writes_but_compares_change_nothing(self) -> None:
        log = EventLog.from_events(
            [SortingEvent(COMPARE, 0, 1), SortingEvent(SWAP, 0, 2), SortingEvent(WRITE, 1, -9)]
        )
        values = [1, 2, 3]
        log.apply_to(values)
        assert values == [3, -9, 1]
        partial = [1, 2, 3]
        log.apply_to(partial, 1, 2)
        assert partial == [3, 2, 1]


class TestCheck:
    def test_a_valid_log_has_no_problem(self) -> None:
        log = EventLog.from_events([SortingEvent(COMPARE, 0, 2), SortingEvent(WRITE, 1, 2**31 - 1)])
        assert log.check(3) is None

    def test_an_empty_log_is_valid_for_an_empty_array(self) -> None:
        assert EventLog.from_events([]).check(0) is None

    def test_names_the_first_event_with_an_index_outside_the_array(self) -> None:
        log = EventLog.from_events(
            [SortingEvent(COMPARE, 0, 1), SortingEvent(SWAP, 1, 3), SortingEvent(SWAP, 9, 0)]
        )
        assert log.check(3) == "event 1 names index 3, but the array has 3 elements"

    def test_the_first_index_is_checked_too(self) -> None:
        assert EventLog.from_events([SortingEvent(WRITE, 4, 0)]).check(4) == (
            "event 0 names index 4, but the array has 4 elements"
        )

    def test_a_write_value_is_not_an_index(self) -> None:
        assert EventLog.from_events([SortingEvent(WRITE, 0, -1)]).check(1) is None

    def test_an_unknown_type_is_reported(self) -> None:
        log = EventLog.from_records(record(0, 0, 1) + record(7, 0, 1))
        assert log.check(2) == "event 1 has the unknown type 7"
