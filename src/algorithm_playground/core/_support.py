"""Helpers shared by the core modules; not part of the public API."""

import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # implementation.py imports this module, so the import is for annotations only.
    from algorithm_playground.core._implementation import Implementation

__all__ = ["display_path", "split_command_text", "validate_implementations"]


def split_command_text(text: str) -> tuple[str, ...]:
    """Split shell-style command text into arguments.

    Args:
        text: The command as a user would type it.

    Returns:
        The arguments of the command.

    Raises:
        ValueError: If ``text`` is malformed or holds no argument.
    """
    try:
        arguments = shlex.split(text)
    except ValueError as error:
        message = f"Could not parse command {text!r}: {error}"
        raise ValueError(message) from error
    if not arguments:
        message = "A command must not be empty"
        raise ValueError(message)
    return tuple(arguments)


def validate_implementations(implementations: Sequence["Implementation"]) -> None:
    """Require at least one implementation and unique names.

    Args:
        implementations: The implementations to check.

    Raises:
        ValueError: If there are none or two share a name.
    """
    if not implementations:
        message = "At least one implementation is required"
        raise ValueError(message)
    seen: set[str] = set()
    for implementation in implementations:
        if implementation.name in seen:
            message = f"Duplicate implementation name: '{implementation.name}'"
            raise ValueError(message)
        seen.add(implementation.name)


def display_path(path: Path) -> str:
    """Return the path as shown to users.

    Args:
        path: The path to show.

    Returns:
        ``path`` relative to the current directory when it lies inside it,
        otherwise ``path`` unchanged.
    """
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
