"""Tests for replaying the events of a sorting trace."""

import random
from collections.abc import Callable
from pathlib import Path

import pytest
from helpers.instrumented_sort import (
    SWAP,
    Recording,
    encode_trace,
    insertion_sort,
    merge_sort,
)
from helpers.sorting_traces import decode_trace

from algorithm_playground.problems.sorting import (
    EventLog,
    EventType,
    SortingEvent,
    SortingProblem,
    SortingTrace,
)
from algorithm_playground.problems.sorting.replay import replay_warnings, sorting_timeline


def build_sorting_events(recording: Recording) -> list[SortingEvent]:
    """Build the event objects of a recording."""
    return [
        SortingEvent(EventType(kind), first, second) for kind, first, second in recording.events
    ]


class TestReplay:
    @pytest.mark.parametrize("algorithm", [insertion_sort, merge_sort])
    def test_replaying_the_events_sorts_the_input(
        self, algorithm: Callable[[list[int]], Recording]
    ) -> None:
        """Test replaying the events of an instrumented sort ends in the sorted input."""
        values = random.Random(2).sample(range(-500, 500), 40)
        recording = algorithm(values)

        timeline = sorting_timeline(values, EventLog.from_events(build_sorting_events(recording)))

        assert timeline.final_state == tuple(sorted(values))

    def test_every_prefix_is_recovered_across_checkpoints(self) -> None:
        """Test the state after any number of events equals applying that many events."""
        values = random.Random(9).sample(range(100), 30)
        recording = insertion_sort(values)
        log = EventLog.from_events(build_sorting_events(recording))
        assert len(log) > 2 * 256

        timeline = sorting_timeline(values, log)

        for count in (0, 1, 255, 256, 257, 512, len(log) // 2, len(log)):
            expected = list(values)
            log.apply_to(expected, 0, count)
            assert timeline.state_after(count) == tuple(expected)

    def test_asking_for_more_events_than_exist_raises(self) -> None:
        """Test asking for the state after more events than exist raises IndexError."""
        timeline = sorting_timeline([1], EventLog.from_events([]))

        with pytest.raises(IndexError, match="events were not recorded"):
            timeline.state_after(1)


class TestReplayWarnings:
    def test_consistent_events_and_snapshots_give_no_warning(self, tmp_path: Path) -> None:
        """Test events that agree with the snapshots produce no warning."""
        values = [3, 1, 2]
        recording = insertion_sort(values)
        trace = decode_trace(tmp_path, encode_trace(recording.snapshots, recording.events), values)

        assert replay_warnings(trace, values) == []

    def test_the_problem_reports_no_trace_warning_for_a_consistent_trace(
        self, tmp_path: Path
    ) -> None:
        """Test the sorting problem reports no trace warning for a consistent trace."""
        values = [3, 1, 2]
        recording = insertion_sort(values)
        trace = decode_trace(tmp_path, encode_trace(recording.snapshots, recording.events), values)

        warnings = SortingProblem().trace_warnings(values, sorted(values), trace)

        assert warnings == []

    def test_a_disagreement_with_the_final_snapshot_is_a_warning_with_the_first_difference(
        self, tmp_path: Path
    ) -> None:
        """Test a replay that disagrees with the final snapshot warns with the first difference."""
        raw = encode_trace(snapshots=[[3, 1, 2], [1, 2, 3]], events=[(SWAP, 0, 1)])
        trace = decode_trace(tmp_path, raw, input_values=[3, 1, 2])

        warnings = replay_warnings(trace, [3, 1, 2])

        assert len(warnings) == 1
        assert "first difference at index 1 (replayed 3, snapshot 2)" in warnings[0]
        assert "1 events" in warnings[0]

    def test_snapshots_of_different_lengths_are_reported_as_such(self, tmp_path: Path) -> None:
        """Test a final snapshot of another length than the replayed array is reported."""
        raw = encode_trace(snapshots=[[2, 1], [1]], events=[(SWAP, 0, 1)])
        trace = decode_trace(tmp_path, raw, input_values=[2, 1])

        warnings = replay_warnings(trace, [2, 1])

        assert "the replayed array has 2 values, the snapshot 1" in warnings[0]

    def test_a_first_snapshot_of_another_length_than_the_input_is_a_warning(
        self, tmp_path: Path
    ) -> None:
        """Test a first snapshot of another length than the input produces a warning."""
        trace = decode_trace(tmp_path, encode_trace(snapshots=[[1, 2, 3]]), input_values=[9])

        warnings = replay_warnings(trace, [9])

        assert warnings == [
            "The first snapshot has 3 values, but the input has 1. "
            "A snapshot should show the whole array."
        ]

    def test_a_matching_input_and_snapshot_do_not_disagree(self) -> None:
        """Test a first snapshot that matches the input length produces no warning."""
        assert replay_warnings(SortingTrace(((1, 2, 3),)), [3, 2, 1]) == []

    @pytest.mark.parametrize(
        "content",
        [
            encode_trace(snapshots=[[2, 1], [1, 2]]),
            encode_trace(snapshots=[[2, 1]], events=[(SWAP, 0, 1)]),
            encode_trace(events=[(SWAP, 0, 1)]),
        ],
        ids=["no events", "a single snapshot", "no snapshots"],
    )
    def test_there_is_nothing_to_compare_without_events_and_a_first_and_last_snapshot(
        self, tmp_path: Path, content: bytes
    ) -> None:
        """Test a trace without events or without two snapshots produces no warning."""
        trace = decode_trace(tmp_path, content, input_values=[2, 1])

        assert replay_warnings(trace, [2, 1]) == []
