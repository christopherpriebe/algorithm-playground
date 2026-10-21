"""Tests for frames and the lazily built frame sequence."""

import pytest

from algorithm_playground.core import Frame, FrameSequence


def build_numbered_frame(position: int) -> Frame:
    """Build the frame whose body, caption and highlight are derived from its position."""
    return Frame(f"body {position}", f"caption {position}", (position,))


class TestFrame:
    def test_a_frame_needs_only_a_body(self) -> None:
        """Test a frame built from a body alone has no caption and no highlighted indices."""
        frame = Frame("picture")

        assert frame.caption == ""
        assert frame.highlighted_indices == ()


class TestFrameSequence:
    def test_has_the_given_length_and_builds_frames_by_position(self) -> None:
        """Test the sequence reports its length and builds the frame at a position, from the end too."""
        frames = FrameSequence(4, build_numbered_frame)

        assert len(frames) == 4
        assert frames[2] == Frame("body 2", "caption 2", (2,))
        assert frames[-1] == build_numbered_frame(3)

    def test_builds_a_frame_only_when_it_is_asked_for(self) -> None:
        """Test a frame is built on access, so a huge sequence costs nothing until it is read."""
        built: list[int] = []

        def build_and_record_frame(position: int) -> Frame:
            built.append(position)
            return build_numbered_frame(position)

        frames = FrameSequence(1_000_000, build_and_record_frame)

        frames[5]
        frames[999_999]

        assert built == [5, 999_999]

    def test_slices_give_frames_in_order(self) -> None:
        """Test a slice of the sequence holds the frames at those positions in order."""
        frames = FrameSequence(5, build_numbered_frame)

        assert [frame.body for frame in frames[1:4]] == ["body 1", "body 2", "body 3"]

    def test_iteration_gives_frames_in_order(self) -> None:
        """Test iterating the sequence yields every frame in order."""
        frames = FrameSequence(5, build_numbered_frame)

        assert [frame.body for frame in frames] == [f"body {number}" for number in range(5)]

    @pytest.mark.parametrize("position", [3, -4], ids=["past-the-end", "before-the-start"])
    def test_a_position_outside_the_sequence_is_an_error(self, position: int) -> None:
        """Test reading a position outside the sequence raises an index error."""
        frames = FrameSequence(3, build_numbered_frame)

        with pytest.raises(IndexError, match="out of range for 3 frames"):
            frames[position]

    def test_a_negative_length_is_rejected(self) -> None:
        """Test a sequence cannot have a negative length."""
        with pytest.raises(ValueError, match="non-negative"):
            FrameSequence(-1, build_numbered_frame)

    def test_an_empty_sequence_is_falsy(self) -> None:
        """Test a sequence without frames counts as false."""
        assert not FrameSequence(0, build_numbered_frame)
