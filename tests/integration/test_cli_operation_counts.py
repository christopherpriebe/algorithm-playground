"""CLI tests for ``benchmark --count-operations`` and for stepping through event traces in ``debug``.

Most tests run the benchmark with in-process fake runners; the last ones of each
class run the instrumented sorters of ``tests/instrumented_sort.py`` as real processes.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import (
    FakeRunners,
    TraceFailure,
    insertion_sort_trace,
    merge_sort_trace,
    snapshot_only_trace,
    sort_correctly,
)
from support import Invoke, TableRows
from typer.testing import CliRunner, Result

from algorithm_playground.cli.main import app
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

UseFakeRunners = Callable[..., FakeRunners]

INSTRUMENTED_SORT = Path(__file__).resolve().parent.parent / "instrumented_sort.py"
SIZES = "8,16,32"


def benchmark(invoke: Invoke, *arguments: str, sizes: str = SIZES) -> Result:
    return invoke(
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


def operation_section(output: str) -> str:
    """Return the part of the output from the first operation table title on."""
    assert "compares — sorting" in output, output
    return output[output.index("compares — sorting") :]


def operation_rows(output: str, table_rows: TableRows, operation: str) -> list[list[str]]:
    """Return the body rows of the table of one operation (they end at the next title)."""
    section = operation_section(output)
    start = section.index(f"{operation} — sorting")
    following = [
        section.index(f"{other} — sorting", start + 1)
        for other in ("compares", "swaps", "writes")
        if other != operation and f"{other} — sorting" in section[start + 1 :]
    ]
    return table_rows(section[start : min(following, default=len(section))])


class TestOperationCountTable:
    def test_counts_are_listed_per_operation_with_a_column_per_implementation(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"insertion": sort_correctly, "merge": sort_correctly},
            traces={"insertion": insertion_sort_trace, "merge": merge_sort_trace},
        )
        result = benchmark(
            invoke, "--command", "insertion", "--command", "merge", "--count-operations"
        )
        assert result.exit_code == 0, result.stdout
        output = result.stdout
        assert operation_rows(output, table_rows, "compares") == [
            ["8", "28", "12"],
            ["16", "120", "32"],
            ["32", "496", "80"],
            ["growth", "~ n^2 (n^2.07)", "~ n log n (n^1.37)"],
        ]
        assert operation_rows(output, table_rows, "swaps") == [
            ["8", "28", "0"],
            ["16", "120", "0"],
            ["32", "496", "0"],
            ["growth", "~ n^2 (n^2.07)", "-"],
        ]
        assert operation_rows(output, table_rows, "writes")[:3] == [
            ["8", "0", "24"],
            ["16", "0", "64"],
            ["32", "0", "160"],
        ]

    def test_an_implementation_that_reports_nothing_says_so_in_every_row_of_every_table(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"traced": sort_correctly, "snapshots": sort_correctly, "silent": sort_correctly},
            traces={"traced": insertion_sort_trace, "snapshots": snapshot_only_trace},
        )
        result = benchmark(
            invoke,
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
        for operation, counts in (("compares", ("28", "120")), ("swaps", ("28", "120"))):
            assert operation_rows(result.stdout, table_rows, operation) == [
                ["8", counts[0], "not reported", "not reported"],
                ["16", counts[1], "not reported", "not reported"],
            ]

    def test_a_malformed_trace_is_named_in_the_table_and_explained_below_it(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        table_rows: TableRows,
        tmp_path: Path,
    ) -> None:
        use_fake_runners(
            {"broken": sort_correctly, "fine": sort_correctly},
            traces={
                "broken": lambda values: TraceFailure("Unsupported trace kind: 7"),
                "fine": insertion_sort_trace,
            },
        )
        path = tmp_path / "report.json"
        result = benchmark(
            invoke,
            "--command",
            "broken",
            "--command",
            "fine",
            "--count-operations",
            "--json",
            str(path),
            sizes="8,16",
        )
        assert result.exit_code == 0, result.stdout
        assert operation_rows(result.stdout, table_rows, "compares") == [
            ["8", "malformed trace", "28"],
            ["16", "malformed trace", "120"],
        ]
        below = result.stdout[result.stdout.rindex("┘") :]
        assert "broken (reversed, size 8): no operation counts, malformed trace:" in below
        assert "Unsupported trace kind: 7" in below
        assert "broken (reversed, size 16)" in below
        assert "fine (" not in below
        record = json.loads(path.read_text())["implementations"][0]["results"][0]
        assert record["operation_counts"] is None
        assert record["operation_issue"] == {
            "kind": "malformed trace",
            "message": "Unsupported trace kind: 7",
        }

    def test_counts_come_only_from_a_run_whose_output_verifies(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"liar": sort_correctly, "honest": sort_correctly},
            traces={"liar": insertion_sort_trace, "honest": insertion_sort_trace},
            traced_behaviors={"liar": lambda values: sorted(values)[:-1]},
        )
        result = benchmark(
            invoke, "--command", "liar", "--command", "honest", "--count-operations", sizes="8,16"
        )
        assert result.exit_code == 0, result.stdout
        assert operation_rows(result.stdout, table_rows, "compares") == [
            ["8", "output did not verify", "28"],
            ["16", "output did not verify", "120"],
        ]
        assert "no operation counts, output did not verify: Output length 7" in result.stdout

    def test_the_reasons_are_given_even_when_no_counts_remain_for_a_table(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners
    ) -> None:
        use_fake_runners(
            {"liar": sort_correctly},
            traces={"liar": insertion_sort_trace},
            traced_behaviors={"liar": lambda values: []},
        )
        result = benchmark(invoke, "--command", "liar", "--count-operations", sizes="8")
        assert result.exit_code == 0, result.stdout
        assert "No implementation reported operation counts." in result.stdout
        assert "liar (reversed, size 8): no operation counts, output did not verify" in (
            result.stdout
        )

    def test_without_verification_the_counts_are_read_anyway(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"liar": sort_correctly},
            traces={"liar": insertion_sort_trace},
            traced_behaviors={"liar": lambda values: []},
        )
        result = benchmark(
            invoke, "--command", "liar", "--count-operations", "--no-verify", sizes="8"
        )
        assert result.exit_code == 0, result.stdout
        assert operation_rows(result.stdout, table_rows, "compares")[0] == ["8", "28"]

    def test_a_failed_counting_run_marks_the_cell_and_skips_the_rest_of_the_distribution(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        from algorithm_playground.core.runner import RunnerError

        def fail_for_large(values: list[int]) -> object:
            if len(values) > 8:
                raise RunnerError("trace file could not be written")
            return insertion_sort_trace(values)

        use_fake_runners({"a": sort_correctly}, traces={"a": fail_for_large})
        result = benchmark(invoke, "--command", "a", "--count-operations", sizes="8,16,32")
        assert result.exit_code == 1, result.stdout
        assert operation_rows(result.stdout, table_rows, "compares") == [
            ["8", "28"],
            ["16", "counting failed"],
            ["32", "skipped"],
        ]
        assert "while counting operations" in result.stdout

    def test_names_that_look_like_markup_are_shown_as_they_are(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        monkeypatch: pytest.MonkeyPatch,
        table_rows: TableRows,
    ) -> None:
        monkeypatch.setenv("COLUMNS", "200")
        monkeypatch.setattr(
            SortingProblem,
            "operation_counts",
            lambda self, input_data, output, trace: {"[red]compares[/red]": 1, "[bold": 2},
        )
        use_fake_runners(
            {"[b]odd[/b]": sort_correctly}, traces={"[b]odd[/b]": insertion_sort_trace}
        )
        result = benchmark(invoke, "--command", "[b]odd[/b]", "--count-operations")
        assert result.exit_code == 0, result.stdout
        output = result.stdout
        assert "[red]compares[/red] — sorting" in output and "[bold — sorting" in output
        headers = [line for line in output.splitlines() if line.startswith("┃")]
        assert all("[b]odd[/b]" in header for header in headers[1:])
        section = output[output.index("[red]compares[/red] — sorting") :]
        assert table_rows(section)[0] == ["8", "1"]

    def test_a_note_replaces_the_table_when_nobody_reports_counts(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners
    ) -> None:
        use_fake_runners({"silent": sort_correctly})
        result = benchmark(invoke, "--command", "silent", "--count-operations")
        assert result.exit_code == 0, result.stdout
        assert "No implementation reported operation counts." in result.stdout
        assert "Counted in one extra untimed run" not in result.stdout

    def test_nothing_is_counted_without_the_option(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners
    ) -> None:
        runners = use_fake_runners({"a": sort_correctly}, traces={"a": insertion_sort_trace})
        result = benchmark(invoke, "--command", "a")
        assert result.exit_code == 0, result.stdout
        assert "Counted in one extra untimed run" not in result.stdout
        assert runners.traced_calls == []

    def test_several_distributions_get_a_header_row_each(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"a": sort_correctly}, traces={"a": insertion_sort_trace})
        result = invoke(
            "benchmark",
            "sorting",
            "--command",
            "a",
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
        rows = operation_rows(result.stdout, table_rows, "compares")
        assert rows[:2] == [["sorted", ""], ["8", "7"]]
        assert rows[5:7] == [["reversed", ""], ["8", "28"]]
        assert operation_rows(result.stdout, table_rows, "swaps")[:2] == [
            ["sorted", ""],
            ["8", "0"],
        ]

    def test_the_json_report_carries_counts_and_their_growth(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        tmp_path: Path,
    ) -> None:
        use_fake_runners(
            {"insertion": sort_correctly, "silent": sort_correctly},
            traces={"insertion": insertion_sort_trace},
        )
        path = tmp_path / "report.json"
        result = benchmark(
            invoke,
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
        assert report["format_version"] == 6
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

    def test_the_option_is_documented_in_the_help(self, invoke: Invoke) -> None:
        result = invoke("benchmark", "--help")
        assert "--count-operations" in result.stdout


class TestWithRealProcesses:
    def command(self, algorithm: str, *flags: str) -> str:
        return f"{sys.executable} {INSTRUMENTED_SORT} {' '.join(flags)} {algorithm}".replace(
            "  ", " "
        )

    def test_instrumented_sorters_report_counts_through_their_trace_files(
        self, invoke: Invoke, tmp_path: Path
    ) -> None:
        path = tmp_path / "report.json"
        result = benchmark(
            invoke,
            "--command",
            self.command("insertion"),
            "--command",
            self.command("merge", "--events-only"),
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

    def test_debug_steps_through_the_events_and_shows_the_running_counts(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "debug",
                "sorting",
                "--command",
                self.command("insertion"),
                "--size",
                "6",
                "--seed",
                "3",
            ],
            input="n\nn\ng 8\nq\n",
        )
        assert result.exit_code == 0, result.stdout
        assert "frame 1 / " in result.stdout and "frame 8 / " in result.stdout
        assert "start: " in result.stdout
        assert "event 1 / " in result.stdout
        assert "so far: " in result.stdout
        assert "Trace warning" not in result.stdout

    def test_debug_works_from_events_alone(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "debug",
                "sorting",
                "--command",
                self.command("merge", "--events-only"),
                "--size",
                "5",
                "--seed",
                "1",
            ],
            input="n\nq\n",
        )
        assert result.exit_code == 0, result.stdout
        assert "event 1 / " in result.stdout

    def test_debug_warns_when_the_events_do_not_reach_the_final_snapshot(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "debug",
                "sorting",
                "--command",
                self.command("insertion", "--wrong-final-snapshot"),
                "--size",
                "6",
                "--seed",
                "3",
            ],
            input="q\n",
        )
        assert result.exit_code == 0, result.stdout
        assert "Trace warning: Replaying the" in result.stdout
        assert "Output verified." in result.stdout
