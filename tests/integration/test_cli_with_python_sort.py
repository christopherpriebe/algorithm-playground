"""End-to-end CLI tests that invoke the Typer app via Click's runner.

We use :class:`typer.testing.CliRunner` instead of spawning a subprocess so
the tests are fast and deterministic in CI. The runner still exercises the
real argument parsing, problem registry, subprocess Runner, and on-disk
binary I/O against the reference Python executables in ``examples/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from support import Invoke, assert_exits_with

pytestmark = pytest.mark.integration


class TestList:
    def test_lists_sorting(self, invoke: Invoke) -> None:
        result = invoke("list")
        assert result.exit_code == 0
        assert "sorting" in result.stdout


class TestTest:
    def test_python_sort_passes_every_fixture(
        self, invoke: Invoke, python_sort_executable: Path, sorting_fixture_count: int
    ) -> None:
        result = invoke("test", "sorting", str(python_sort_executable), "--random-cases", "1")
        assert result.exit_code == 0, result.stdout
        total = sorting_fixture_count
        assert (
            f"python_sort.py: {total + 1}/{total + 1} cases passed "
            f"({total}/{total} fixtures, 1/1 generated)"
        ) in result.stdout

    def test_unknown_problem_exits_with_code_2_and_names_the_registered_ones_on_standard_error(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("test", "not-a-problem", str(python_sort_executable))
        assert_exits_with(result, 2)
        assert result.stderr.startswith("Unknown problem 'not-a-problem'. Registered problems:")
        assert "sorting" in result.stderr
        assert result.stdout == ""

    @pytest.mark.usefixtures("only_first_fixture")
    def test_malformed_output_is_reported_per_case(
        self, invoke: Invoke, truncated_output_executable: Path
    ) -> None:
        result = invoke("test", "sorting", str(truncated_output_executable), "--random-cases", "1")
        # Every case errors, and the CLI exits with the failure code instead of crashing.
        assert isinstance(result.exception, SystemExit), result.exception
        assert result.exit_code == 1
        assert "ERROR" in result.stdout
        assert "0/2 cases passed (0/1 fixtures, 0/1 generated)" in result.stdout


def run_benchmark_command(
    invoke: Invoke, executable: Path, json_path: Path, *extra: str
) -> dict[str, Any]:
    """Benchmark ``executable`` on two sizes with two repetitions; return the JSON report."""
    result = invoke(
        "benchmark",
        "sorting",
        str(executable),
        "--seed",
        "42",
        "--sizes",
        "100,1000",
        "--repetitions",
        "2",
        "--warmup",
        "0",
        "--no-plot",
        "--json",
        str(json_path),
        *extra,
    )
    assert result.exit_code == 0, result.stdout
    assert "startup" in result.stdout
    return json.loads(json_path.read_text())


class TestBenchmark:
    @pytest.fixture(scope="class")
    def report(
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> dict[str, Any]:
        json_path = tmp_path_factory.mktemp("benchmark") / "report.json"
        return run_benchmark_command(invoke, python_sort_executable, json_path)

    def test_writes_json_report_with_metadata(
        self, report: dict[str, Any], python_sort_executable: Path
    ) -> None:
        assert report["problem"] == "sorting"
        assert report["settings"]["seed"] == 42
        implementation = report["implementations"][0]
        assert {record["size"] for record in implementation["results"]} == {100, 1000}
        for record in implementation["results"]:
            assert record["minimum_seconds"] > 0.0
            assert record["median_seconds"] > 0.0
            assert len(record["samples_seconds"]) == 2
        assert implementation["files"][0]["path"] == str(python_sort_executable.resolve())
        assert implementation["files"][0]["sha256"]
        assert report["host"]["system"]

    def test_reports_startup_time_without_subtracting_by_default(
        self, report: dict[str, Any]
    ) -> None:
        assert report["settings"]["subtract_startup_time"] is False
        implementation = report["implementations"][0]
        assert len(implementation["startup"]["samples_seconds"]) == 2
        assert implementation["startup"]["mean_seconds"] > 0.0
        for record in implementation["results"]:
            assert record["samples_seconds"] == sorted(record["raw_samples_seconds"])

    def test_subtract_startup_time_removes_startup_mean_from_each_sample(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        report = run_benchmark_command(
            invoke, python_sort_executable, tmp_path / "report.json", "--subtract-startup-time"
        )
        assert report["settings"]["subtract_startup_time"] is True
        implementation = report["implementations"][0]
        startup_mean = implementation["startup"]["mean_seconds"]
        for record in implementation["results"]:
            expected = sorted(raw - startup_mean for raw in record["raw_samples_seconds"])
            assert record["samples_seconds"] == pytest.approx(expected)
            assert record["minimum_seconds"] == pytest.approx(min(expected))


class TestDebugFallback:
    def test_no_trace_falls_back_to_io_view(self, invoke: Invoke, c_qsort_executable: Path) -> None:
        result = invoke("debug", "sorting", str(c_qsort_executable), "--size", "4", "--seed", "1")
        assert result.exit_code == 0, result.stdout
        assert "did not produce a usable trace" in result.stderr
        assert "did not produce a usable trace" not in result.stdout

    def test_malformed_trace_is_reported_then_falls_back(
        self, invoke: Invoke, malformed_trace_executable: Path
    ) -> None:
        result = invoke(
            "debug", "sorting", str(malformed_trace_executable), "--size", "4", "--seed", "1"
        )
        assert result.exit_code == 0, result.exception
        assert "Trace file is malformed" in result.stderr
        assert "did not produce a usable trace" in result.stderr
        assert result.stdout.count("Output verified.") == 1
