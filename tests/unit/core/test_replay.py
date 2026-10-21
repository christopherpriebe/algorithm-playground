"""Tests for the generic replay of events to the state after each of them."""

from collections.abc import Sequence

import pytest

from algorithm_playground.core.replay import StateTimeline


def add_all(total: int, events: Sequence[int]) -> int:
    """Apply events to a running total by adding them."""
    return total + sum(events)


def append_all(history: tuple[str, ...], events: Sequence[str]) -> tuple[str, ...]:
    """Apply events to a history by appending them."""
    return (*history, *events)


class TestStateTimeline:
    def test_the_final_state_is_every_event_applied(self) -> None:
        """Test the final state is the start state with every event applied."""
        timeline = StateTimeline(100, [1, 2, 3], add_all)

        assert timeline.final_state == 106

    def test_the_state_after_any_number_of_events_is_recovered(self) -> None:
        """Test the state after any prefix of the events equals applying just that prefix."""
        events = list(range(1, 11))
        timeline = StateTimeline(0, events, add_all, checkpoint_interval=3)

        states = [timeline.state_after(count) for count in range(11)]

        assert states == [sum(events[:count]) for count in range(11)]

    def test_a_state_that_is_not_a_number_works_too(self) -> None:
        """Test states of any type are supported, not only numbers."""
        events = list("abcdefg")
        timeline = StateTimeline((), events, append_all, checkpoint_interval=2)

        assert timeline.state_after(5) == tuple("abcde")
        assert timeline.final_state == tuple("abcdefg")

    def test_no_events_leave_the_start_state(self) -> None:
        """Test a timeline without events stays in its start state."""
        timeline = StateTimeline("start", [], lambda state, events: state + "!")

        assert timeline.final_state == "start"
        assert timeline.state_after(0) == "start"

    def test_a_lookup_replays_fewer_events_than_the_interval(self) -> None:
        """Test a lookup replays only the events after the nearest checkpoint."""
        batches: list[int] = []

        def add_and_record_batch(total: int, events: Sequence[int]) -> int:
            batches.append(len(events))
            return total + sum(events)

        timeline = StateTimeline(0, list(range(100)), add_and_record_batch, checkpoint_interval=10)
        batches.clear()

        timeline.state_after(57)
        replayed_after_57 = list(batches)
        batches.clear()
        timeline.state_after(60)

        assert replayed_after_57 == [7]
        assert batches == []

    def test_building_it_replays_every_event_once(self) -> None:
        """Test constructing a timeline applies each event exactly once, in order."""
        seen: list[int] = []

        def add_and_record_events(total: int, events: Sequence[int]) -> int:
            seen.extend(events)
            return total + sum(events)

        StateTimeline(0, list(range(25)), add_and_record_events, checkpoint_interval=10)

        assert seen == list(range(25))

    def test_a_state_that_the_function_leaves_alone_survives_lookups(self) -> None:
        """Test repeated lookups return the same states, so earlier lookups corrupt nothing."""
        timeline = StateTimeline(
            (0,),
            [1, 2, 3, 4],
            lambda state, events: (state[0] + sum(events),),
            checkpoint_interval=2,
        )

        states = [timeline.state_after(3), timeline.state_after(1), timeline.state_after(3)]

        assert states == [(6,), (1,), (6,)]

    @pytest.mark.parametrize("count", [-1, 4], ids=["negative", "more-than-recorded"])
    def test_asking_for_more_events_than_exist_or_fewer_than_none_raises(self, count: int) -> None:
        """Test a lookup outside zero to the number of events raises an index error."""
        timeline = StateTimeline(0, [1, 2, 3], add_all)

        with pytest.raises(IndexError, match="were not recorded: 3 were"):
            timeline.state_after(count)

    def test_the_interval_must_be_positive(self) -> None:
        """Test a checkpoint interval below one is rejected."""
        with pytest.raises(ValueError, match="at least 1"):
            StateTimeline(0, [1], add_all, checkpoint_interval=0)
