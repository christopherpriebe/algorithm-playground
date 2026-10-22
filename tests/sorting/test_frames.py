"""Tests for the frames a sorting trace and an input and output are shown as."""

import re
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from algorithm_playground import visualization
from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.problems.sorting import (
    EVENT_RECORD_BYTES,
    EventLog,
    EventType,
    SortingEvent,
    SortingProblem,
    SortingTrace,
    draw_sorting_input_output_frame,
    draw_sorting_trace_frames,
)
from algorithm_playground.visualization import (
    render_bar_chart,
    render_side_by_side_bar_charts,
)
from helpers.instrumented_sort import (
    COMPARE,
    SWAP,
    WRITE,
    Recording,
    insertion_sort,
    merge_sort,
)


def strip_ansi_codes(text: str) -> str:
    """Remove the color escape sequences from some text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def build_event_frames(
    events: list[tuple[int, int, int]],
    input_values: tuple[int, ...],
    snapshots: tuple[tuple[int, ...], ...] = (),
) -> Sequence[Frame]:
    """Build the frames of a trace made of (type, first, second) events and snapshots."""
    log = EventLog.from_events(
        [SortingEvent(EventType(kind), first, second) for kind, first, second in events]
    )
    return draw_sorting_trace_frames(input_values, SortingTrace(snapshots, log))


@pytest.fixture
def drawn_heights(monkeypatch: pytest.MonkeyPatch) -> list[list[float]]:
    """Record the bar heights of every chart the frames draw (the chart itself is still drawn)."""
    heights: list[list[float]] = []

    def render_and_record(
        values: Sequence[float],
        **keywords: Any,  # noqa: ANN401  forwarded unchanged to the real renderer
    ) -> str:
        heights.append(list(values))
        return render_bar_chart(values, **keywords)

    monkeypatch.setattr(visualization, "render_bar_chart", render_and_record)
    return heights


SNAPSHOT_TRACE: SortingTrace = SortingTrace(
    ((3, 1, 2), (1, 3, 2), (1, 3, 2), (1, 2, 3))
)


def test_there_is_one_frame_per_snapshot() -> None:
    """Test a trace of snapshots yields one frame per snapshot."""
    frames = draw_sorting_trace_frames((), SNAPSHOT_TRACE)

    assert len(frames) == 4
    assert "snapshot 2 / 4" in strip_ansi_codes(frames[1].body)


def test_positions_that_changed_since_the_previous_snapshot_are_highlighted() -> None:
    """Test the positions that changed since the previous snapshot are highlighted."""
    frames = draw_sorting_trace_frames((), SNAPSHOT_TRACE)

    assert [frame.highlighted_indices for frame in frames] == [
        (),
        (0, 1),
        (),
        (1, 2),
    ]
    assert "changed" in strip_ansi_codes(frames[1].body)
    assert "changed" not in strip_ansi_codes(frames[0].body)


def test_captions_say_what_changed() -> None:
    """Test the caption of each snapshot frame says what changed."""
    frames = draw_sorting_trace_frames((), SNAPSHOT_TRACE)

    assert frames[0].caption == "first snapshot"
    assert frames[1].caption == (
        "changed since the previous snapshot: indices 0, 1\nvalues now: [0] = 1, [1] = 3"
    )
    assert frames[2].caption == "no position changed since the previous snapshot"


def test_snapshots_of_different_lengths_are_not_compared() -> None:
    """Test snapshots of different lengths highlight nothing."""
    frames = draw_sorting_trace_frames((), SortingTrace(((1, 2), (1,))))

    assert frames[1].highlighted_indices == ()


def test_a_long_list_of_changes_is_cut_short() -> None:
    """Test a caption listing many changes is cut short with an ellipsis."""
    trace = SortingTrace((tuple(range(40)), tuple(range(40, 0, -1))))

    caption = draw_sorting_trace_frames((), trace)[1].caption

    assert "indices 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ..." in caption
    assert caption.endswith("[0] = 40, [1] = 39, [2] = 38, [3] = 37, ...")


def test_bars_show_ranks_so_that_huge_values_stay_readable(
    drawn_heights: list[list[float]],
) -> None:
    """Test bars are drawn with the ranks of the values instead of the values."""
    trace = SortingTrace(
        ((2_000_000_000, -2_000_000_000, 7), (-2_000_000_000, 7, 2_000_000_000))
    )
    frames = draw_sorting_trace_frames((), trace)

    # Frames are drawn when they are first indexed.
    frames[0], frames[1]

    assert drawn_heights == [[3, 1, 2], [1, 2, 3]]


def test_the_caption_shows_the_actual_values_of_the_changed_positions() -> None:
    """Test the caption of a snapshot frame shows the values, not their ranks."""
    trace = SortingTrace(
        ((2_000_000_000, -2_000_000_000, 7), (-2_000_000_000, 7, 2_000_000_000))
    )

    frames = draw_sorting_trace_frames((), trace)

    assert "values now: [0] = -2000000000" in frames[1].caption


def test_equal_values_share_a_height_and_a_new_value_takes_the_next_larger_rank(
    drawn_heights: list[list[float]],
) -> None:
    """Test equal values share a height and the next distinct value ranks one higher."""
    trace = SortingTrace(((5, 5, 9), (5, 7, 9)))
    frames = draw_sorting_trace_frames((), trace)

    # Frames are drawn when they are first indexed.
    frames[1]

    assert drawn_heights == [[1, 2, 2]]


RECORDED_EVENTS: list[tuple[int, int, int]] = [
    (COMPARE, 0, 1),
    (SWAP, 0, 1),
    (COMPARE, 1, 2),
    (WRITE, 2, 9),
]


def test_there_is_a_start_frame_and_one_frame_per_event() -> None:
    """Test a trace of events yields a start frame followed by one frame per event."""
    frames = build_event_frames(RECORDED_EVENTS, (2, 1, 3))

    assert isinstance(frames, FrameSequence)
    assert len(frames) == 5


def test_the_start_frame_announces_the_events_and_highlights_nothing() -> None:
    """Test the start frame announces how many events follow and highlights no position."""
    frames = build_event_frames(RECORDED_EVENTS, (2, 1, 3))

    assert frames[0].caption.startswith("start: 4 events follow")
    assert frames[0].highlighted_indices == ()


def test_each_frame_highlights_the_indices_of_its_event() -> None:
    """Test each event frame highlights the indices its event names."""
    frames = build_event_frames(RECORDED_EVENTS, (2, 1, 3))

    assert [frame.highlighted_indices for frame in frames] == [
        (),
        (0, 1),
        (0, 1),
        (1, 2),
        (2,),
    ]


@pytest.mark.parametrize(
    ("position", "label"),
    [(1, "compared"), (2, "swapped"), (4, "written")],
    ids=["compare", "swap", "write"],
)
def test_the_legend_names_what_the_highlight_means(position: int, label: str) -> None:
    """Test the legend of an event frame names what its highlight means."""
    frames = build_event_frames(RECORDED_EVENTS, (2, 1, 3))

    assert label in strip_ansi_codes(frames[position].body)


def test_the_caption_names_the_event_and_the_operations_so_far() -> None:
    """Test the caption of an event frame names the event, the values and the totals so far."""
    frames = build_event_frames(RECORDED_EVENTS, (2, 1, 3))

    assert frames[2].caption == (
        "event 2 / 4: swap(0, 1)\n"
        "values now: [0] = 1, [1] = 2\n"
        "so far: 1 compares, 1 swaps, 0 writes"
    )


def test_the_operations_so_far_count_every_event_type() -> None:
    """Test the last line of the final caption counts every event type."""
    frames = build_event_frames(RECORDED_EVENTS, (2, 1, 3))

    assert frames[4].caption.splitlines()[-1] == "so far: 2 compares, 1 swaps, 1 writes"


def test_events_without_snapshots_start_from_the_input() -> None:
    """Test a trace without snapshots starts from the input values."""
    frames = build_event_frames([(SWAP, 0, 1)], (2, 1))

    assert "2 values" in strip_ansi_codes(frames[0].body)


def test_events_win_over_snapshots_when_both_are_present() -> None:
    """Test a trace with events and snapshots is framed by its events."""
    frames = build_event_frames([(SWAP, 0, 1)], (2, 1), snapshots=((2, 1), (1, 2)))

    assert len(frames) == 2


def test_a_trace_with_no_events_has_only_the_start_frame() -> None:
    """Test a trace without events yields only the start frame."""
    assert len(build_event_frames([], (3, 2))) == 1


@pytest.mark.parametrize("algorithm", [insertion_sort, merge_sort])
def test_the_final_frame_of_an_instrumented_sort_has_the_totals_of_the_run(
    algorithm: Callable[[list[int]], Recording],
) -> None:
    """Test the final frame of an instrumented sort reports the compares of the run."""
    values = [5, 2, 8, 1, 9, 3]
    recording = algorithm(values)
    compares = sum(event[0] == COMPARE for event in recording.events)

    frames = build_event_frames(recording.events, tuple(values))

    assert f"so far: {compares} compares" in frames[len(frames) - 1].caption


def test_a_trace_of_a_million_events_is_framed_without_drawing_any(
    drawn_heights: list[list[float]],
) -> None:
    """Test framing a trace of a million events draws a frame only when it is indexed."""
    compare_record = (
        bytes([COMPARE]) + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
    )
    assert len(compare_record) == EVENT_RECORD_BYTES
    log = EventLog.from_records(compare_record * 1_000_000)

    frames = draw_sorting_trace_frames((2, 1), SortingTrace((), log))

    assert len(frames) == 1_000_001
    assert drawn_heights == []
    # Frames are drawn when they are first indexed.
    frames[500_000]
    assert len(drawn_heights) == 1


def test_the_caption_names_the_values_a_write_stored() -> None:
    """Test the caption of a write frame shows the value that was stored."""
    frames = build_event_frames([(WRITE, 0, -(2**31))], (5, 6))

    assert "values now: [0] = -2147483648" in frames[1].caption


def test_the_bars_of_a_write_frame_show_ranks(drawn_heights: list[list[float]]) -> None:
    """Test the bars of a write frame are drawn with ranks."""
    frames = build_event_frames([(WRITE, 0, -(2**31))], (5, 6))

    # Frames are drawn when they are first indexed.
    frames[1]

    assert drawn_heights[-1] == [1, 2]


def test_shows_both_arrays() -> None:
    """Test the frame labels the input and the sorted output."""
    frame = SortingProblem().input_output_frame([3, 1, 2], [1, 2, 3])

    assert isinstance(frame, Frame)
    assert "input" in strip_ansi_codes(frame.body)
    assert "output (sorted)" in strip_ansi_codes(frame.body)


def test_both_arrays_are_drawn_with_the_ranks_of_the_input_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test both arrays are drawn with the ranks of the input values."""
    captured: list[tuple[Sequence[float], Sequence[float]]] = []

    def render_and_record(
        left: Sequence[float],
        right: Sequence[float],
        **keywords: Any,  # noqa: ANN401  forwarded unchanged to the real renderer
    ) -> str:
        captured.append((list(left), list(right)))
        return render_side_by_side_bar_charts(left, right, **keywords)

    monkeypatch.setattr(
        visualization, "render_side_by_side_bar_charts", render_and_record
    )

    draw_sorting_input_output_frame([900, -4, 17], [-4, 17, 900])

    assert captured == [([3, 1, 2], [1, 2, 3])]


def test_an_empty_input_has_nothing_to_draw() -> None:
    """Test an empty input is shown as such."""
    assert draw_sorting_input_output_frame([], []).body == "(empty input)"
