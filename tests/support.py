"""Type aliases and assertions shared by the CLI tests."""

from __future__ import annotations

import struct
from collections.abc import Callable
from pathlib import Path

from typer.testing import Result

Invoke = Callable[..., Result]
Configure = Callable[..., Path]
TableRows = Callable[[str], list[list[str]]]
WriteSorter = Callable[..., Path]
WriteExecutable = Callable[[Path, str], Path]


def assert_exits_with(result: Result, exit_code: int) -> None:
    """Assert that the command ended by exiting with ``exit_code`` and not by crashing."""
    assert result.exit_code == exit_code, f"{result.stdout}{result.stderr}"
    assert isinstance(result.exception, SystemExit), result.exception


def logged_inputs(log: Path) -> list[list[int]]:
    """The inputs a recording sorter saw, as lists of values."""
    inputs = []
    for line in log.read_text().splitlines():
        raw = bytes.fromhex(line)
        (count,) = struct.unpack_from("<Q", raw)
        inputs.append(list(struct.unpack_from(f"<{count}i", raw, 8)))
    return inputs
