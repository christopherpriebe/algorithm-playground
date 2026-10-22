"""Sorting problem package: sort an array of i32 values in ascending order."""

from algorithm_playground.problems.sorting._codec import (
    I32_MAX,
    I32_MIN,
    read_values,
    write_values,
)
from algorithm_playground.problems.sorting._events import (
    EVENT_RECORD_BYTES,
    EventLog,
    EventType,
    SortingEvent,
)
from algorithm_playground.problems.sorting._fixtures import (
    build_sorting_fixtures,
)
from algorithm_playground.problems.sorting._frames import (
    draw_sorting_input_output_frame,
    draw_sorting_trace_frames,
)
from algorithm_playground.problems.sorting._generators import (
    build_sorting_generators,
    compute_median_of_three_killer_ranks,
)
from algorithm_playground.problems.sorting._problem import (
    SortingProblem,
)
from algorithm_playground.problems.sorting._replay import (
    build_sorting_timeline,
    find_replay_warnings,
)
from algorithm_playground.problems.sorting._trace import (
    EVENT_TRACE_KIND,
    SNAPSHOT_TRACE_KIND,
    SortingTrace,
    choose_start_values,
    count_operations,
    read_trace,
)
from algorithm_playground.problems.sorting._verification import (
    verify_sorted,
)

__all__ = [
    "EVENT_RECORD_BYTES",
    "EVENT_TRACE_KIND",
    "I32_MAX",
    "I32_MIN",
    "SNAPSHOT_TRACE_KIND",
    "EventLog",
    "EventType",
    "SortingEvent",
    "SortingProblem",
    "SortingTrace",
    "build_sorting_fixtures",
    "build_sorting_generators",
    "build_sorting_timeline",
    "choose_start_values",
    "compute_median_of_three_killer_ranks",
    "count_operations",
    "draw_sorting_input_output_frame",
    "draw_sorting_trace_frames",
    "find_replay_warnings",
    "read_trace",
    "read_values",
    "verify_sorted",
    "write_values",
]
