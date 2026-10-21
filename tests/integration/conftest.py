"""Shared fixtures for the end-to-end CLI tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeRunners
from support import WriteExecutable
from typer.testing import CliRunner, Result

from algorithm_playground.cli import benchmark_command, context, test_command
from algorithm_playground.cli.main import app
from algorithm_playground.core.configuration import DEFAULT_CONFIGURATION_FILE_NAME


@pytest.fixture(scope="session")
def invoke() -> Callable[..., Result]:
    """Invoke the CLI in-process with the given arguments and return Click's result."""
    runner = CliRunner()

    def run(*arguments: str) -> Result:
        return runner.invoke(app, list(arguments))

    return run


@pytest.fixture
def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Write the default configuration file from entries and make its directory current."""

    def write(*entries: str) -> Path:
        path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
        path.write_text("\n".join(entries))
        monkeypatch.chdir(tmp_path)
        return path

    return write


@pytest.fixture(scope="session")
def table_rows() -> Callable[[str], list[list[str]]]:
    """Split the body rows of the rendered tables in some output into stripped cells."""

    def rows(output: str) -> list[list[str]]:
        return [
            [cell.strip() for cell in line.strip().strip("│").split("│")]
            for line in output.splitlines()
            if line.startswith("│")
        ]

    return rows


@pytest.fixture
def use_fake_runners(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeRunners]:
    """Make ``benchmark`` run implementations through in-process fakes with set durations.

    Implementations are then named on the command line with ``--command NAME``;
    the commands are never run, nor checked for existing. Returns the factory so a test can inspect the calls.
    """

    def install(
        behaviors: Mapping[str, Callable[[Any], Any]],
        durations: Mapping[str, float | Callable[[Any], float]] | None = None,
        traces: Mapping[str, Callable[[Any], Any]] | None = None,
        traced_behaviors: Mapping[str, Callable[[Any], Any]] | None = None,
    ) -> FakeRunners:
        runners = FakeRunners(behaviors, durations, traces, traced_behaviors)
        monkeypatch.setattr(context, "check_can_start", lambda implementation: None)
        real_run_benchmark = benchmark_command.run_benchmark

        def run(*arguments: Any, **keywords: Any) -> Any:
            return real_run_benchmark(*arguments, runner_factory=runners, **keywords)

        monkeypatch.setattr(benchmark_command, "run_benchmark", run)
        return runners

    return install


@pytest.fixture
def use_fake_test_runners(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeRunners]:
    """Make ``test`` run implementations through in-process fakes.

    Implementations are then named on the command line with ``--command NAME``;
    the commands are never run, nor checked for existing. Returns the factory so a test can inspect the calls.
    """

    def install(behaviors: Mapping[str, Callable[[Any], Any]]) -> FakeRunners:
        runners = FakeRunners(behaviors)
        monkeypatch.setattr(context, "check_can_start", lambda implementation: None)
        real_run_tests = test_command.run_tests

        def run(*arguments: Any, **keywords: Any) -> Any:
            return real_run_tests(*arguments, runner_factory=runners, **keywords)

        monkeypatch.setattr(test_command, "run_tests", run)
        return runners

    return install


@pytest.fixture
def recording_sorter(tmp_path: Path, write_executable: WriteExecutable) -> tuple[Path, Path]:
    """A correct sorter that appends the bytes of every input it receives to a log file."""
    log = tmp_path / "inputs.log"
    script = write_executable(
        tmp_path / "recording_sorter.py",
        f"""\
        #!/usr/bin/env python3
        import struct, sys
        raw = open(sys.argv[1], "rb").read()
        with open({str(log)!r}, "a") as log:
            log.write(raw.hex() + "\\n")
        count = struct.unpack_from("<Q", raw)[0]
        values = sorted(struct.unpack_from(f"<{{count}}i", raw, 8))
        open(sys.argv[2], "wb").write(struct.pack(f"<Q{{count}}i", count, *values))
        """,
    )
    return script, log
