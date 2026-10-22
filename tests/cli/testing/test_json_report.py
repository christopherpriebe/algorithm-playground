"""Tests for the JSON report of the test command and where it is written."""

import json
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import Result

from helpers.fakes import FakeRunners
from helpers.support import (
    assert_exits_with,
    invoke_cli,
    replace_command_dependencies,
)
from helpers.two_dimensions import add_pair, register_two_dimension_problem

pytestmark = pytest.mark.integration


UseFakeTestRunners = Callable[..., FakeRunners]


LARGE_CASE = "generated:uniform:size=12:seed=5"


class ReportRun(NamedTuple):
    """The outcome of a test command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


@pytest.fixture
def nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the engine is started: the command must have stopped before that."""

    def refuse(*_arguments: object, **_keywords: object) -> None:
        message = "the test engine must not run"
        raise AssertionError(message)

    replace_command_dependencies(monkeypatch, run_tests=refuse)


@pytest.fixture(scope="module")
def explicit_cases_run(
    drops_last_executable: Path,
    python_sort_executable: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> ReportRun:
    """Run a correct and a failing sorter on a fixture and a large case, writing a report."""
    path = tmp_path_factory.mktemp("explicit") / "report.json"
    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        str(drops_last_executable),
        "--fixture",
        "single",
        "--case",
        LARGE_CASE,
        "--no-shrink",
        "--json",
        str(path),
    )
    return ReportRun(result, json.loads(path.read_text()))


def test_the_command_says_where_it_wrote_the_report(
    explicit_cases_run: ReportRun,
) -> None:
    """Test the command exits with one for a failure and names the report it wrote."""
    assert explicit_cases_run.result.exit_code == 1
    assert "Wrote test report to" in explicit_cases_run.result.stdout


def test_the_report_records_the_problem_the_settings_and_the_cases(
    explicit_cases_run: ReportRun,
) -> None:
    """Test the report names the problem, whether it passed, the settings, and the cases."""
    report = explicit_cases_run.report

    assert report["report"] == "test"
    assert report["format_version"] == 3
    assert report["problem"] == "sorting"
    assert report["passed"] is False
    assert report["settings"]["cases"] == "explicit"
    assert report["settings"]["shrink"]["enabled"] is False
    assert report["cases"] == [
        {"identifier": "fixture:single", "kind": "fixture", "fixture": "single"},
        {
            "identifier": LARGE_CASE,
            "kind": "generated",
            "distribution": "uniform",
            "size": {"size": 12},
            "seed": 5,
        },
    ]


def test_the_report_summarizes_each_implementation(
    explicit_cases_run: ReportRun, python_sort_executable: Path
) -> None:
    """Test the report gives each implementation its command, files, and summary."""
    good, bad = explicit_cases_run.report["implementations"]

    assert good["name"] == "python_sort.py"
    assert good["command"] == [str(python_sort_executable.resolve())]
    assert good["files"][0]["path"] == str(python_sort_executable.resolve())
    assert good["summary"] == {"passed": 2, "failed": 0, "errors": 0}
    assert bad["summary"] == {"passed": 1, "failed": 1, "errors": 0}


def test_the_report_lists_the_outcome_of_every_case_with_the_failure_details(
    explicit_cases_run: ReportRun,
) -> None:
    """Test the report holds an outcome per case, with the failure of the failing one."""
    _, bad = explicit_cases_run.report["implementations"]

    passing, failing = bad["outcomes"]

    assert passing["status"] == "passed"
    assert passing["failure"] is None
    assert failing["case"] == LARGE_CASE
    assert failing["status"] == "failed"
    assert set(failing["failure"]) == {"input", "expected", "actual"}
    assert failing["shrunk"] is None


def test_the_report_carries_the_host_and_metadata(
    explicit_cases_run: ReportRun,
) -> None:
    """Test the report describes the host and the run."""
    assert {"host", "metadata"} <= set(explicit_cases_run.report)


def test_a_failed_build_is_recorded(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test an implementation whose build failed is listed with the reason."""
    path = tmp_path / "report.json"
    configuration = tmp_path / "algorithm-playground.toml"
    configuration.write_text(
        "[[implementations]]\n"
        'name = "unbuildable"\n'
        'problem = "sorting"\n'
        f"command = {json.dumps([sys.executable, str(python_sort_executable)])}\n"
        f"build_command = {json.dumps([sys.executable, '-c', 'raise SystemExit(1)'])}\n"
    )

    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "unbuildable",
        "--configuration",
        str(configuration),
        "--fixture",
        "single",
        "--json",
        str(path),
    )

    assert result.exit_code == 1
    report = json.loads(path.read_text())
    assert report["passed"] is False
    assert [item["name"] for item in report["implementations"]] == [
        "python_sort.py",
        "unbuildable",
    ]
    assert "exited with code 1" in report["implementations"][1]["build_failure"]


def test_planned_cases_are_recorded_with_the_settings_that_produced_them(
    use_fake_test_runners: UseFakeTestRunners,
    tmp_path: Path,
) -> None:
    """Test the report of planned cases records the options that planned them."""
    use_fake_test_runners({"sorter": sorted})
    path = tmp_path / "planned.json"

    result = invoke_cli(
        *["test", "sorting", "--command", "sorter"],
        *[
            "--random-cases",
            "2",
            "--maximum-size",
            "6",
            "--seed",
            "3",
            "--no-fixtures",
        ],
        *["--distribution", "sorted", "--timeout", "30", "--json", str(path)],
    )

    assert result.exit_code == 0, result.stdout
    settings = json.loads(path.read_text())["settings"]
    assert settings == {
        "cases": "planned",
        "seed": 3,
        "random_cases": 2,
        "maximum_size": {"size": 6},
        "distributions": ["sorted"],
        "include_fixtures": False,
        "shrink": {
            "enabled": True,
            "maximum_shrunk_cases": 3,
            "maximum_runs": 200,
            "time_budget_seconds": 30.0,
        },
        "timeout_seconds": 30.0,
    }


@pytest.fixture
def locked_directory(tmp_path: Path) -> Iterator[Path]:
    """A directory that cannot be written to; its permissions are restored afterwards."""
    directory = tmp_path / "locked"
    directory.mkdir()
    directory.chmod(0o500)
    yield directory
    directory.chmod(0o700)


@pytest.mark.usefixtures("nothing_runs")
def test_a_directory_is_refused_before_anything_runs(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a directory given as the report path is a usage error and nothing runs."""
    result = invoke_cli(
        "test", "sorting", str(python_sort_executable), "--json", str(tmp_path)
    )

    assert_exits_with(result, 2)
    assert "is a directory" in result.stderr
    assert result.stdout == ""


@pytest.mark.usefixtures("nothing_runs")
def test_a_parent_that_is_a_file_is_refused_before_anything_runs(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a report path below a file is a usage error and nothing runs."""
    blocker = tmp_path / "blocker"
    blocker.write_text("")

    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--json",
        str(blocker / "sub" / "r.json"),
    )

    assert_exits_with(result, 2)
    assert "is not a directory" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="the superuser can write anywhere")
@pytest.mark.usefixtures("nothing_runs")
def test_a_directory_that_cannot_be_written_is_refused_before_anything_runs(
    python_sort_executable: Path, locked_directory: Path
) -> None:
    """Test a report path in a directory without write permission is a usage error."""
    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--json",
        str(locked_directory / "r.json"),
    )

    assert_exits_with(result, 2)
    assert "permission denied" in result.stderr


def test_missing_directories_are_created(
    use_fake_test_runners: UseFakeTestRunners,
    tmp_path: Path,
) -> None:
    """Test the directories above the report path are created when they are missing."""
    use_fake_test_runners({"sorter": sorted})
    path = tmp_path / "a" / "b" / "report.json"

    result = invoke_cli(
        *["test", "sorting", "--command", "sorter", "--fixture", "single"],
        *["--json", str(path)],
    )

    assert result.exit_code == 0, result.stdout
    assert json.loads(path.read_text())["problem"] == "sorting"


def test_a_failure_while_writing_is_a_usage_error_not_a_traceback(
    use_fake_test_runners: UseFakeTestRunners,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a report that cannot be written is reported as an error after the results."""
    use_fake_test_runners({"sorter": sorted})

    def refuse(_self: Path, *_arguments: object, **_keywords: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", refuse)

    result = invoke_cli(
        *["test", "sorting", "--command", "sorter", "--fixture", "single"],
        *["--json", str(tmp_path / "full.json")],
    )

    assert_exits_with(result, 2)
    assert "Could not write the test report to" in result.stderr
    assert "No space left on device" in result.stderr
    assert "sorter: 1/1 cases passed" in result.stdout


def test_a_maximum_size_names_every_dimension(
    use_fake_test_runners: UseFakeTestRunners, tmp_path: Path
) -> None:
    """Test the maximum size of a problem with two dimensions caps each of them."""
    use_fake_test_runners({"adder": add_pair})
    name = register_two_dimension_problem()
    path = tmp_path / "pairs.json"

    result = invoke_cli(
        *["test", name, "--command", "adder", "--random-cases", "6", "--no-fixtures"],
        *["--maximum-size", "vertices=3:edges=4", "--json", str(path)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads(path.read_text())
    assert report["settings"]["maximum_size"] == {"vertices": 3, "edges": 4}
    assert report["dimensions"] == [
        {"name": "vertices", "minimum": 1},
        {"name": "edges", "minimum": 0},
    ]
    sizes = [case["size"] for case in report["cases"]]
    assert len(sizes) == 6
    assert all(1 <= size["vertices"] <= 3 and 0 <= size["edges"] <= 4 for size in sizes)
