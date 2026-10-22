"""Command-line invocation, output parsing and assertions shared by the CLI tests."""

import dataclasses
import struct
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from algorithm_playground.cli import CommandDependencies, app

# The type of the ``configure`` fixture, which writes a configuration file.
Configure = Callable[..., Path]


@dataclasses.dataclass(slots=True)
class _ActiveDependencies:
    """The collaborators that the commands run by these helpers are handed."""

    value: CommandDependencies = dataclasses.field(default_factory=CommandDependencies)


_ACTIVE_DEPENDENCIES = _ActiveDependencies()


def replace_command_dependencies(
    monkeypatch: pytest.MonkeyPatch, **replacements: object
) -> None:
    """Hand the commands these collaborators for the rest of the test.

    Later calls add to earlier ones, and the defaults come back after the test.

    Args:
        monkeypatch: The test's monkeypatch, which undoes the change.
        **replacements: Fields of :class:`CommandDependencies` and their new values.
    """
    monkeypatch.setattr(
        _ACTIVE_DEPENDENCIES,
        "value",
        dataclasses.replace(_ACTIVE_DEPENDENCIES.value, **replacements),
    )


def invoke_cli(*arguments: str, keystrokes: str | None = None) -> Result:
    """Run the command-line app in-process with the given arguments.

    The commands get the collaborators set with :func:`replace_command_dependencies`.

    Args:
        *arguments: The command-line arguments after the program name.
        keystrokes: What to type on standard input, if anything.

    Returns:
        The result Click collected: exit code, output streams and exception.
    """
    return CliRunner().invoke(
        app, list(arguments), input=keystrokes, obj=_ACTIVE_DEPENDENCIES.value
    )


def parse_table_rows(output: str) -> list[list[str]]:
    """Split the body rows of the rendered tables in some output into stripped cells.

    Args:
        output: The text the command wrote.

    Returns:
        One list of cell texts for every table row, in order.
    """
    return [
        [cell.strip() for cell in line.strip().strip("│").split("│")]
        for line in output.splitlines()
        if line.startswith("│")
    ]


def find_table_header(output: str) -> str:
    """Return the first header line of the tables in the output."""
    return next(line for line in output.splitlines() if line.startswith("┃"))


def assert_exits_with(result: Result, exit_code: int) -> None:
    """Assert that the command ended by exiting with ``exit_code`` and not by crashing."""
    assert result.exit_code == exit_code, f"{result.stdout}{result.stderr}"
    assert isinstance(result.exception, SystemExit), result.exception


def read_logged_inputs(log: Path) -> list[list[int]]:
    """Read the inputs a recording sorter saw, as lists of values.

    Args:
        log: The log file the recording sorter appended to, one hex-encoded input per line.

    Returns:
        The values of every logged input, in the order they were received.
    """
    inputs: list[list[int]] = []
    for line in log.read_text().splitlines():
        raw = bytes.fromhex(line)
        (count,) = struct.unpack_from("<Q", raw)
        inputs.append(list(struct.unpack_from(f"<{count}i", raw, 8)))
    return inputs
