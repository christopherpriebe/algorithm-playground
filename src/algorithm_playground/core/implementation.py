"""A runnable implementation of a problem: a command the harness extends with file paths.

An :class:`Implementation` is a program plus its leading arguments (``node
sort.js``, ``java -jar Sort.jar``, ``./build/merge_sort``). The runner appends
``<input> <output> [<trace>]`` to the command, so any language works as long
as the program honors the problem's binary contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from algorithm_playground.core._support import split_command_text


@dataclass(frozen=True)
class Implementation:
    """A named command that implements a problem's binary contract.

    ``working_directory`` of ``None`` means the caller's current directory.
    ``build_command`` runs once before the implementation is used. By default
    the child process sees a minimal environment; set ``inherit_environment``
    to pass the full environment of the caller instead. ``environment`` adds
    variables on top of whichever of the two applies, for runs and for the
    build. ``timeout_seconds`` replaces the timeout given for the run when it
    is set.
    """

    name: str
    command: tuple[str, ...]
    working_directory: Path | None = None
    build_command: tuple[str, ...] | None = None
    inherit_environment: bool = False
    environment: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("An implementation must have a non-empty name")
        if not self.command:
            raise ValueError(f"Implementation '{self.name}' must have a non-empty command")
        if self.build_command is not None and not self.build_command:
            raise ValueError(f"Implementation '{self.name}' has an empty build command")
        for variable, value in self.environment.items():
            if not variable or "=" in variable or "\0" in variable or "\0" in value:
                raise ValueError(
                    f"Implementation '{self.name}' has an invalid environment variable {variable!r}"
                )
        if self.timeout_seconds is not None and (
            not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
        ):
            raise ValueError(
                f"Implementation '{self.name}' needs a finite positive timeout, "
                f"got {self.timeout_seconds}"
            )

    @classmethod
    def from_executable(cls, path: Path, *, name: str | None = None) -> Implementation:
        """Wrap a single executable file; the name defaults to the file name."""
        resolved = path.resolve()
        return cls(name=name if name is not None else path.name, command=(str(resolved),))

    @classmethod
    def from_command_text(cls, text: str, *, name: str | None = None) -> Implementation:
        """Split ``text`` into a command.

        The name defaults to the last argument that names an existing file,
        without its extension, followed by the arguments after it:
        ``python3 sort.py`` is called ``sort``, ``python3 sort.py insertion`` is
        called ``sort insertion``, and ``java -jar build/Sort.jar`` is called
        ``Sort``, so two commands that run the same script with other arguments
        stay apart. When no argument names a file the name is the text itself.
        """
        command = split_command_text(text)
        if name is None:
            name = _default_name(command) or text
        return cls(name=name, command=command)

    def referenced_files(self) -> tuple[Path, ...]:
        """Return the existing files named by the command, as absolute paths.

        Arguments are resolved against ``working_directory`` when it is set.
        Reports fingerprint these files so a result can be tied to the code
        that produced it.
        """
        base = self.working_directory if self.working_directory is not None else Path.cwd()
        files: list[Path] = []
        for argument in self.command:
            candidate = (base / argument).resolve()
            if candidate.is_file() and candidate not in files:
                files.append(candidate)
        return tuple(files)


def _default_name(command: tuple[str, ...]) -> str | None:
    for position in range(len(command) - 1, -1, -1):
        candidate = Path(command[position])
        if candidate.is_file():
            return " ".join([candidate.stem, *command[position + 1 :]])
    return None
