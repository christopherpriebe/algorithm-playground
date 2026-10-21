"""Tests for the generic replay of events to the state after each of them."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from algorithm_playground.core.replay import StateTimeline


def add_all(total: int, events: Sequence[int]) -> int:
    return total + sum(events)


def append_all(history: tuple[str, ...], events: Sequence[str]) -> tuple[str, ...]:
    return (*history, *events)


class TestStateTimeline:
    def test_the_final_state_is_every_event_applied(self) -> None:
        assert StateTimeline(100, [1, 2, 3], add_all).final_state == 106

    def test_the_state_after_any_number_of_events_is_recovered(self) -> None:
        events = list(range(1, 11))
        timeline = StateTimeline(0, events, add_all, checkpoint_interval=3)
        assert [timeline.state_after(count) for count in range(11)] == [
            sum(events[:count]) for count in range(11)
        ]

    def test_a_state_that_is_not_a_number_works_too(self) -> None:
        events = list("abcdefg")
        timeline = StateTimeline((), events, append_all, checkpoint_interval=2)
        assert timeline.state_after(5) == tuple("abcde")
        assert timeline.final_state == tuple("abcdefg")

    def test_no_events_leave_the_start_state(self) -> None:
        timeline = StateTimeline("start", [], lambda state, events: state + "!")
        assert timeline.final_state == "start"
        assert timeline.state_after(0) == "start"

    def test_a_lookup_replays_fewer_events_than_the_interval(self) -> None:
        batches: list[int] = []

        def counting(total: int, events: Sequence[int]) -> int:
            batches.append(len(events))
            return total + sum(events)

        timeline = StateTimeline(0, list(range(100)), counting, checkpoint_interval=10)
        batches.clear()
        timeline.state_after(57)
        assert batches == [7]
        batches.clear()
        timeline.state_after(60)
        assert batches == []

    def test_building_it_replays_every_event_once(self) -> None:
        seen: list[int] = []

        def recording(total: int, events: Sequence[int]) -> int:
            seen.extend(events)
            return total + sum(events)

        StateTimeline(0, list(range(25)), recording, checkpoint_interval=10)
        assert seen == list(range(25))

    def test_a_state_that_the_function_leaves_alone_survives_lookups(self) -> None:
        timeline = StateTimeline(
            (0,),
            [1, 2, 3, 4],
            lambda state, events: (state[0] + sum(events),),
            checkpoint_interval=2,
        )
        assert timeline.state_after(3) == (6,)
        assert timeline.state_after(1) == (1,)
        assert timeline.state_after(3) == (6,)

    @pytest.mark.parametrize("count", [-1, 4])
    def test_asking_for_more_events_than_exist_or_fewer_than_none_raises(self, count: int) -> None:
        with pytest.raises(IndexError, match="were not recorded: 3 were"):
            StateTimeline(0, [1, 2, 3], add_all).state_after(count)

    def test_the_interval_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            StateTimeline(0, [1], add_all, checkpoint_interval=0)
