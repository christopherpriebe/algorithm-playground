"""A runnable implementation of a problem: a command the harness extends with file paths.

An :class:`Implementation` is a program plus its leading arguments (``node
sort.js``, ``java -jar Sort.jar``, ``./build/merge_sort``). The runner appends
``<input> <output> [<trace>]`` to the command, so any language works as long
as the program honors the problem's binary contract.
"""

import math
from collections.abc import Iterator, Mapping
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path
from typing import Self

from typing_extensions import override

from algorithm_playground.core._support import split_command_text

__all__ = ["Implementation"]


def _default_name(command: tuple[str, ...]) -> str | None:
    """Name a command after the last argument that is an existing file.

    Returns:
        The name, or ``None`` when no argument is an existing file.
    """
    for position in range(len(command) - 1, -1, -1):
        candidate = Path(command[position])
        if candidate.is_file():
            return " ".join([candidate.stem, *command[position + 1 :]])
    return None


def _is_valid_environment_variable(variable: str, value: str) -> bool:
    return (
        bool(variable)
        and "=" not in variable
        and "\0" not in variable
        and "\0" not in value
    )


class _Environment(Mapping[str, str]):
    """An immutable, hashable copy of environment variables that pickles and copies."""

    def __init__(self, variables: Mapping[str, str]) -> None:
        self._variables = dict(variables)

    @override
    def __getitem__(self, variable: str) -> str:
        return self._variables[variable]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._variables)

    @override
    def __len__(self) -> int:
        return len(self._variables)

    @override
    def __repr__(self) -> str:
        return repr(self._variables)

    @override
    def __hash__(self) -> int:
        return hash(frozenset(self._variables.items()))

    @override
    def __reduce__(self) -> tuple[type[Self], tuple[dict[str, str]]]:
        return type(self), (dict(self._variables),)


@dataclass(frozen=True, slots=True)
class Implementation:
    """A named command that implements a problem's binary contract.

    Args:
        name: The name that identifies the implementation in reports.
        command: The program and its leading arguments.
        working_directory: The directory to run in. ``None`` means the current
            directory of the caller.
        build_command: A command that runs once before the implementation is
            used.
        inherit_environment: Pass the full environment of the caller to the
            child process instead of a minimal one.
        environment: Variables added on top of whichever environment applies,
            for runs and for the build.
        timeout_seconds: A timeout that replaces the one given for a run when
            it is set.

    The environment is copied and read-only, and implementations are hashable,
    can be pickled and can be deep-copied.

    Raises:
        ValueError: If the name or the command is empty, the build command is
            empty, an environment variable is invalid, or the timeout is not
            a finite positive number.
    """

    name: str
    command: tuple[str, ...]
    _: KW_ONLY
    working_directory: Path | None = None
    build_command: tuple[str, ...] | None = None
    inherit_environment: bool = False
    environment: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        # A read-only copy, so neither the caller's mapping nor later writes can
        # change what was validated below.
        object.__setattr__(self, "environment", _Environment(self.environment))
        if not self.name:
            message = "An implementation must have a non-empty name"
            raise ValueError(message)
        if not self.command:
            message = f"Implementation '{self.name}' must have a non-empty command"
            raise ValueError(message)
        if self.build_command is not None and not self.build_command:
            message = f"Implementation '{self.name}' has an empty build command"
            raise ValueError(message)
        for variable, value in self.environment.items():
            if not _is_valid_environment_variable(variable, value):
                message = (
                    f"Implementation '{self.name}' has an invalid environment "
                    f"variable {variable!r}"
                )
                raise ValueError(message)
        if self.timeout_seconds is not None and (
            not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
        ):
            message = (
                f"Implementation '{self.name}' needs a finite positive timeout, "
                f"got {self.timeout_seconds}"
            )
            raise ValueError(message)

    @classmethod
    def from_executable(cls, path: Path, *, name: str | None = None) -> Self:
        """Wrap a single executable file.

        Args:
            path: The executable file.
            name: The name of the implementation. Defaults to the file name.

        Returns:
            An implementation whose command is the resolved path.
        """
        resolved = path.resolve()
        return cls(
            name=name if name is not None else path.name, command=(str(resolved),)
        )

    @classmethod
    def from_command_text(cls, text: str, *, name: str | None = None) -> Self:
        """Split command text into an implementation.

        The default name is the last argument that names an existing file,
        without its extension, followed by the arguments after it:
        ``python3 sort.py`` is called ``sort``, ``python3 sort.py insertion`` is
        called ``sort insertion``, and ``java -jar build/Sort.jar`` is called
        ``Sort``, so two commands that run the same script with other arguments
        stay apart. When no argument names a file the name is the text itself.
        It raises ``ValueError`` if ``text`` is malformed or empty.

        Args:
            text: The command as a user would type it.
            name: The name of the implementation. Defaults as described above.

        Returns:
            The implementation.
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

        Returns:
            The files, each once, in command order.
        """
        base = (
            self.working_directory if self.working_directory is not None else Path.cwd()
        )
        files: list[Path] = []
        for argument in self.command:
            candidate = (base / argument).resolve()
            if candidate.is_file() and candidate not in files:
                files.append(candidate)
        return tuple(files)
