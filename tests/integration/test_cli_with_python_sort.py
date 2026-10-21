"""End-to-end CLI tests that invoke the Typer app via Click's runner.

We use :class:`typer.testing.CliRunner` instead of spawning a subprocess so
the tests are fast and deterministic in CI. The runner still exercises the
real argument parsing, problem registry, subprocess Runner, and on-disk
binary I/O against the reference Python executables in ``examples/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from algorithm_playground.cli.main import app


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


pytestmark = pytest.mark.integration


class TestList:
    def test_lists_sorting(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "sorting" in result.stdout


class TestTest:
    def test_python_sort_passes_every_fixture(
        self, runner: CliRunner, python_sort_executable: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["test", "sorting", str(python_sort_executable)],
        )
        assert result.exit_code == 0, result.stdout
        assert "fixtures passed" in result.stdout

    def test_unknown_problem_exits_with_code_2(
        self, runner: CliRunner, python_sort_executable: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["test", "not-a-problem", str(python_sort_executable)],
        )
        assert result.exit_code == 2

    def test_malformed_output_is_reported_per_fixture(
        self, runner: CliRunner, truncated_output_executable: Path
    ) -> None:
        result = runner.invoke(app, ["test", "sorting", str(truncated_output_executable)])
        # Every fixture fails, and the CLI exits cleanly instead of crashing.
        assert isinstance(result.exception, SystemExit), result.exception
        assert result.exit_code == 10
        assert "ERROR" in result.stdout
        assert "0/10 fixtures passed" in result.stdout


class TestBenchmark:
    def test_writes_json_report_with_metadata(
        self, runner: CliRunner, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        json_path = tmp_path / "report.json"
        result = runner.invoke(
            app,
            [
                "benchmark",
                "sorting",
                str(python_sort_executable),
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
            ],
        )
        assert result.exit_code == 0, result.stdout
        report = json.loads(json_path.read_text())
        assert report["problem"] == "sorting"
        assert report["configuration"]["seed"] == 42
        assert {record["size"] for record in report["results"]} == {100, 1000}
        for record in report["results"]:
            assert record["minimum_seconds"] > 0.0
            assert record["median_seconds"] > 0.0
            assert len(record["samples_seconds"]) == 2
        assert "sha256" in report["executable"]
        assert report["host"]["system"]

    def _run_benchmark(
        self, runner: CliRunner, executable: Path, json_path: Path, *extra: str
    ) -> dict:
        result = runner.invoke(
            app,
            [
                "benchmark",
                "sorting",
                str(executable),
                "--sizes",
                "100",
                "--repetitions",
                "3",
                "--warmup",
                "0",
                "--no-plot",
                "--json",
                str(json_path),
                *extra,
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert "startup (empty input)" in result.stdout
        return json.loads(json_path.read_text())

    def test_reports_startup_time_without_subtracting_by_default(
        self, runner: CliRunner, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        report = self._run_benchmark(runner, python_sort_executable, tmp_path / "report.json")
        assert report["configuration"]["subtract_startup_time"] is False
        assert len(report["startup"]["samples_seconds"]) == 3
        assert report["startup"]["mean_seconds"] > 0.0
        record = report["results"][0]
        assert record["samples_seconds"] == record["raw_samples_seconds"]

    def test_subtract_startup_time_removes_startup_mean_from_each_sample(
        self, runner: CliRunner, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        report = self._run_benchmark(
            runner, python_sort_executable, tmp_path / "report.json", "--subtract-startup-time"
        )
        assert report["configuration"]["subtract_startup_time"] is True
        startup_mean = report["startup"]["mean_seconds"]
        record = report["results"][0]
        expected = [raw - startup_mean for raw in record["raw_samples_seconds"]]
        assert record["samples_seconds"] == pytest.approx(expected)
        assert record["minimum_seconds"] == pytest.approx(min(expected))


class TestDebugFallback:
    def test_no_trace_falls_back_to_io_view(
        self, runner: CliRunner, c_qsort_executable: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["debug", "sorting", str(c_qsort_executable), "--size", "4", "--seed", "1"],
        )
        assert result.exit_code == 0, result.stdout
        assert "did not produce a usable trace" in result.stdout

    def test_malformed_trace_is_reported_then_falls_back(
        self, runner: CliRunner, malformed_trace_executable: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["debug", "sorting", str(malformed_trace_executable), "--size", "4", "--seed", "1"],
        )
        assert result.exit_code == 0, result.exception
        assert "Trace file is malformed" in result.stdout
        assert "did not produce a usable trace" in result.stdout
