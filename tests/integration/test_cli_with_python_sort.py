"""End-to-end CLI tests that invoke the Typer app via Click's runner.

We use :class:`typer.testing.CliRunner` instead of spawning a subprocess so
the tests are fast and deterministic in CI. The runner still exercises the
real argument parsing, problem registry, subprocess Runner, and on-disk
binary I/O against the reference Python executables in ``examples/``.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.support import assert_exits_with, invoke_cli

pytestmark = pytest.mark.integration


def run_benchmark_command(
    executable: Path, json_path: Path, *additional_arguments: str
) -> dict[str, Any]:
    """Benchmark ``executable`` on two sizes with two repetitions; return the JSON report."""
    result = invoke_cli(
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
        *additional_arguments,
    )
    assert result.exit_code == 0, result.stdout
    assert "startup" in result.stdout
    return json.loads(json_path.read_text())


class TestListCommand:
    def test_list_shows_the_sorting_problem(self) -> None:
        """Test list shows the sorting problem."""
        result = invoke_cli("list")

        assert result.exit_code == 0
        assert "sorting" in result.stdout


class TestTestCommand:
    def test_python_sort_passes_every_fixture(
        self, python_sort_executable: Path, sorting_fixture_count: int
    ) -> None:
        """Test the reference Python sorter passes every fixture and the generated case."""
        result = invoke_cli("test", "sorting", str(python_sort_executable), "--random-cases", "1")

        assert result.exit_code == 0, result.stdout
        total = sorting_fixture_count
        assert (
            f"python_sort.py: {total + 1}/{total + 1} cases passed "
            f"({total}/{total} fixtures, 1/1 generated)"
        ) in result.stdout

    def test_unknown_problem_exits_with_code_2_and_names_the_registered_ones_on_standard_error(
        self, python_sort_executable: Path
    ) -> None:
        """Test an unknown problem is a usage error that lists the registered problems."""
        result = invoke_cli("test", "not-a-problem", str(python_sort_executable))

        assert_exits_with(result, 2)
        assert result.stderr.startswith("Unknown problem 'not-a-problem'. Registered problems:")
        assert "sorting" in result.stderr
        assert result.stdout == ""

    @pytest.mark.usefixtures("only_first_fixture")
    def test_malformed_output_is_reported_per_case(self, truncated_output_executable: Path) -> None:
        """Test an implementation that writes a malformed output errors every case."""
        result = invoke_cli(
            "test", "sorting", str(truncated_output_executable), "--random-cases", "1"
        )

        # Every case errors, and the CLI exits with the failure code instead of crashing.
        assert_exits_with(result, 1)
        assert "ERROR" in result.stdout
        assert "0/2 cases passed (0/1 fixtures, 0/1 generated)" in result.stdout


class TestBenchmarkCommand:
    @pytest.fixture(scope="class")
    def report(
        self,
        python_sort_executable: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> dict[str, Any]:
        """The JSON report of benchmarking the reference Python sorter with default options."""
        json_path = tmp_path_factory.mktemp("benchmark") / "report.json"
        return run_benchmark_command(python_sort_executable, json_path)

    def test_the_json_report_records_the_problem_and_the_seed(self, report: dict[str, Any]) -> None:
        """Test the JSON report names the problem and holds the seed that was given."""
        assert report["problem"] == "sorting"
        assert report["settings"]["seed"] == 42

    def test_the_json_report_has_timings_for_every_size(self, report: dict[str, Any]) -> None:
        """Test the JSON report holds the timings of two repetitions at each size."""
        implementation = report["implementations"][0]

        assert {record["size"] for record in implementation["results"]} == {100, 1000}
        for record in implementation["results"]:
            assert record["minimum_seconds"] > 0.0
            assert record["median_seconds"] > 0.0
            assert len(record["samples_seconds"]) == 2

    def test_the_json_report_identifies_the_executable_and_the_host(
        self, report: dict[str, Any], python_sort_executable: Path
    ) -> None:
        """Test the JSON report gives the path and checksum of the executable and the host."""
        implementation = report["implementations"][0]

        assert implementation["files"][0]["path"] == str(python_sort_executable.resolve())
        assert implementation["files"][0]["sha256"]
        assert report["host"]["system"]

    def test_startup_time_is_reported_and_not_subtracted_by_default(
        self, report: dict[str, Any]
    ) -> None:
        """Test the startup time is measured and left in the samples unless asked otherwise."""
        assert report["settings"]["subtract_startup_time"] is False
        implementation = report["implementations"][0]
        assert len(implementation["startup"]["samples_seconds"]) == 2
        assert implementation["startup"]["mean_seconds"] > 0.0
        for record in implementation["results"]:
            assert record["samples_seconds"] == sorted(record["raw_samples_seconds"])

    def test_subtract_startup_time_removes_startup_mean_from_each_sample(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test the subtract option takes the mean startup time off every sample."""
        report = run_benchmark_command(
            python_sort_executable, tmp_path / "report.json", "--subtract-startup-time"
        )

        assert report["settings"]["subtract_startup_time"] is True
        implementation = report["implementations"][0]
        startup_mean = implementation["startup"]["mean_seconds"]
        for record in implementation["results"]:
            expected = sorted(raw - startup_mean for raw in record["raw_samples_seconds"])
            assert record["samples_seconds"] == pytest.approx(expected)
            assert record["minimum_seconds"] == pytest.approx(min(expected))


class TestDebugFallback:
    def test_an_implementation_without_a_trace_falls_back_to_the_input_output_view(
        self, c_qsort_executable: Path
    ) -> None:
        """Test debug shows the input and output when the implementation writes no trace."""
        result = invoke_cli(
            "debug", "sorting", str(c_qsort_executable), "--size", "4", "--seed", "1"
        )

        assert result.exit_code == 0, result.stdout
        assert "did not produce a usable trace" in result.stderr
        assert "did not produce a usable trace" not in result.stdout

    def test_malformed_trace_is_reported_then_falls_back(
        self, malformed_trace_executable: Path
    ) -> None:
        """Test debug reports a malformed trace once and shows the input and output instead."""
        result = invoke_cli(
            "debug", "sorting", str(malformed_trace_executable), "--size", "4", "--seed", "1"
        )

        assert result.exit_code == 0, result.exception
        assert "Trace file is malformed" in result.stderr
        assert "did not produce a usable trace" in result.stderr
        assert result.stdout.count("Output verified.") == 1
