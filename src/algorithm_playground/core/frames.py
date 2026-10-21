"""Frames: the views a problem hands to the debug stepper.

A problem does not print and does not run a stepper. It returns
:class:`Frame` objects, one per step of a trace, and the stepper in
:mod:`algorithm_playground.visualization` owns playback (keys, auto-advance,
redrawing). A frame is text, so a problem builds one with any charting
library, and so a test can compare frames without a terminal.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import overload


@dataclass(frozen=True)
class Frame:
    """One step of a trace, ready to display.

    ``body`` is the picture as text, which may contain terminal color codes.
    ``caption`` is a short description of the step, for example the operation
    that led to it, and may span several lines. ``highlighted_indices`` names
    the positions the body draws emphasized, so that a test or another tool
    need not parse the body to know what the frame points at.
    """

    body: str
    caption: str = ""
    highlighted_indices: tuple[int, ...] = ()


class FrameSequence(Sequence[Frame]):
    """A sequence of frames that builds each one when it is first asked for.

    A trace with a million events has a million frames, far too many to draw
    up front; the stepper only ever needs the current one. ``build`` receives
    the position of the frame and must be a pure function of it.
    """

    def __init__(self, length: int, build: Callable[[int], Frame]) -> None:
        if length < 0:
            raise ValueError(f"The number of frames must be non-negative, got {length}")
        self._length = length
        self._build = build

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, position: int) -> Frame: ...

    @overload
    def __getitem__(self, position: slice) -> tuple[Frame, ...]: ...

    def __getitem__(self, position: int | slice) -> Frame | tuple[Frame, ...]:
        if isinstance(position, slice):
            return tuple(self[index] for index in range(*position.indices(self._length)))
        index = position + self._length if position < 0 else position
        if not 0 <= index < self._length:
            raise IndexError(f"Frame {position} is out of range for {self._length} frames")
        return self._build(index)

    def __iter__(self) -> Iterator[Frame]:
        return (self._build(index) for index in range(self._length))
