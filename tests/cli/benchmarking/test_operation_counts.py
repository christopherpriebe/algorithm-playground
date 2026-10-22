"""Tests for the operation counts that the benchmark command reports from traces."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import Result

from algorithm_playground.core import RunnerError
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import INSTRUMENTED_SORT
from helpers.fakes import (
    FakeRunners,
    TraceFailure,
    build_insertion_sort_trace,
    build_merge_sort_trace,
    build_snapshot_only_trace,
    sort_correctly,
)
from helpers.support import invoke_cli, parse_table_rows

pytestmark = pytest.mark.integration


UseFakeRunners = Callable[..., FakeRunners]


SIZES = "8,16,32"


class BenchmarkRun(NamedTuple):
    """The outcome of a benchmark command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


def invoke_benchmark(*arguments: str, sizes: str = SIZES) -> Result:
    """Benchmark the implementations on the reversed distribution, with one repetition."""
    return invoke_cli(
        "benchmark",
        "sorting",
        *arguments,
        "--sizes",
        sizes,
        "--repetitions",
        "1",
        "--warmup",
        "0",
        "--no-plot",
        "--distribution",
        "reversed",
    )


def extract_operation_section(output: str) -> str:
    """Return the part of the output from the first operation table title on."""
    assert "compares — sorting" in output, output
    return output[output.index("compares — sorting") :]


def parse_operation_rows(output: str, operation: str) -> list[list[str]]:
    """Return the body rows of the table of one operation (they end at the next title)."""
    section = extract_operation_section(output)
    start = section.index(f"{operation} — sorting")
    following = [
        section.index(f"{other} — sorting", start + 1)
        for other in ("compares", "swaps", "writes")
        if other != operation and f"{other} — sorting" in section[start + 1 :]
    ]
    return parse_table_rows(section[start : min(following, default=len(section))])


def build_instrumented_command(algorithm: str, *flags: str) -> str:
    """Build the command line that runs an instrumented sorter with the given flags."""
    return (
        f"{sys.executable} {INSTRUMENTED_SORT} {' '.join(flags)} {algorithm}".replace(
            "  ", " "
        )
    )


def invoke_stepping(command: str, keystrokes: str, *, size: str, seed: str) -> Result:
    """Run ``debug`` on a command and answer the stepper with the keystrokes."""
    return invoke_cli(
        "debug",
        "sorting",
        "--command",
        command,
        "--size",
        size,
        "--seed",
        seed,
        keystrokes=keystrokes,
    )


@pytest.fixture
def insertion_and_merge_result(use_fake_runners: UseFakeRunners) -> Result:
    """The result of counting the operations of an insertion sort and a merge sort."""
    use_fake_runners(
        {"insertion": sort_correctly, "merge": sort_correctly},
        traces={
            "insertion": build_insertion_sort_trace,
            "merge": build_merge_sort_trace,
        },
    )
    return invoke_benchmark(
        "--command", "insertion", "--command", "merge", "--count-operations"
    )


@pytest.fixture
def malformed_trace_run(
    use_fake_runners: UseFakeRunners, tmp_path: Path
) -> BenchmarkRun:
    """Count the operations of an implementation with a malformed trace and a good one."""
    use_fake_runners(
        {"broken": sort_correctly, "fine": sort_correctly},
        traces={
            "broken": lambda _values: TraceFailure("Unsupported trace kind: 7"),
            "fine": build_insertion_sort_trace,
        },
    )
    path = tmp_path / "report.json"
    result = invoke_benchmark(
        "--command",
        "broken",
        "--command",
        "fine",
        "--count-operations",
        "--json",
        str(path),
        sizes="8,16",
    )
    return BenchmarkRun(result, json.loads(path.read_text()))


def test_the_comparisons_are_listed_per_operation_with_a_column_per_implementation(
    insertion_and_merge_result: Result,
) -> None:
    """Test the compares table has a column of counts per implementation and their growth."""
    assert insertion_and_merge_result.exit_code == 0, insertion_and_merge_result.stdout
    assert parse_operation_rows(insertion_and_merge_result.stdout, "compares") == [
        ["8", "28", "12"],
        ["16", "120", "32"],
        ["32", "496", "80"],
        ["growth", "~ n^2 (n^2.07)", "~ n log n (n^1.37)"],
    ]


def test_the_swaps_are_listed_with_a_dash_for_growth_without_swaps(
    insertion_and_merge_result: Result,
) -> None:
    """Test the swaps table shows no growth for the implementation that never swaps."""
    assert parse_operation_rows(insertion_and_merge_result.stdout, "swaps") == [
        ["8", "28", "0"],
        ["16", "120", "0"],
        ["32", "496", "0"],
        ["growth", "~ n^2 (n^2.07)", "-"],
    ]


def test_the_writes_are_listed_per_size(insertion_and_merge_result: Result) -> None:
    """Test the writes table counts the writes of each implementation at every size."""
    assert parse_operation_rows(insertion_and_merge_result.stdout, "writes")[:3] == [
        ["8", "0", "24"],
        ["16", "0", "64"],
        ["32", "0", "160"],
    ]


def test_an_implementation_that_reports_nothing_says_so_in_every_row_of_every_table(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test implementations without a usable trace are marked in each table of counts."""
    use_fake_runners(
        {
            "traced": sort_correctly,
            "snapshots": sort_correctly,
            "silent": sort_correctly,
        },
        traces={
            "traced": build_insertion_sort_trace,
            "snapshots": build_snapshot_only_trace,
        },
    )

    result = invoke_benchmark(
        "--command",
        "traced",
        "--command",
        "snapshots",
        "--command",
        "silent",
        "--count-operations",
        sizes="8,16",
    )

    assert result.exit_code == 0, result.stdout
    for operation, counts in (
        ("compares", ("28", "120")),
        ("swaps", ("28", "120")),
    ):
        assert parse_operation_rows(result.stdout, operation) == [
            ["8", counts[0], "not reported", "not reported"],
            ["16", counts[1], "not reported", "not reported"],
        ]


def test_a_malformed_trace_is_named_in_the_table(
    malformed_trace_run: BenchmarkRun,
) -> None:
    """Test the table of counts marks the implementation whose trace is malformed."""
    result = malformed_trace_run.result

    assert result.exit_code == 0, result.stdout
    assert parse_operation_rows(result.stdout, "compares") == [
        ["8", "malformed trace", "28"],
        ["16", "malformed trace", "120"],
    ]


def test_a_malformed_trace_is_explained_below_the_table(
    malformed_trace_run: BenchmarkRun,
) -> None:
    """Test the notes below the tables explain each malformed trace, and only those."""
    stdout = malformed_trace_run.result.stdout

    below = stdout[stdout.rindex("┘") :]
    assert "broken (reversed, size=8): no operation counts, malformed trace:" in below
    assert "Unsupported trace kind: 7" in below
    assert "broken (reversed, size=16)" in below
    assert "fine (" not in below


def test_a_malformed_trace_is_recorded_as_an_issue_in_the_json_report(
    malformed_trace_run: BenchmarkRun,
) -> None:
    """Test the report holds no counts for a malformed trace but the kind and the message."""
    record = malformed_trace_run.report["implementations"][0]["results"][0]

    assert record["operation_counts"] is None
    assert record["operation_issue"] == {
        "kind": "malformed trace",
        "message": "Unsupported trace kind: 7",
    }


def test_counts_come_only_from_a_run_whose_output_verifies(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test an implementation whose traced run gives a wrong output has no counts."""
    use_fake_runners(
        {"liar": sort_correctly, "honest": sort_correctly},
        traces={
            "liar": build_insertion_sort_trace,
            "honest": build_insertion_sort_trace,
        },
        traced_behaviors={"liar": lambda values: sorted(values)[:-1]},
    )

    result = invoke_benchmark(
        "--command",
        "liar",
        "--command",
        "honest",
        "--count-operations",
        sizes="8,16",
    )

    assert result.exit_code == 0, result.stdout
    assert parse_operation_rows(result.stdout, "compares") == [
        ["8", "output did not verify", "28"],
        ["16", "output did not verify", "120"],
    ]
    assert (
        "no operation counts, output did not verify: Output length 7" in result.stdout
    )


def test_the_reasons_are_given_even_when_no_counts_remain_for_a_table(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test the reasons for missing counts are printed when no implementation has counts."""
    use_fake_runners(
        {"liar": sort_correctly},
        traces={"liar": build_insertion_sort_trace},
        traced_behaviors={"liar": lambda _values: []},
    )

    result = invoke_benchmark("--command", "liar", "--count-operations", sizes="8")

    assert result.exit_code == 0, result.stdout
    assert "No implementation reported operation counts." in result.stdout
    assert "liar (reversed, size=8): no operation counts, output did not verify" in (
        result.stdout
    )


def test_without_verification_the_counts_are_read_anyway(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test the counts of a wrong output are kept when verification is turned off."""
    use_fake_runners(
        {"liar": sort_correctly},
        traces={"liar": build_insertion_sort_trace},
        traced_behaviors={"liar": lambda _values: []},
    )

    result = invoke_benchmark(
        "--command", "liar", "--count-operations", "--no-verify", sizes="8"
    )

    assert result.exit_code == 0, result.stdout
    assert parse_operation_rows(result.stdout, "compares")[0] == ["8", "28"]


def test_a_failed_counting_run_marks_the_cell_and_skips_the_rest_of_the_distribution(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a traced run that fails is marked, and the larger sizes after it are skipped."""

    def fail_for_large_inputs(values: list[int]) -> object:
        if len(values) > 8:
            message = "trace file could not be written"
            raise RunnerError(message)
        return build_insertion_sort_trace(values)

    use_fake_runners(
        {"counter": sort_correctly}, traces={"counter": fail_for_large_inputs}
    )

    result = invoke_benchmark(
        "--command", "counter", "--count-operations", sizes="8,16,32"
    )

    assert result.exit_code == 1, result.stdout
    assert parse_operation_rows(result.stdout, "compares") == [
        ["8", "28"],
        ["16", "counting failed"],
        ["32", "skipped"],
    ]
    assert "while counting operations" in result.stdout


def test_names_that_look_like_markup_are_shown_as_they_are(
    use_fake_runners: UseFakeRunners,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test operation names and implementation names are printed without markup parsing."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(
        SortingProblem,
        "operation_counts",
        lambda _self, _input_data, _output, _trace: {
            "[red]compares[/red]": 1,
            "[bold": 2,
        },
    )
    use_fake_runners(
        {"[b]odd[/b]": sort_correctly},
        traces={"[b]odd[/b]": build_insertion_sort_trace},
    )

    result = invoke_benchmark("--command", "[b]odd[/b]", "--count-operations")

    assert result.exit_code == 0, result.stdout
    output = result.stdout
    assert "[red]compares[/red] — sorting" in output
    assert "[bold — sorting" in output
    headers = [line for line in output.splitlines() if line.startswith("┃")]
    assert all("[b]odd[/b]" in header for header in headers[1:])
    section = output[output.index("[red]compares[/red] — sorting") :]
    assert parse_table_rows(section)[0] == ["8", "1"]


def test_a_note_replaces_the_table_when_nobody_reports_counts(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a note is printed instead of tables when no implementation reports counts."""
    use_fake_runners({"silent": sort_correctly})

    result = invoke_benchmark("--command", "silent", "--count-operations")

    assert result.exit_code == 0, result.stdout
    assert "No implementation reported operation counts." in result.stdout
    assert "Counted in one extra untimed run" not in result.stdout


def test_nothing_is_counted_without_the_option(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test no traced run is made when operation counting is not requested."""
    runners = use_fake_runners(
        {"counter": sort_correctly}, traces={"counter": build_insertion_sort_trace}
    )

    result = invoke_benchmark("--command", "counter")

    assert result.exit_code == 0, result.stdout
    assert "Counted in one extra untimed run" not in result.stdout
    assert runners.traced_calls == []


def test_several_distributions_get_a_header_row_each(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test every table of counts has a header row for each measured distribution."""
    use_fake_runners(
        {"counter": sort_correctly}, traces={"counter": build_insertion_sort_trace}
    )

    result = invoke_cli(
        "benchmark",
        "sorting",
        "--command",
        "counter",
        "--count-operations",
        "--sizes",
        "8,16,32",
        "--repetitions",
        "1",
        "--warmup",
        "0",
        "--no-plot",
        "--distribution",
        "sorted",
        "--distribution",
        "reversed",
    )

    assert result.exit_code == 0, result.stdout
    rows = parse_operation_rows(result.stdout, "compares")
    assert rows[:2] == [["sorted", ""], ["8", "7"]]
    assert rows[5:7] == [["reversed", ""], ["8", "28"]]
    assert parse_operation_rows(result.stdout, "swaps")[:2] == [
        ["sorted", ""],
        ["8", "0"],
    ]


def test_the_json_report_carries_counts_and_their_growth(
    use_fake_runners: UseFakeRunners,
    tmp_path: Path,
) -> None:
    """Test the JSON report holds the counts of every run and the growth of the counts."""
    use_fake_runners(
        {"insertion": sort_correctly, "silent": sort_correctly},
        traces={"insertion": build_insertion_sort_trace},
    )
    path = tmp_path / "report.json"

    result = invoke_benchmark(
        "--command",
        "insertion",
        "--command",
        "silent",
        "--count-operations",
        "--json",
        str(path),
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(path.read_text())
    assert report["format_version"] == 7
    assert report["settings"]["count_operations"] is True
    insertion, silent = report["implementations"]
    assert insertion["results"][0]["operation_counts"] == {
        "compares": 28,
        "swaps": 28,
        "writes": 0,
    }
    compares_growth = insertion["operation_growth"]["reversed"]["compares"]
    assert compares_growth["exponent"] == pytest.approx(2.0, abs=0.1)
    assert compares_growth["class"] == "n^2"
    assert silent["results"][0]["operation_counts"] is None
    assert silent["operation_growth"] == {"reversed": {}}


def test_the_option_is_documented_in_the_help() -> None:
    """Test the help of the benchmark command lists the count-operations option."""
    result = invoke_cli("benchmark", "--help")

    assert "--count-operations" in result.stdout


def test_instrumented_sorters_report_counts_through_their_trace_files(
    tmp_path: Path,
) -> None:
    """Test counts are read from the trace files that real sorters write."""
    path = tmp_path / "report.json"

    result = invoke_benchmark(
        "--command",
        build_instrumented_command("insertion"),
        "--command",
        build_instrumented_command("merge", "--events-only"),
        "--count-operations",
        "--json",
        str(path),
    )

    assert result.exit_code == 0, result.stdout
    insertion, merge = json.loads(path.read_text())["implementations"]
    assert [record["operation_counts"] for record in insertion["results"]] == [
        {"compares": 28, "swaps": 28, "writes": 0},
        {"compares": 120, "swaps": 120, "writes": 0},
        {"compares": 496, "swaps": 496, "writes": 0},
    ]
    assert [record["operation_counts"] for record in merge["results"]] == [
        {"compares": 12, "swaps": 0, "writes": 24},
        {"compares": 32, "swaps": 0, "writes": 64},
        {"compares": 80, "swaps": 0, "writes": 160},
    ]


def test_debug_steps_through_the_events_and_shows_the_running_counts() -> None:
    """Test debug steps through the frames of a trace and shows the counts so far."""
    result = invoke_stepping(
        build_instrumented_command("insertion"),
        "n\nn\ng 8\nq\n",
        size="6",
        seed="3",
    )

    assert result.exit_code == 0, result.stdout
    assert "frame 1 / " in result.stdout
    assert "frame 8 / " in result.stdout
    assert "start: " in result.stdout
    assert "event 1 / " in result.stdout
    assert "so far: " in result.stdout
    assert "Trace warning" not in result.stdout


def test_debug_works_from_events_alone() -> None:
    """Test debug steps through a trace that holds events and no snapshots."""
    result = invoke_stepping(
        build_instrumented_command("merge", "--events-only"),
        "n\nq\n",
        size="5",
        seed="1",
    )

    assert result.exit_code == 0, result.stdout
    assert "event 1 / " in result.stdout


def test_debug_warns_when_the_events_do_not_reach_the_final_snapshot() -> None:
    """Test debug warns when replaying the events does not give the final snapshot."""
    result = invoke_stepping(
        build_instrumented_command("insertion", "--wrong-final-snapshot"),
        "q\n",
        size="6",
        seed="3",
    )

    assert result.exit_code == 0, result.stdout
    assert "Trace warning: Replaying the" in result.stdout
    assert "Output verified." in result.stdout
