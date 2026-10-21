"""Tests for frames and the lazily built frame sequence."""

from __future__ import annotations

import pytest

from algorithm_playground.core import Frame, FrameSequence


def numbered(position: int) -> Frame:
    return Frame(f"body {position}", f"caption {position}", (position,))


class TestFrame:
    def test_a_frame_needs_only_a_body(self) -> None:
        frame = Frame("picture")
        assert frame.caption == ""
        assert frame.highlighted_indices == ()


class TestFrameSequence:
    def test_has_the_given_length_and_builds_frames_by_position(self) -> None:
        frames = FrameSequence(4, numbered)
        assert len(frames) == 4
        assert frames[2] == Frame("body 2", "caption 2", (2,))
        assert frames[-1] == numbered(3)

    def test_builds_a_frame_only_when_it_is_asked_for(self) -> None:
        built: list[int] = []

        def build(position: int) -> Frame:
            built.append(position)
            return numbered(position)

        frames = FrameSequence(1_000_000, build)
        frames[5]
        frames[999_999]
        assert built == [5, 999_999]

    def test_slices_and_iteration_give_frames_in_order(self) -> None:
        frames = FrameSequence(5, numbered)
        assert [frame.body for frame in frames[1:4]] == ["body 1", "body 2", "body 3"]
        assert [frame.body for frame in frames] == [f"body {number}" for number in range(5)]

    @pytest.mark.parametrize("position", [3, -4])
    def test_a_position_outside_the_sequence_is_an_error(self, position: int) -> None:
        with pytest.raises(IndexError, match="out of range for 3 frames"):
            FrameSequence(3, numbered)[position]

    def test_a_negative_length_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            FrameSequence(-1, numbered)

    def test_an_empty_sequence_is_falsy(self) -> None:
        assert not FrameSequence(0, numbered)
