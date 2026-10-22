"""Tests for frames, frame sequences, and replaying events into states."""

from collections.abc import Sequence

import pytest

from algorithm_playground.core import Frame, FrameSequence, StateTimeline


def build_numbered_frame(position: int) -> Frame:
    """Build the frame whose body, caption and highlight are derived from its position."""
    return Frame(
        f"body {position}",
        caption=f"caption {position}",
        highlighted_indices=(position,),
    )


def add_all(total: int, events: Sequence[int]) -> int:
    """Apply events to a running total by adding them."""
    return total + sum(events)


def append_all(history: tuple[str, ...], events: Sequence[str]) -> tuple[str, ...]:
    """Apply events to a history by appending them."""
    return (*history, *events)


def test_a_frame_needs_only_a_body() -> None:
    """Test a frame built from a body alone has no caption and no highlighted indices."""
    frame = Frame("picture")

    assert frame.caption == ""
    assert frame.highlighted_indices == ()


def test_has_the_given_length_and_builds_frames_by_position() -> None:
    """Test the sequence reports its length and builds the frame at a position, from the end too."""
    frames = FrameSequence(4, build_numbered_frame)

    assert len(frames) == 4
    assert frames[2] == Frame("body 2", caption="caption 2", highlighted_indices=(2,))
    assert frames[-1] == build_numbered_frame(3)


def test_builds_a_frame_only_when_it_is_asked_for() -> None:
    """Test a frame is built on access, so a huge sequence costs nothing until it is read."""
    built: list[int] = []

    def build_and_record_frame(position: int) -> Frame:
        built.append(position)
        return build_numbered_frame(position)

    frames = FrameSequence(1_000_000, build_and_record_frame)

    frames[5]
    frames[999_999]

    assert built == [5, 999_999]


def test_slices_give_frames_in_order() -> None:
    """Test a slice of the sequence holds the frames at those positions in order."""
    frames = FrameSequence(5, build_numbered_frame)

    assert [frame.body for frame in frames[1:4]] == ["body 1", "body 2", "body 3"]


def test_iteration_gives_frames_in_order() -> None:
    """Test iterating the sequence yields every frame in order."""
    frames = FrameSequence(5, build_numbered_frame)

    assert [frame.body for frame in frames] == [f"body {number}" for number in range(5)]


@pytest.mark.parametrize("position", [3, -4], ids=["past-the-end", "before-the-start"])
def test_a_position_outside_the_sequence_is_an_error(position: int) -> None:
    """Test reading a position outside the sequence raises an index error."""
    frames = FrameSequence(3, build_numbered_frame)

    with pytest.raises(IndexError, match="out of range for 3 frames"):
        frames[position]


def test_a_negative_length_is_rejected() -> None:
    """Test a sequence cannot have a negative length."""
    with pytest.raises(ValueError, match="non-negative"):
        FrameSequence(-1, build_numbered_frame)


def test_an_empty_sequence_is_falsy() -> None:
    """Test a sequence without frames counts as false."""
    assert not FrameSequence(0, build_numbered_frame)


def test_the_final_state_is_every_event_applied() -> None:
    """Test the final state is the start state with every event applied."""
    timeline = StateTimeline(100, [1, 2, 3], add_all)

    assert timeline.final_state == 106


def test_the_state_after_any_number_of_events_is_recovered() -> None:
    """Test the state after any prefix of the events equals applying just that prefix."""
    events = list(range(1, 11))
    timeline = StateTimeline(0, events, add_all, checkpoint_interval=3)

    states = [timeline.state_after(count) for count in range(11)]

    assert states == [sum(events[:count]) for count in range(11)]


def test_a_state_that_is_not_a_number_works_too() -> None:
    """Test states of any type are supported, not only numbers."""
    events = list("abcdefg")
    timeline = StateTimeline((), events, append_all, checkpoint_interval=2)

    assert timeline.state_after(5) == tuple("abcde")
    assert timeline.final_state == tuple("abcdefg")


def test_no_events_leave_the_start_state() -> None:
    """Test a timeline without events stays in its start state."""
    timeline = StateTimeline("start", [], lambda state, _: state + "!")

    assert timeline.final_state == "start"
    assert timeline.state_after(0) == "start"


def test_a_lookup_replays_fewer_events_than_the_interval() -> None:
    """Test a lookup replays only the events after the nearest checkpoint."""
    batches: list[int] = []

    def add_and_record_batch(total: int, events: Sequence[int]) -> int:
        batches.append(len(events))
        return total + sum(events)

    timeline = StateTimeline(
        0, list(range(100)), add_and_record_batch, checkpoint_interval=10
    )
    batches.clear()

    timeline.state_after(57)
    replayed_after_57 = list(batches)
    batches.clear()
    timeline.state_after(60)

    assert replayed_after_57 == [7]
    assert batches == []


def test_building_it_replays_every_event_once() -> None:
    """Test constructing a timeline applies each event exactly once, in order."""
    seen: list[int] = []

    def add_and_record_events(total: int, events: Sequence[int]) -> int:
        seen.extend(events)
        return total + sum(events)

    StateTimeline(0, list(range(25)), add_and_record_events, checkpoint_interval=10)

    assert seen == list(range(25))


def test_a_state_that_the_function_leaves_alone_survives_lookups() -> None:
    """Test repeated lookups return the same states, so earlier lookups corrupt nothing."""
    timeline = StateTimeline(
        (0,),
        [1, 2, 3, 4],
        lambda state, events: (state[0] + sum(events),),
        checkpoint_interval=2,
    )

    states = [
        timeline.state_after(3),
        timeline.state_after(1),
        timeline.state_after(3),
    ]

    assert states == [(6,), (1,), (6,)]


@pytest.mark.parametrize("count", [-1, 4], ids=["negative", "more-than-recorded"])
def test_asking_for_more_events_than_exist_or_fewer_than_none_raises(
    count: int,
) -> None:
    """Test a lookup outside zero to the number of events raises an index error."""
    timeline = StateTimeline(0, [1, 2, 3], add_all)

    with pytest.raises(IndexError, match="were not recorded: 3 were"):
        timeline.state_after(count)


def test_the_interval_must_be_positive() -> None:
    """Test a checkpoint interval below one is rejected."""
    with pytest.raises(ValueError, match="at least 1"):
        StateTimeline(0, [1], add_all, checkpoint_interval=0)
