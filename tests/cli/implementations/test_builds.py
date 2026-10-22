"""Tests for build commands and how a failed build is isolated."""

import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import Result

from helpers.executables import (
    write_sorter,
)
from helpers.support import (
    Configure,
    assert_exits_with,
    find_table_header,
    invoke_cli,
    parse_table_rows,
)

pytestmark = pytest.mark.integration


BENCHMARK_OPTIONS = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0"]


BUILD_MARKER = "open('built.marker', 'w').write('built')"


FAILING_BUILD = (
    sys.executable,
    "-c",
    "import sys; print('compile exploded', file=sys.stderr); sys.exit(1)",
)


BUILD_OUTPUT = "standard error:\ncompile exploded"


RATIO = re.compile(r"\((\d+\.\d+)x\)")


class BenchmarkRun(NamedTuple):
    """The outcome of a benchmark command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


def format_toml_list(*items: str) -> str:
    """Format the items as a TOML array of strings."""
    return json.dumps(list(items))


def build_configured_entry(
    name: str,
    script: Path,
    *,
    build_command: tuple[str, ...] | None = None,
    problem: str = "sorting",
    extra_lines: tuple[str, ...] = (),
) -> str:
    """Build the text of one ``[[implementations]]`` entry that runs a Python script.

    Args:
        name: The name of the implementation.
        script: The Python script the implementation runs.
        build_command: The build command, if the implementation has one.
        problem: The name of the problem the implementation solves.
        extra_lines: Further lines to add to the entry.

    Returns:
        The entry, ending in a newline.
    """
    lines = [
        "[[implementations]]",
        f"name = {json.dumps(name)}",
        f'problem = "{problem}"',
        f"command = {format_toml_list(sys.executable, str(script))}",
    ]
    if build_command is not None:
        lines.append(f"build_command = {format_toml_list(*build_command)}")
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


@pytest.fixture
def built_sorter(configure: Configure, python_sort_executable: Path) -> Path:
    """Configure a sorter whose build command writes a marker file; return the marker."""
    path = configure(
        build_configured_entry(
            "built-sorter",
            python_sort_executable,
            build_command=(sys.executable, "-c", BUILD_MARKER),
        ),
    )
    return path.parent / "built.marker"


def test_the_build_command_runs_in_the_configuration_directory_before_the_run(
    built_sorter: Path,
) -> None:
    """Test the build command runs once, in the configuration directory, before the run."""
    result = invoke_cli("debug", "sorting", "--size", "4")

    assert result.exit_code == 0, result.stdout
    assert "Building built-sorter" in result.stderr
    assert built_sorter.read_text() == "built"


def test_no_build_skips_the_build_command(built_sorter: Path) -> None:
    """Test the no-build option runs the implementation without building it."""
    result = invoke_cli("debug", "sorting", "--size", "4", "--no-build")

    assert result.exit_code == 0, result.stdout
    assert "Building" not in result.stderr
    assert not built_sorter.exists()


def test_a_failing_build_exits_with_one_and_shows_its_output(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test a build that fails ends the command with exit code 1 and its output."""
    configure(
        build_configured_entry(
            "broken-build", python_sort_executable, build_command=FAILING_BUILD
        )
    )

    result = invoke_cli("debug", "sorting", "--size", "4")

    assert_exits_with(result, 1)
    assert "Building broken-build" in result.stderr
    assert result.stderr.count(BUILD_OUTPUT) == 1
    assert "No implementation could be built" in result.stderr
    assert "Output verified" not in result.stdout


@pytest.fixture
def run_log(tmp_path: Path) -> Path:
    """The file in which the sorters log their runs."""
    return tmp_path / "runs.log"


@pytest.fixture
def mixed_builds(configure: Configure, tmp_path: Path, run_log: Path) -> None:
    """A sorter that builds and runs, and one whose build fails (and must never run)."""
    good = write_sorter(tmp_path / "good.py", log_path=run_log, label="good")
    bad = write_sorter(tmp_path / "bad.py", log_path=run_log, label="bad")
    configure(
        build_configured_entry("good", good),
        build_configured_entry("bad", bad, build_command=FAILING_BUILD),
    )


@pytest.fixture
def benchmark_run(
    mixed_builds: None,  # noqa: ARG001  requested for its side effect of writing the configuration
    tmp_path: Path,
) -> BenchmarkRun:
    """Benchmark the mixed builds, writing a JSON report."""
    json_path = tmp_path / "report.json"
    result = invoke_cli(
        "benchmark",
        "sorting",
        *BENCHMARK_OPTIONS,
        "--no-plot",
        "--json",
        str(json_path),
    )
    return BenchmarkRun(result, json.loads(json_path.read_text()))


@pytest.mark.usefixtures("mixed_builds", "only_first_fixture")
def test_the_failed_build_is_marked_in_the_matrix_and_the_other_implementation_runs(
    run_log: Path,
) -> None:
    """Test the matrix marks the failed build and the other implementation still runs."""
    result = invoke_cli("test", "sorting")

    assert_exits_with(result, 1)
    header = find_table_header(result.stdout)
    assert header.index("good") < header.index("bad")
    assert parse_table_rows(result.stdout) == [["fixtures", "1/1", "build failed"]]
    assert "good: 1/1 cases passed" in result.stdout
    assert "bad: build failed, not run" in result.stdout
    assert set(run_log.read_text().split()) == {"good"}


@pytest.mark.usefixtures("mixed_builds", "only_first_fixture")
def test_the_build_output_is_printed_once_on_standard_error() -> None:
    """Test the output of a failed build is printed once, on standard error only."""
    result = invoke_cli("test", "sorting")

    assert "Building bad" in result.stderr
    assert "Building good" not in result.stderr
    assert result.stderr.count(BUILD_OUTPUT) == 1
    assert BUILD_OUTPUT not in result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_a_failed_build_does_not_stop_later_builds(
    configure: Configure,
    python_sort_executable: Path,
    tmp_path: Path,
) -> None:
    """Test the implementations after one whose build failed are still built and run."""
    configure(
        build_configured_entry(
            "bad", python_sort_executable, build_command=FAILING_BUILD
        ),
        build_configured_entry(
            "good",
            python_sort_executable,
            build_command=(sys.executable, "-c", BUILD_MARKER),
        ),
    )

    result = invoke_cli("test", "sorting")

    assert result.exit_code == 1
    assert (tmp_path / "built.marker").read_text() == "built"
    assert "good: 1/1 cases passed" in result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_when_nothing_builds_nothing_runs(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test no case is run when no implementation could be built."""
    configure(
        build_configured_entry(
            "bad", python_sort_executable, build_command=FAILING_BUILD
        )
    )

    result = invoke_cli("test", "sorting")

    assert_exits_with(result, 1)
    assert result.stdout == ""
    assert result.stderr.count(BUILD_OUTPUT) == 1
    assert "No implementation could be built, so nothing was run." in result.stderr


def test_benchmark_shows_the_failed_build_as_a_failed_implementation(
    benchmark_run: BenchmarkRun, run_log: Path
) -> None:
    """Test the benchmark table shows the failed build as failed and runs the other one."""
    result = benchmark_run.result

    assert_exits_with(result, 1)
    rows = parse_table_rows(result.stdout)
    assert [row[0] for row in rows] == ["startup", "4", "8"]
    assert all(row[2] == "failed" for row in rows)
    assert all("failed" not in row[1] and "skipped" not in row[1] for row in rows)
    assert result.stderr.count(BUILD_OUTPUT) == 1
    assert BUILD_OUTPUT not in result.stdout
    assert set(run_log.read_text().split()) == {"good"}


def test_benchmark_records_the_failed_build_in_the_json_report(
    benchmark_run: BenchmarkRun,
) -> None:
    """Test the JSON report has the results of the built sorter and the build failure."""
    good, bad = benchmark_run.report["implementations"]

    assert (good["name"], good["failures"]) == ("good", [])
    assert [record["size"] for record in good["results"]] == [4, 8]
    assert bad["name"] == "bad"
    assert [failure["stage"] for failure in bad["failures"]] == ["build"]
    assert "compile exploded" in bad["failures"][0]["message"]
    assert bad["startup"] is None
    assert bad["results"] == []


def test_benchmark_runs_nothing_when_no_implementation_builds(
    configure: Configure, python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test the benchmark runs and reports nothing when no implementation could be built."""
    configure(
        build_configured_entry(
            "bad", python_sort_executable, build_command=FAILING_BUILD
        )
    )
    json_path = tmp_path / "report.json"

    result = invoke_cli(
        "benchmark", "sorting", *BENCHMARK_OPTIONS, "--json", str(json_path)
    )

    assert_exits_with(result, 1)
    assert result.stdout == ""
    assert "No implementation could be built" in result.stderr
    assert not json_path.exists()


def test_a_reference_whose_build_failed_leaves_the_other_cells_without_ratios(
    configure: Configure,
    python_sort_executable: Path,
) -> None:
    """Test no ratios are shown when the reference is an implementation that failed to build."""
    configure(
        build_configured_entry(
            "bad", python_sort_executable, build_command=FAILING_BUILD
        ),
        build_configured_entry("good", python_sort_executable),
    )

    result = invoke_cli(
        "benchmark",
        "sorting",
        *BENCHMARK_OPTIONS,
        "--no-plot",
        "--reference",
        "bad",
    )

    assert result.exit_code == 1, result.stdout
    assert "ratio to bad" in result.stdout
    rows = parse_table_rows(result.stdout)
    assert all(row[1] == "failed" for row in rows)
    assert all("x)" not in row[2] for row in rows)


def test_the_default_reference_is_the_first_implementation_that_is_ready(
    configure: Configure,
    python_sort_executable: Path,
) -> None:
    """Test ratios are taken to the first implementation that built when none is chosen."""
    configure(
        build_configured_entry(
            "bad", python_sort_executable, build_command=FAILING_BUILD
        ),
        build_configured_entry("good", python_sort_executable),
        build_configured_entry("also-good", python_sort_executable),
    )

    result = invoke_cli("benchmark", "sorting", *BENCHMARK_OPTIONS, "--no-plot")

    assert result.exit_code == 1, result.stdout
    assert "ratio to good" in result.stdout
    assert "ratio to bad" not in result.stdout
    rows = parse_table_rows(result.stdout)
    assert any(RATIO.search(row[3]) for row in rows)
