"""Tests for how implementations named on the command line are told apart."""

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from helpers.executables import (
    INSTRUMENTED_SORT,
)
from helpers.fakes import FakeRunners, sort_correctly
from helpers.support import (
    assert_exits_with,
    find_table_header,
    invoke_cli,
)

pytestmark = pytest.mark.integration


SMALL = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0", "--no-plot"]


def build_instrumented_command(algorithm: str) -> str:
    """Build the command line that runs an instrumented sorter of the given algorithm."""
    return shlex.join([sys.executable, str(INSTRUMENTED_SORT), algorithm])


def test_two_commands_running_one_script_are_told_apart_by_their_arguments() -> None:
    """Test commands that run the same script are named after their arguments too."""
    result = invoke_cli(
        "benchmark",
        "sorting",
        *[
            "--command",
            build_instrumented_command("insertion"),
            "--command",
            build_instrumented_command("merge"),
        ],
        *SMALL,
    )

    assert result.exit_code == 0, result.stdout
    header = find_table_header(result.stdout)
    assert "instrumented_sort insertion" in header
    assert "instrumented_sort merge" in header


def test_a_name_replaces_the_default_name_of_the_command_in_its_position(
    use_fake_test_runners: Callable[..., FakeRunners],
) -> None:
    """Test a name given with the name option replaces the default name of its command."""
    use_fake_test_runners({"quick": sort_correctly, "second": sort_correctly})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "first",
        "--command",
        "second",
        "--name",
        "quick",
        "--fixture",
        "empty",
    )

    assert result.exit_code == 0, result.stdout
    assert "quick: 1/1 cases passed" in result.stdout
    assert "second: 1/1 cases passed" in result.stdout


def test_names_pair_with_commands_in_order_in_every_command(tmp_path: Path) -> None:
    """Test names are matched to commands in the order they are given, in the report."""
    report = tmp_path / "report.json"

    result = invoke_cli(
        "benchmark",
        "sorting",
        *[
            "--command",
            build_instrumented_command("insertion"),
            "--command",
            build_instrumented_command("merge"),
        ],
        *["--name", "slow", "--name", "fast"],
        *SMALL,
        "--json",
        str(report),
    )

    assert result.exit_code == 0, result.stdout
    names = [item["name"] for item in json.loads(report.read_text())["implementations"]]
    assert names == ["slow", "fast"]


def test_debug_accepts_a_name() -> None:
    """Test the debug command accepts the name option."""
    result = invoke_cli(
        "debug",
        "sorting",
        "--command",
        build_instrumented_command("insertion"),
        "--name",
        "mine",
        "--size",
        "4",
    )

    assert result.exit_code == 0, result.stderr


def test_more_names_than_commands_are_a_usage_error() -> None:
    """Test giving more names than commands is a usage error."""
    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "node first.js",
        "--name",
        "first",
        "--name",
        "second",
    )

    assert_exits_with(result, 2)
    assert (
        "--name was given 2 times, but there are only 1 --command values"
        in result.stderr
    )
    assert result.stdout == ""


def test_a_name_without_a_command_is_a_usage_error(
    python_sort_executable: Path,
) -> None:
    """Test a name given without any command is a usage error."""
    result = invoke_cli(
        "test", "sorting", str(python_sort_executable), "--name", "first"
    )

    assert_exits_with(result, 2)
    assert (
        "--name was given 1 times, but there are only 0 --command values"
        in result.stderr
    )


def test_the_same_name_twice_is_a_usage_error() -> None:
    """Test two commands cannot be given the same name."""
    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "node first.js",
        "--command",
        "node second.js",
        "--name",
        "same",
        "--name",
        "same",
    )

    assert_exits_with(result, 2)
    assert "'same'" in result.stderr
