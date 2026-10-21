"""The events a sorting executable can record: compares, swaps, and writes.

An event is ``(type, first, second)``. A compare and a swap name two array
indices; a write names an index and the i32 value stored there. A trace can
hold millions of them, so :class:`EventLog` keeps them in three compact
columns and builds a :class:`SortingEvent` only when one is asked for.
"""

from __future__ import annotations

import sys
from array import array
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
from itertools import compress
from typing import overload

EVENT_RECORD_BYTES = 9
_U32_RANGE = 2**32
_I32_LIMIT = 2**31


class EventType(IntEnum):
    """The type byte of an event record."""

    COMPARE = 0
    SWAP = 1
    WRITE = 2


LARGEST_EVENT_TYPE = max(EventType)


@dataclass(frozen=True)
class SortingEvent:
    """One recorded operation.

    For ``COMPARE`` and ``SWAP``, ``first`` and ``second`` are array indices.
    For ``WRITE``, ``first`` is the index written and ``second`` the signed
    i32 value stored there.
    """

    event_type: EventType
    first: int
    second: int

    def describe(self) -> str:
        """Return the event as it is shown to a person, such as ``swap(2, 3)``."""
        return f"{self.event_type.name.lower()}({self.first}, {self.second})"

    def indices(self) -> tuple[int, ...]:
        """Return the array indices the event touches."""
        if self.event_type is EventType.WRITE:
            return (self.first,)
        return (self.first, self.second)


class EventLog(Sequence[SortingEvent]):
    """An immutable sequence of events stored as three parallel columns.

    ``types`` holds one byte per event; ``firsts`` and ``seconds`` hold the raw
    ``u32`` fields. A write's value is kept as its unsigned bit pattern and
    read back as a signed i32.
    """

    def __init__(self, types: bytes, firsts: array[int], seconds: array[int]) -> None:
        if not len(types) == len(firsts) == len(seconds):
            raise ValueError("The columns of an event log must have the same length")
        self._types = types
        self._firsts = firsts
        self._seconds = seconds

    @classmethod
    def from_events(cls, events: Iterable[SortingEvent]) -> EventLog:
        """Build a log from event objects."""
        listed = list(events)
        return cls(
            bytes(event.event_type for event in listed),
            array("I", (event.first for event in listed)),
            array("I", (event.second % _U32_RANGE for event in listed)),
        )

    @classmethod
    def from_records(cls, records: bytes) -> EventLog:
        """Build a log from the bytes of consecutive 9-byte records (``u8, u32, u32``).

        The length of ``records`` must be a multiple of 9.
        """
        if len(records) % EVENT_RECORD_BYTES:
            raise ValueError(f"{len(records)} bytes are not a whole number of event records")
        count = len(records) // EVENT_RECORD_BYTES
        return cls(
            records[0::EVENT_RECORD_BYTES],
            _column(records, 1, count),
            _column(records, 5, count),
        )

    def __len__(self) -> int:
        return len(self._types)

    @overload
    def __getitem__(self, position: int) -> SortingEvent: ...

    @overload
    def __getitem__(self, position: slice) -> EventLog: ...

    def __getitem__(self, position: int | slice) -> SortingEvent | EventLog:
        if isinstance(position, slice):
            return EventLog(self._types[position], self._firsts[position], self._seconds[position])
        event_type = EventType(self._types[position])
        second = self._seconds[position]
        if event_type is EventType.WRITE:
            second = _signed(second)
        return SortingEvent(event_type, self._firsts[position], second)

    def __iter__(self) -> Iterator[SortingEvent]:
        return (self[position] for position in range(len(self)))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EventLog):
            return (
                self._types == other._types
                and self._firsts == other._firsts
                and self._seconds == other._seconds
            )
        return NotImplemented

    def __repr__(self) -> str:
        return f"EventLog({len(self)} events)"

    def count_of(self, event_type: EventType, *, before: int | None = None) -> int:
        """Count the events of one type among the first ``before`` events (default: all)."""
        end = len(self) if before is None else before
        return self._types.count(bytes([event_type]), 0, end)

    def apply_to(self, values: list[int], start: int = 0, stop: int | None = None) -> None:
        """Perform events ``start`` up to ``stop`` on ``values`` in place; compares do nothing."""
        end = len(self) if stop is None else stop
        for position in range(start, end):
            event_type = self._types[position]
            if event_type == EventType.SWAP:
                first, second = self._firsts[position], self._seconds[position]
                values[first], values[second] = values[second], values[first]
            elif event_type == EventType.WRITE:
                values[self._firsts[position]] = _signed(self._seconds[position])

    def check(self, length: int) -> str | None:
        """Describe the first event that is invalid for an array of ``length``, or return ``None``.

        An event is invalid when its type is unknown or when an index it
        names is not below ``length``.
        """
        if self._all_valid(length):
            return None
        return next(
            (
                message
                for position in range(len(self))
                if (message := self._problem_with(position, length))
            ),
            None,
        )

    def _all_valid(self, length: int) -> bool:
        if self._types and max(self._types) > LARGEST_EVENT_TYPE:
            return False
        if self._firsts and max(self._firsts) >= length:
            return False
        second_indices = compress(self._seconds, map(EventType.WRITE.__ne__, self._types))
        return max(second_indices, default=-1) < length

    def _problem_with(self, position: int, length: int) -> str | None:
        event_type = self._types[position]
        first, second = self._firsts[position], self._seconds[position]
        if event_type > LARGEST_EVENT_TYPE:
            return f"event {position} has the unknown type {event_type}"
        if first >= length:
            return f"event {position} names index {first}, but the array has {length} elements"
        if event_type != EventType.WRITE and second >= length:
            return f"event {position} names index {second}, but the array has {length} elements"
        return None


def _column(records: bytes, offset: int, count: int) -> array[int]:
    """Collect the little-endian ``u32`` that starts ``offset`` bytes into every record."""
    gathered = bytearray(4 * count)
    for byte in range(4):
        gathered[byte::4] = records[offset + byte :: EVENT_RECORD_BYTES]
    column = array("I")
    column.frombytes(bytes(gathered))
    if sys.byteorder == "big":
        column.byteswap()
    return column


def _signed(value: int) -> int:
    return value - _U32_RANGE if value >= _I32_LIMIT else value
