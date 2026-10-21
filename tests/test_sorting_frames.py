"""Tests for the frames a sorting trace and an input and output are shown as."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, ClassVar

import pytest
from instrumented_sort import COMPARE, SWAP, WRITE, insertion_sort, merge_sort

from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.problems.sorting import (
    EventLog,
    SortingEvent,
    SortingProblem,
    SortingTrace,
)
from algorithm_playground.problems.sorting import frames as frames_module
from algorithm_playground.problems.sorting.events import EVENT_RECORD_BYTES, EventType
from algorithm_playground.problems.sorting.frames import (
    sorting_input_output_frame,
    sorting_trace_frames,
)


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def event_frames(
    events: list[tuple[int, int, int]],
    input_values: tuple[int, ...],
    snapshots: tuple[tuple[int, ...], ...] = (),
) -> Sequence[Frame]:
    log = EventLog.from_events(
        [SortingEvent(EventType(kind), first, second) for kind, first, second in events]
    )
    return sorting_trace_frames(input_values, SortingTrace(snapshots, log))


@pytest.fixture
def drawn_heights(monkeypatch: pytest.MonkeyPatch) -> list[list[float]]:
    """Record the bar heights of every chart the frames draw (the chart itself is still drawn)."""
    heights: list[list[float]] = []
    real_render = frames_module.render_bar_chart

    def spy(values: Sequence[float], **keywords: Any) -> str:
        heights.append(list(values))
        return real_render(values, **keywords)

    monkeypatch.setattr(frames_module, "render_bar_chart", spy)
    return heights


class TestSnapshotFrames:
    trace: ClassVar[SortingTrace] = SortingTrace(((3, 1, 2), (1, 3, 2), (1, 3, 2), (1, 2, 3)))

    def test_there_is_one_frame_per_snapshot(self) -> None:
        frames = sorting_trace_frames((), self.trace)
        assert len(frames) == 4
        assert "snapshot 2 / 4" in plain(frames[1].body)

    def test_positions_that_changed_since_the_previous_snapshot_are_highlighted(self) -> None:
        frames = sorting_trace_frames((), self.trace)
        assert [frame.highlighted_indices for frame in frames] == [(), (0, 1), (), (1, 2)]
        assert "changed" in plain(frames[1].body)
        assert "changed" not in plain(frames[0].body)

    def test_captions_say_what_changed(self) -> None:
        frames = sorting_trace_frames((), self.trace)
        assert frames[0].caption == "first snapshot"
        assert frames[1].caption == (
            "changed since the previous snapshot: indices 0, 1\nvalues now: [0] = 1, [1] = 3"
        )
        assert frames[2].caption == "no position changed since the previous snapshot"

    def test_snapshots_of_different_lengths_are_not_compared(self) -> None:
        frames = sorting_trace_frames((), SortingTrace(((1, 2), (1,))))
        assert frames[1].highlighted_indices == ()

    def test_a_long_list_of_changes_is_cut_short(self) -> None:
        trace = SortingTrace((tuple(range(40)), tuple(range(40, 0, -1))))
        caption = sorting_trace_frames((), trace)[1].caption
        assert "indices 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ..." in caption
        assert caption.endswith("[0] = 40, [1] = 39, [2] = 38, [3] = 37, ...")

    def test_bars_show_ranks_so_that_huge_values_stay_readable(
        self, drawn_heights: list[list[float]]
    ) -> None:
        trace = SortingTrace(
            ((2_000_000_000, -2_000_000_000, 7), (-2_000_000_000, 7, 2_000_000_000))
        )
        frames = sorting_trace_frames((), trace)
        frames[0], frames[1]
        assert drawn_heights == [[3, 1, 2], [1, 2, 3]]
        assert "values now: [0] = -2000000000" in frames[1].caption

    def test_equal_values_share_a_height_and_a_new_value_takes_the_next_larger_rank(
        self, drawn_heights: list[list[float]]
    ) -> None:
        trace = SortingTrace(((5, 5, 9), (5, 7, 9)))
        sorting_trace_frames((), trace)[1]
        assert drawn_heights == [[1, 2, 2]]


class TestEventFrames:
    events: ClassVar[list[tuple[int, int, int]]] = [
        (COMPARE, 0, 1),
        (SWAP, 0, 1),
        (COMPARE, 1, 2),
        (WRITE, 2, 9),
    ]

    def test_there_is_a_start_frame_and_one_frame_per_event(self) -> None:
        frames = event_frames(self.events, (2, 1, 3))
        assert isinstance(frames, FrameSequence)
        assert len(frames) == 5
        assert frames[0].caption.startswith("start: 4 events follow")
        assert frames[0].highlighted_indices == ()

    def test_each_frame_highlights_the_indices_of_its_event(self) -> None:
        frames = event_frames(self.events, (2, 1, 3))
        assert [frame.highlighted_indices for frame in frames] == [(), (0, 1), (0, 1), (1, 2), (2,)]

    def test_the_legend_names_what_the_highlight_means(self) -> None:
        frames = event_frames(self.events, (2, 1, 3))
        assert [
            label in plain(frames[position].body)
            for position, label in ((1, "compared"), (2, "swapped"), (4, "written"))
        ] == [True, True, True]

    def test_the_caption_names_the_event_and_the_operations_so_far(self) -> None:
        frames = event_frames(self.events, (2, 1, 3))
        assert frames[2].caption == (
            "event 2 / 4: swap(0, 1)\n"
            "values now: [0] = 1, [1] = 2\n"
            "so far: 1 compares, 1 swaps, 0 writes"
        )
        assert frames[4].caption.splitlines()[-1] == "so far: 2 compares, 1 swaps, 1 writes"

    def test_events_without_snapshots_start_from_the_input(self) -> None:
        frames = event_frames([(SWAP, 0, 1)], (2, 1))
        assert "2 values" in plain(frames[0].body)

    def test_events_win_over_snapshots_when_both_are_present(self) -> None:
        assert len(event_frames([(SWAP, 0, 1)], (2, 1), snapshots=((2, 1), (1, 2)))) == 2

    def test_a_trace_with_no_events_has_only_the_start_frame(self) -> None:
        assert len(event_frames([], (3, 2))) == 1

    def test_the_final_frame_of_an_instrumented_sort_has_the_totals_of_the_run(self) -> None:
        values = [5, 2, 8, 1, 9, 3]
        for algorithm in (insertion_sort, merge_sort):
            recording = algorithm(values)
            frames = event_frames(recording.events, tuple(values))
            compares = sum(event[0] == COMPARE for event in recording.events)
            assert f"so far: {compares} compares" in frames[len(frames) - 1].caption

    def test_a_trace_of_a_million_events_is_framed_without_drawing_any(
        self, drawn_heights: list[list[float]]
    ) -> None:
        compare_record = bytes([COMPARE]) + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
        assert len(compare_record) == EVENT_RECORD_BYTES
        log = EventLog.from_records(compare_record * 1_000_000)
        frames = sorting_trace_frames((2, 1), SortingTrace((), log))
        assert len(frames) == 1_000_001
        assert drawn_heights == []
        frames[500_000]
        assert len(drawn_heights) == 1

    def test_the_caption_names_the_values_a_write_stored(
        self, drawn_heights: list[list[float]]
    ) -> None:
        frames = event_frames([(WRITE, 0, -(2**31))], (5, 6))
        assert "values now: [0] = -2147483648" in frames[1].caption
        assert drawn_heights[-1] == [1, 2]


class TestInputAndOutputFrame:
    def test_shows_both_arrays(self) -> None:
        frame = SortingProblem().input_output_frame([3, 1, 2], [1, 2, 3])
        assert isinstance(frame, Frame)
        assert "input" in plain(frame.body)
        assert "output (sorted)" in plain(frame.body)

    def test_both_arrays_are_drawn_with_the_ranks_of_the_input_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[tuple[Sequence[float], Sequence[float]]] = []
        real: Callable[..., str] = frames_module.render_side_by_side_bar_charts

        def spy(left: Sequence[float], right: Sequence[float], **keywords: Any) -> str:
            captured.append((list(left), list(right)))
            return real(left, right, **keywords)

        monkeypatch.setattr(frames_module, "render_side_by_side_bar_charts", spy)
        sorting_input_output_frame([900, -4, 17], [-4, 17, 900])
        assert captured == [([3, 1, 2], [1, 2, 3])]

    def test_an_empty_input_has_nothing_to_draw(self) -> None:
        assert sorting_input_output_frame([], []).body == "(empty input)"
