"""Tests for running the benchmark command, its sizes, and its failures."""

import json
import shlex
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import Result

from helpers.executables import write_sorter
from helpers.fakes import FakeRunners
from helpers.misbehaving import count_distinct_values
from helpers.registration import register_faulty_problem
from helpers.support import (
    assert_exits_with,
    invoke_cli,
    parse_table_rows,
)
from helpers.two_dimensions import add_pair, register_two_dimension_problem

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


BENCHMARK_OPTIONS = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0"]


class BenchmarkRun(NamedTuple):
    """The outcome of a benchmark command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


def build_python_command_text(script: Path) -> str:
    """Build the text of a command line that runs a script with the current interpreter."""
    return shlex.join([sys.executable, str(script)])


UseFakeRunners = Callable[..., FakeRunners]


GENERATORS_MESSAGE = (
    "The problem's generators hook raised RuntimeError: generators exploded."
)


GENERATOR_MESSAGE = (
    "The problem's 'broken' generator hook raised RuntimeError: generator exploded."
)


class FakeBenchmarkRun(NamedTuple):
    """The outcome of a benchmark command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]
    runners: FakeRunners


def assert_hook_failure(result: Result, message: str) -> None:
    """Assert the command exited with code 1 and the message, without a traceback."""
    assert_exits_with(result, 1)
    output = f"{result.stdout}{result.stderr}"
    assert message in output
    assert "Traceback" not in output


@pytest.fixture(scope="module")
def report(
    python_sort_executable: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """The JSON report of benchmarking the reference Python sorter with default options."""
    json_path = tmp_path_factory.mktemp("benchmark") / "report.json"
    return run_benchmark_command(python_sort_executable, json_path)


def test_the_json_report_records_the_problem_and_the_seed(
    report: dict[str, Any],
) -> None:
    """Test the JSON report names the problem and holds the seed that was given."""
    assert report["problem"] == "sorting"
    assert report["settings"]["seed"] == 42


def test_the_json_report_has_timings_for_every_size(report: dict[str, Any]) -> None:
    """Test the JSON report holds the timings of two repetitions at each size."""
    implementation = report["implementations"][0]

    assert sorted(record["size"]["size"] for record in implementation["results"]) == [
        100,
        1000,
    ]
    for record in implementation["results"]:
        assert record["minimum_seconds"] > 0.0
        assert record["median_seconds"] > 0.0
        assert len(record["samples_seconds"]) == 2


def test_the_json_report_identifies_the_executable_and_the_host(
    report: dict[str, Any], python_sort_executable: Path
) -> None:
    """Test the JSON report gives the path and checksum of the executable and the host."""
    implementation = report["implementations"][0]

    assert implementation["files"][0]["path"] == str(python_sort_executable.resolve())
    assert implementation["files"][0]["sha256"]
    assert report["host"]["system"]


def test_startup_time_is_reported_and_not_subtracted_by_default(
    report: dict[str, Any],
) -> None:
    """Test the startup time is measured and left in the samples unless asked otherwise."""
    assert report["settings"]["subtract_startup_time"] is False
    implementation = report["implementations"][0]
    assert len(implementation["startup"]["samples_seconds"]) == 2
    assert implementation["startup"]["mean_seconds"] > 0.0
    for record in implementation["results"]:
        assert record["samples_seconds"] == sorted(record["raw_samples_seconds"])


def test_subtract_startup_time_removes_startup_mean_from_each_sample(
    python_sort_executable: Path, tmp_path: Path
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


@pytest.fixture(scope="module")
def plain_script(
    python_sort_executable: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """A copy of the reference sorter without the executable bit."""
    script = tmp_path_factory.mktemp("plain") / "plain sort.py"
    shutil.copyfile(python_sort_executable, script)
    return script


@pytest.fixture(scope="module")
def comparison(
    python_sort_executable: Path,
    plain_script: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> BenchmarkRun:
    """Benchmark the reference sorter against a copy of it, writing a JSON report."""
    json_path = tmp_path_factory.mktemp("comparison") / "report.json"
    result = invoke_cli(
        "benchmark",
        "sorting",
        str(python_sort_executable),
        "--command",
        build_python_command_text(plain_script),
        *BENCHMARK_OPTIONS,
        "--json",
        str(json_path),
    )
    return BenchmarkRun(result, json.loads(json_path.read_text()))


@pytest.fixture(scope="module")
def failing_run(
    python_sort_executable: Path,
    crashing_executable: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> BenchmarkRun:
    """Benchmark a working sorter next to one that crashes, writing a JSON report."""
    json_path = tmp_path_factory.mktemp("failing") / "report.json"
    result = invoke_cli(
        "benchmark",
        "sorting",
        str(python_sort_executable),
        str(crashing_executable),
        *BENCHMARK_OPTIONS,
        "--no-plot",
        "--json",
        str(json_path),
    )
    return BenchmarkRun(result, json.loads(json_path.read_text()))


def test_compared_implementations_show_ratios_and_the_startup_row(
    comparison: BenchmarkRun,
) -> None:
    """Test the table of two implementations has a startup row and ratios to the first."""
    assert comparison.result.exit_code == 0, comparison.result.stdout
    assert "(1.00x)" in comparison.result.stdout
    assert "startup" in comparison.result.stdout


def test_the_json_report_names_the_problem_the_settings_and_the_host(
    comparison: BenchmarkRun,
) -> None:
    """Test the JSON report records the problem, the sizes, and the host."""
    report = comparison.report

    assert report["report"] == "benchmark"
    assert report["problem"] == "sorting"
    assert report["settings"]["sizes"] == [{"size": 4}, {"size": 8}]
    assert report["host"]["system"]


def test_the_json_report_describes_each_compared_implementation(
    comparison: BenchmarkRun, python_sort_executable: Path, plain_script: Path
) -> None:
    """Test the JSON report records the name, command, and files of each implementation."""
    first, second = comparison.report["implementations"]

    assert first["name"] == "python_sort.py"
    assert first["failures"] == []
    assert first["command"] == [str(python_sort_executable.resolve())]
    assert first["files"][0]["sha256"]
    assert second["name"] == "plain sort"
    assert second["command"] == [sys.executable, str(plain_script)]
    assert str(plain_script.resolve()) in {file["path"] for file in second["files"]}


def test_the_json_report_holds_one_sample_per_run_of_each_implementation(
    comparison: BenchmarkRun,
) -> None:
    """Test every implementation has one startup sample and one sample per size."""
    for implementation in comparison.report["implementations"]:
        assert len(implementation["startup"]["samples_seconds"]) == 1
        assert [record["size"] for record in implementation["results"]] == [
            {"size": 4},
            {"size": 8},
        ]
        for record in implementation["results"]:
            assert len(record["samples_seconds"]) == 1
            assert len(record["raw_samples_seconds"]) == 1


def test_a_failing_implementation_is_reported_while_the_others_finish(
    failing_run: BenchmarkRun,
) -> None:
    """Test a crashing implementation is named in the output and the command exits with one."""
    assert_exits_with(failing_run.result, 1)
    assert "failed" in failing_run.result.stdout
    assert "crashing.py failed:" in failing_run.result.stdout
    assert "kaboom" in failing_run.result.stdout


def test_the_json_report_records_the_failure_next_to_the_finished_results(
    failing_run: BenchmarkRun,
) -> None:
    """Test the report keeps the results of the working implementation and the failure."""
    good, bad = failing_run.report["implementations"]

    assert good["failures"] == []
    assert len(good["results"]) == 2
    assert [failure["stage"] for failure in bad["failures"]] == ["startup"]
    assert "kaboom" in bad["failures"][0]["message"]
    assert bad["results"] == []


def test_unknown_reference_exits_with_code_2_before_running(
    python_sort_executable: Path,
) -> None:
    """Test an unknown reference is a usage error and nothing is benchmarked."""
    result = invoke_cli(
        "benchmark",
        "sorting",
        str(python_sort_executable),
        *BENCHMARK_OPTIONS,
        "--reference",
        "nope",
    )

    assert_exits_with(result, 2)
    assert "Unknown reference 'nope'" in result.stderr
    assert result.stdout == ""


ARGUMENTS = ("--sizes", "3,6", "--repetitions", "1", "--warmup", "0", "--no-plot")


@pytest.fixture
def broken_distribution_run(
    use_fake_runners: UseFakeRunners, tmp_path: Path
) -> FakeBenchmarkRun:
    """Benchmark two implementations on a working and a broken distribution; write a report."""
    runners = use_fake_runners(
        {"first": count_distinct_values, "second": count_distinct_values}
    )
    name = register_faulty_problem("generator")
    json_path = tmp_path / "report.json"
    result = invoke_cli(
        *["benchmark", name, "--command", "first", "--command", "second"],
        *["--distribution", "uniform", "--distribution", "broken"],
        *ARGUMENTS,
        *["--json", str(json_path)],
    )
    return FakeBenchmarkRun(result, json.loads(json_path.read_text()), runners)


@pytest.fixture
def untraced_run(use_fake_runners: UseFakeRunners, tmp_path: Path) -> FakeBenchmarkRun:
    """Benchmark with operation counting a problem that has no trace format; write a report."""
    runners = use_fake_runners({"counter": count_distinct_values})
    name = register_faulty_problem("")
    json_path = tmp_path / "report.json"
    result = invoke_cli(
        *["benchmark", name, "--command", "counter", "--count-operations"],
        *ARGUMENTS,
        *["--json", str(json_path)],
    )
    return FakeBenchmarkRun(result, json.loads(json_path.read_text()), runners)


def test_a_generators_hook_that_raises_ends_the_command_before_anything_runs(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a generators hook that raises stops the benchmark before any implementation runs."""
    runners = use_fake_runners({"counter": count_distinct_values})
    name = register_faulty_problem("generators")

    result = invoke_cli("benchmark", name, "--command", "counter", *ARGUMENTS)

    assert_hook_failure(result, GENERATORS_MESSAGE)
    assert runners.calls == []


def test_a_generator_that_raises_is_reported_once_with_its_distribution(
    broken_distribution_run: FakeBenchmarkRun,
) -> None:
    """Test a generator that raises is explained once, without a traceback."""
    result = broken_distribution_run.result

    assert_exits_with(result, 1)
    message = "Could not generate the input size=3 for the distribution 'broken'"
    assert result.stdout.count(message) == 1
    assert GENERATOR_MESSAGE in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_a_generator_that_raises_fails_its_distribution_for_every_implementation(
    broken_distribution_run: FakeBenchmarkRun,
) -> None:
    """Test every size of the broken distribution is failed and the other one is not."""
    rows = parse_table_rows(broken_distribution_run.result.stdout)

    labels = [row[0] for row in rows]
    broken_rows = rows[labels.index("broken") + 1 :]
    assert [row[0] for row in broken_rows] == ["3", "6"]
    assert all(row[1:] == ["failed", "failed"] for row in broken_rows)
    uniform_rows = rows[labels.index("uniform") + 1 : labels.index("broken")]
    assert [row[0] for row in uniform_rows[:2]] == ["3", "6"]
    assert all("failed" not in cell for row in uniform_rows for cell in row)


def test_a_generator_that_raises_is_recorded_as_a_distribution_failure_in_the_json_report(
    broken_distribution_run: FakeBenchmarkRun,
) -> None:
    """Test the report records the broken distribution as a failure of every implementation."""
    report = broken_distribution_run.report

    assert report["format_version"] == 7
    for implementation in report["implementations"]:
        (failure,) = implementation["failures"]
        assert (failure["stage"], failure["distribution"], failure["size"]) == (
            "distribution",
            "broken",
            None,
        )
        assert GENERATOR_MESSAGE in failure["message"]
        assert [item["distribution"] for item in implementation["results"]] == [
            "uniform",
            "uniform",
        ]
        assert implementation["startup"] is not None


def test_a_problem_without_a_trace_format_says_so_when_asked_to_count_operations(
    untraced_run: FakeBenchmarkRun,
) -> None:
    """Test counting operations for a problem without a trace format is ignored with a notice."""
    result = untraced_run.result

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "does not define operation counts" in result.stderr
    assert "no trace format" in result.stderr


def test_a_problem_without_a_trace_format_runs_no_traced_run(
    untraced_run: FakeBenchmarkRun,
) -> None:
    """Test no traced run is made and no operation table or hint is printed."""
    assert untraced_run.runners.traced_calls == []
    assert (
        "No implementation reported operation counts" not in untraced_run.result.stdout
    )
    assert "write the problem's trace format" not in untraced_run.result.stdout


def test_a_problem_without_a_trace_format_records_that_nothing_was_counted(
    untraced_run: FakeBenchmarkRun,
) -> None:
    """Test the JSON report records operation counting as off."""
    assert untraced_run.report["settings"]["count_operations"] is False


def test_duplicate_sizes_are_a_usage_error(python_sort_executable: Path) -> None:
    """Test sizes that repeat are a usage error naming the repeated size."""
    result = invoke_cli(
        "benchmark",
        "sorting",
        str(python_sort_executable),
        "--sizes",
        "4,8,4",
        "--no-plot",
    )

    assert result.exit_code == 2
    assert "Sizes must be unique" in result.stderr
    assert "repeated: size=4" in result.stderr


def test_sizes_that_differ_only_in_notation_are_still_duplicates(
    python_sort_executable: Path,
) -> None:
    """Test sizes that have the same value are duplicates however they are written."""
    result = invoke_cli(
        "benchmark", "sorting", str(python_sort_executable), "--sizes", "1_000,1000"
    )

    assert_exits_with(result, 2)
    assert "repeated: size=1000" in result.stderr


def test_completed_rows_are_printed_before_the_failure(tmp_path: Path) -> None:
    """Test the rows measured before a failure are printed and the failure comes after."""
    flaky = write_sorter(tmp_path / "flaky.py", fail_above=10)

    result = invoke_cli(
        "benchmark",
        "sorting",
        str(flaky),
        "--sizes",
        "4,50,60",
        "--repetitions",
        "1",
        "--warmup",
        "0",
        "--no-plot",
    )

    assert_exits_with(result, 1)
    output = result.stdout
    assert "startup" in output
    rows = [line for line in output.splitlines() if line.startswith("│")]
    assert len(rows) == 2, output
    assert rows[1].split("│")[1].strip() == "4"
    assert output.index("startup") < output.index("flaky.py failed:")
    assert "Run failed for size=50" in output


def test_a_failure_during_startup_prints_only_the_failure(
    crashing_executable: Path,
) -> None:
    """Test an implementation that fails at startup gets no table, only the failure."""
    result = invoke_cli(
        "benchmark",
        "sorting",
        str(crashing_executable),
        "--sizes",
        "4",
        "--no-plot",
    )

    assert result.exit_code == 1
    assert "benchmark — sorting" not in result.stdout
    assert "crashing.py failed:" in result.stdout


def test_sizes_with_several_dimensions_label_the_rows_and_the_report(
    use_fake_runners: UseFakeRunners, tmp_path: Path
) -> None:
    """Test a size with two dimensions names both in the table and in the JSON report."""
    use_fake_runners({"adder": add_pair})
    name = register_two_dimension_problem()
    json_path = tmp_path / "report.json"

    result = invoke_cli(
        *["benchmark", name, "--command", "adder"],
        *["--sizes", "vertices=2:edges=3,vertices=4:edges=6"],
        *["--repetitions", "1", "--warmup", "0", "--no-plot"],
        *["--json", str(json_path)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [row[0] for row in parse_table_rows(result.stdout)] == [
        "startup",
        "vertices=2 edges=3",
        "vertices=4 edges=6",
    ]
    report = json.loads(json_path.read_text())
    assert report["settings"]["sizes"] == [
        {"vertices": 2, "edges": 3},
        {"vertices": 4, "edges": 6},
    ]
    assert report["dimensions"] == [
        {"name": "vertices", "minimum": 1},
        {"name": "edges", "minimum": 0},
    ]
    assert report["growth_dimension"] == "edges"


def test_a_plain_number_is_a_usage_error_for_a_problem_with_several_dimensions(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a bare number is refused for two dimensions, naming the form to use, before anything runs."""
    runners = use_fake_runners({"adder": add_pair})
    name = register_two_dimension_problem()

    result = invoke_cli(
        "benchmark", name, "--command", "adder", "--sizes", "4", "--no-plot"
    )

    assert_exits_with(result, 2)
    assert "vertices=N:edges=N" in result.stderr
    assert runners.calls == []


def test_a_size_below_the_minimum_of_a_dimension_is_a_usage_error(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a size below the minimum of a dimension is refused with the dimension named."""
    use_fake_runners({"adder": add_pair})
    name = register_two_dimension_problem()

    result = invoke_cli(
        *["benchmark", name, "--command", "adder"],
        *["--sizes", "vertices=0:edges=3", "--no-plot"],
    )

    assert_exits_with(result, 2)
    assert "'vertices' of at least 1" in result.stderr


def test_a_size_with_leading_zeros_is_a_usage_error(
    python_sort_executable: Path,
) -> None:
    """Test a size that is not a plainly written integer is a usage error before anything runs."""
    result = invoke_cli(
        "benchmark",
        "sorting",
        str(python_sort_executable),
        "--sizes",
        "0100",
        "--no-plot",
    )

    assert_exits_with(result, 2)
    assert "plain integer" in result.stderr
    assert result.stdout == ""
