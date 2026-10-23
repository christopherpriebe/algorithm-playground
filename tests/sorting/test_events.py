"""Tests for sorting events and event logs."""

import struct

import pytest

from algorithm_playground.problems.sorting import (
    EventLog,
    EventType,
    SortingEvent,
)

COMPARE_EVENT, SWAP_EVENT, WRITE_EVENT = (
    EventType.COMPARE,
    EventType.SWAP,
    EventType.WRITE,
)


def pack_record(event_type: int, first: int, second: int) -> bytes:
    """Pack one event the way a trace file stores it."""
    return struct.pack("<BII", event_type, first, second)


def test_describes_itself_by_type_and_fields() -> None:
    """Test an event is described by its type and fields."""
    assert SortingEvent(SWAP_EVENT, 2, 3).describe() == "swap(2, 3)"
    assert SortingEvent(WRITE_EVENT, 4, -7).describe() == "write(4, -7)"


def test_a_write_touches_one_index_and_the_others_two() -> None:
    """Test a write names one index and the other events name two."""
    assert SortingEvent(WRITE_EVENT, 4, 99).indices() == (4,)
    assert SortingEvent(COMPARE_EVENT, 1, 6).indices() == (1, 6)


def test_records_decode_to_events_in_order() -> None:
    """Test records decode to events in the order they were written."""
    log = EventLog.from_records(
        pack_record(0, 1, 2) + pack_record(1, 3, 4) + pack_record(2, 5, 6)
    )

    assert list(log) == [
        SortingEvent(COMPARE_EVENT, 1, 2),
        SortingEvent(SWAP_EVENT, 3, 4),
        SortingEvent(WRITE_EVENT, 5, 6),
    ]
    assert len(log) == 3


def test_a_write_value_is_a_signed_bit_pattern() -> None:
    """Test the value of a write is decoded as a signed 32-bit pattern."""
    log = EventLog.from_records(
        pack_record(2, 0, 0xFFFFFFFF) + pack_record(2, 1, 0x80000000)
    )

    assert [event.second for event in log] == [-1, -(2**31)]


def test_a_swap_index_above_the_i32_range_is_not_made_negative() -> None:
    """Test the second field of a swap stays unsigned."""
    log = EventLog.from_records(pack_record(1, 0, 0xFFFFFFFF))

    assert log[0].second == 0xFFFFFFFF


def test_events_built_from_objects_round_trip() -> None:
    """Test a log built from event objects yields them again and encodes as records."""
    events = [
        SortingEvent(WRITE_EVENT, 2, -5),
        SortingEvent(SWAP_EVENT, 0, 1),
        SortingEvent(COMPARE_EVENT, 1, 2),
    ]

    log = EventLog.from_events(events)

    assert list(log) == events
    assert log == EventLog.from_records(
        pack_record(2, 2, 2**32 - 5) + pack_record(1, 0, 1) + pack_record(0, 1, 2)
    )


def test_a_length_that_is_not_a_whole_number_of_records_is_rejected() -> None:
    """Test records whose length is not a whole number of records are rejected."""
    with pytest.raises(ValueError, match="whole number"):
        EventLog.from_records(pack_record(0, 1, 2) + b"\x00")


def test_a_negative_index_counts_from_the_end() -> None:
    """Test a negative index selects an event counting from the end."""
    log = EventLog.from_events(
        [SortingEvent(COMPARE_EVENT, position, position + 1) for position in range(5)]
    )

    assert log[-1] == SortingEvent(COMPARE_EVENT, 4, 5)


def test_a_slice_selects_a_range_of_events() -> None:
    """Test a slice selects the events in its range."""
    log = EventLog.from_events(
        [SortingEvent(COMPARE_EVENT, position, position + 1) for position in range(5)]
    )

    assert list(log[1:3]) == [
        SortingEvent(COMPARE_EVENT, 1, 2),
        SortingEvent(COMPARE_EVENT, 2, 3),
    ]


def test_an_index_past_the_end_raises_index_error() -> None:
    """Test indexing past the last event raises IndexError."""
    log = EventLog.from_events(
        [SortingEvent(COMPARE_EVENT, position, position + 1) for position in range(5)]
    )

    with pytest.raises(IndexError, match="index out of range"):
        log[5]


def test_logs_with_the_same_events_are_equal() -> None:
    """Test logs holding the same events are equal."""
    events = [SortingEvent(SWAP_EVENT, 0, 1)]

    assert EventLog.from_events(events) == EventLog.from_events(events)


def test_logs_with_different_events_are_not_equal() -> None:
    """Test logs holding different events are not equal."""
    first = EventLog.from_events([SortingEvent(SWAP_EVENT, 0, 1)])
    second = EventLog.from_events([SortingEvent(SWAP_EVENT, 0, 2)])

    assert first != second


def test_a_log_is_not_equal_to_a_list() -> None:
    """Test an empty log is not equal to an empty list."""
    assert EventLog.from_events([]) != []


def test_counts_one_type_among_the_first_events() -> None:
    """Test events of one type are counted, optionally among the first events only."""
    log = EventLog.from_events(
        [
            SortingEvent(COMPARE_EVENT, 0, 1),
            SortingEvent(SWAP_EVENT, 0, 1),
            SortingEvent(COMPARE_EVENT, 1, 2),
        ]
    )

    assert log.count_of(COMPARE_EVENT) == 2
    assert log.count_of(COMPARE_EVENT, before=1) == 1
    assert log.count_of(WRITE_EVENT) == 0


def test_applying_events_swaps_and_writes_but_compares_change_nothing() -> None:
    """Test applying events swaps and writes values while compares change nothing."""
    log = EventLog.from_events(
        [
            SortingEvent(COMPARE_EVENT, 0, 1),
            SortingEvent(SWAP_EVENT, 0, 2),
            SortingEvent(WRITE_EVENT, 1, -9),
        ]
    )
    values = [1, 2, 3]

    log.apply_to(values)

    assert values == [3, -9, 1]


def test_applying_a_range_of_events_applies_only_those() -> None:
    """Test applying a range of events leaves out the events outside it."""
    log = EventLog.from_events(
        [
            SortingEvent(COMPARE_EVENT, 0, 1),
            SortingEvent(SWAP_EVENT, 0, 2),
            SortingEvent(WRITE_EVENT, 1, -9),
        ]
    )
    values = [1, 2, 3]

    log.apply_to(values, 1, 2)

    assert values == [3, 2, 1]


def test_a_valid_log_has_no_problem() -> None:
    """Test a log with every index inside the array reports no problem."""
    log = EventLog.from_events(
        [SortingEvent(COMPARE_EVENT, 0, 2), SortingEvent(WRITE_EVENT, 1, 2**31 - 1)]
    )

    assert log.check(3) is None


def test_an_empty_log_is_valid_for_an_empty_array() -> None:
    """Test an empty log is valid for an empty array."""
    assert EventLog.from_events([]).check(0) is None


def test_names_the_first_event_with_an_index_outside_the_array() -> None:
    """Test the problem names the first event with an index outside the array."""
    log = EventLog.from_events(
        [
            SortingEvent(COMPARE_EVENT, 0, 1),
            SortingEvent(SWAP_EVENT, 1, 3),
            SortingEvent(SWAP_EVENT, 9, 0),
        ]
    )

    assert log.check(3) == "event 1 names index 3, but the array has 3 elements"


def test_the_first_index_is_checked_too() -> None:
    """Test the first index of an event is checked as well as the second."""
    log = EventLog.from_events([SortingEvent(WRITE_EVENT, 4, 0)])

    assert log.check(4) == "event 0 names index 4, but the array has 4 elements"


def test_a_write_value_is_not_an_index() -> None:
    """Test the value of a write is not checked as an index."""
    assert EventLog.from_events([SortingEvent(WRITE_EVENT, 0, -1)]).check(1) is None


def test_an_unknown_type_is_reported() -> None:
    """Test an event of an unknown type is reported."""
    log = EventLog.from_records(pack_record(0, 0, 1) + pack_record(7, 0, 1))

    assert log.check(2) == "event 1 has the unknown type 7"
