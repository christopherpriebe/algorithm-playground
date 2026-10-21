"""Helpers shared by the core modules; not part of the public API."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from algorithm_playground.core.implementation import Implementation


def split_command_text(text: str) -> tuple[str, ...]:
    """Split shell-style command text into arguments; reject empty or malformed text."""
    try:
        arguments = shlex.split(text)
    except ValueError as error:
        raise ValueError(f"Could not parse command {text!r}: {error}") from error
    if not arguments:
        raise ValueError("A command must not be empty")
    return tuple(arguments)


def describe_error(error: BaseException) -> str:
    """Return ``ErrorType: message`` for use inside a larger message."""
    return f"{type(error).__name__}: {error}"


def validate_implementations(implementations: Sequence[Implementation]) -> None:
    """Require at least one implementation and unique names."""
    if not implementations:
        raise ValueError("At least one implementation is required")
    seen: set[str] = set()
    for implementation in implementations:
        if implementation.name in seen:
            raise ValueError(f"Duplicate implementation name: '{implementation.name}'")
        seen.add(implementation.name)


def display_path(path: Path) -> str:
    """Return ``path`` relative to the current directory when it lies inside it."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
