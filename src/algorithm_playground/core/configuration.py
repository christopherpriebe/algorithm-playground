"""Load implementations from a TOML configuration file.

A solutions repository describes its implementations in
``algorithm-playground.toml``::

    [[implementations]]
    name = "merge-sort-c"
    problem = "sorting"
    command = "./build/merge_sort"
    build_command = "make build/merge_sort"

Each entry names the problem it solves, the command to run, an optional build
command, an optional working directory (relative to the configuration file,
defaulting to the file's own directory), an optional ``inherit_environment``
flag, an optional ``environment`` table of variables to set (a value may
contain ``{configuration_directory}``, which becomes the directory of the
configuration file), and an optional ``timeout_seconds`` for this
implementation's runs.

Two top-level keys make problems that live outside this package available.
``python_paths`` lists directories (relative to the configuration file) that
are added to the front of ``sys.path``, and ``problem_modules`` lists modules
that are imported so that the problems they register can be used::

    python_paths = ["."]
    problem_modules = ["solutions_problems.graphs"]
"""

from __future__ import annotations

import importlib
import math
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from algorithm_playground.core._support import display_path, split_command_text
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.registry import (
    ProblemLoadError,
    ProblemSourceKind,
    list_problems,
    load_problem_modules,
)

DEFAULT_CONFIGURATION_FILE_NAME = "algorithm-playground.toml"

_TOP_LEVEL_KEYS = frozenset({"implementations", "problem_modules", "python_paths"})
_IMPLEMENTATION_KEYS = frozenset(
    {
        "name",
        "problem",
        "command",
        "build_command",
        "working_directory",
        "inherit_environment",
        "environment",
        "timeout_seconds",
    }
)
_CONFIGURATION_DIRECTORY_PLACEHOLDER = "{configuration_directory}"
_NEWER_VERSION_HINT = (
    "If the file was written for a newer algorithm-playground, upgrade this installation."
)


class ConfigurationError(ValueError):
    """Raised when a configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class ConfiguredImplementation:
    """An implementation together with the problem it solves."""

    problem_name: str
    implementation: Implementation


@dataclass(frozen=True)
class Configuration:
    """The parsed contents of a configuration file."""

    path: Path
    configured_implementations: tuple[ConfiguredImplementation, ...] = ()
    problem_modules: tuple[str, ...] = ()
    python_paths: tuple[Path, ...] = ()

    @property
    def display_path(self) -> str:
        """The path as shown to users: relative to the current directory when inside it."""
        return display_path(self.path)

    def implementations_for(self, problem_name: str) -> tuple[Implementation, ...]:
        """Return the implementations configured for ``problem_name``, in file order."""
        return tuple(
            entry.implementation
            for entry in self.configured_implementations
            if entry.problem_name == problem_name
        )

    def find(self, problem_name: str, implementation_name: str) -> Implementation | None:
        """Return the named implementation for ``problem_name``, or ``None``."""
        for implementation in self.implementations_for(problem_name):
            if implementation.name == implementation_name:
                return implementation
        return None


def find_configuration(directory: Path) -> Path | None:
    """Return the default configuration file of ``directory`` or of the nearest directory above it.

    The search starts in ``directory`` and moves up one directory at a time.
    It stops after the first directory that contains a ``.git`` entry (the
    root of a repository) and at the root of the file system, and returns
    ``None`` when it found no file by then.
    """
    current = directory.resolve()
    while True:
        candidate = current / DEFAULT_CONFIGURATION_FILE_NAME
        if candidate.is_file():
            return candidate
        if (current / ".git").exists() or current.parent == current:
            return None
        current = current.parent


def load_configuration(path: Path) -> Configuration:
    """Read and validate the configuration file at ``path``.

    The file may start with a byte order mark, which some editors add.
    """
    shown = display_path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        raise ConfigurationError(f"{shown}: configuration file not found") from error
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigurationError(f"{shown}: could not read configuration file: {error}") from error
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"{shown}: invalid TOML: {error}") from error

    unknown_keys = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown_keys:
        allowed = ", ".join(sorted(_TOP_LEVEL_KEYS))
        raise ConfigurationError(
            f"{shown}: unknown top-level key(s): {', '.join(unknown_keys)}. "
            f"Allowed keys: {allowed}. {_NEWER_VERSION_HINT}"
        )

    problem_modules = _parse_problem_modules(shown, document.get("problem_modules", []))
    python_paths = _parse_python_paths(path, shown, document.get("python_paths", []))
    entries = _entry_tables(shown, document.get("implementations", []))

    configured: list[ConfiguredImplementation] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_entry in enumerate(entries):
        entry = _parse_entry(path, shown, index, raw_entry)
        key = (entry.problem_name, entry.implementation.name)
        if key in seen:
            raise ConfigurationError(
                f"{_describe_entry(shown, index, raw_entry)}: duplicate implementation name "
                f"'{key[1]}' for problem '{key[0]}'"
            )
        seen.add(key)
        configured.append(entry)
    return Configuration(
        path=path,
        configured_implementations=tuple(configured),
        problem_modules=problem_modules,
        python_paths=python_paths,
    )


def load_configured_problems(configuration: Configuration) -> tuple[str, ...]:
    """Make the problems the configuration asks for available.

    Add ``python_paths`` to the front of ``sys.path``, then import the
    ``problem_modules``. Raise :class:`ConfigurationError` naming the file and
    the module when one cannot be imported. Return a warning for each module
    that registered no problem.
    """
    new_paths = [str(path) for path in configuration.python_paths if str(path) not in sys.path]
    if new_paths:
        sys.path[:0] = new_paths
        importlib.invalidate_caches()
    try:
        return load_problem_modules(configuration.problem_modules, ProblemSourceKind.CONFIGURATION)
    except ProblemLoadError as error:
        raise ConfigurationError(f"{configuration.display_path}: {error}") from error


def check_configured_problems(configuration: Configuration) -> None:
    """Require every implementation's ``problem`` to be a registered problem.

    Call it after all problem modules are loaded. Raise
    :class:`ConfigurationError` for the first implementation that names an
    unknown problem.
    """
    known = list_problems()
    for entry in configuration.configured_implementations:
        if entry.problem_name not in known:
            raise ConfigurationError(
                f"{configuration.display_path}: implementation '{entry.implementation.name}' "
                f"names unknown problem '{entry.problem_name}'. Registered problems: "
                f"{', '.join(known) or '(none)'}. A problem from your own module must be listed "
                "in 'problem_modules' (or loaded with --problem-module)."
            )


def _parse_problem_modules(shown: str, value: object) -> tuple[str, ...]:
    names = _list_of_non_empty_strings(value)
    if names is not None and all(_is_module_name(name) for name in names):
        return tuple(dict.fromkeys(names))
    raise ConfigurationError(
        f"{shown}: 'problem_modules' must be a list of module names, "
        'for example ["solutions_problems.graphs"]'
    )


def _is_module_name(text: str) -> bool:
    return all(part.isidentifier() for part in text.split("."))


def _parse_python_paths(path: Path, shown: str, value: object) -> tuple[Path, ...]:
    items = _list_of_non_empty_strings(value)
    if items is None:
        raise ConfigurationError(
            f"{shown}: 'python_paths' must be a list of non-empty directory names"
        )
    directories: list[Path] = []
    for item in items:
        directory = (path.parent / item).resolve()
        if not directory.is_dir():
            raise ConfigurationError(
                f"{shown}: 'python_paths' entry '{item}' is not a directory ({directory})"
            )
        directories.append(directory)
    return tuple(dict.fromkeys(directories))


def _list_of_non_empty_strings(value: object) -> list[str] | None:
    """Return ``value`` if it is a list of non-empty strings, else ``None``."""
    if not isinstance(value, list):
        return None
    strings = [item for item in value if isinstance(item, str) and item]
    return strings if len(strings) == len(value) else None


def _entry_tables(shown: str, value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    raise ConfigurationError(
        f"{shown}: 'implementations' must be an array of tables ([[implementations]])"
    )


def _parse_entry(
    path: Path, shown: str, index: int, raw_entry: dict[str, Any]
) -> ConfiguredImplementation:
    description = _describe_entry(shown, index, raw_entry)

    unknown_keys = sorted(set(raw_entry) - _IMPLEMENTATION_KEYS)
    if unknown_keys:
        allowed = ", ".join(sorted(_IMPLEMENTATION_KEYS))
        raise ConfigurationError(
            f"{description}: unknown key(s): {', '.join(unknown_keys)}. "
            f"Allowed keys: {allowed}. {_NEWER_VERSION_HINT}"
        )

    name = _non_empty_string(description, raw_entry, "name")
    problem_name = _non_empty_string(description, raw_entry, "problem")
    if "command" not in raw_entry:
        raise ConfigurationError(f"{description}: missing required key 'command'")
    command = _parse_command(description, "command", raw_entry["command"])
    build_command = (
        _parse_command(description, "build_command", raw_entry["build_command"])
        if "build_command" in raw_entry
        else None
    )

    working_directory = path.parent.resolve()
    if "working_directory" in raw_entry:
        working_directory = (
            working_directory / _non_empty_string(description, raw_entry, "working_directory")
        ).resolve()

    inherit_environment = raw_entry.get("inherit_environment", False)
    if not isinstance(inherit_environment, bool):
        raise ConfigurationError(f"{description}: 'inherit_environment' must be true or false")

    implementation = Implementation(
        name=name,
        command=command,
        working_directory=working_directory,
        build_command=build_command,
        inherit_environment=inherit_environment,
        environment=_parse_environment(
            description, raw_entry.get("environment", {}), path.parent.resolve()
        ),
        timeout_seconds=_parse_timeout(description, raw_entry.get("timeout_seconds")),
    )
    return ConfiguredImplementation(problem_name=problem_name, implementation=implementation)


def _parse_environment(description: str, value: object, directory: Path) -> dict[str, str]:
    """Check an ``environment`` table and fill in the configuration directory."""
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"{description}: 'environment' must be a table of variable names to text values, "
            'for example environment = { PYTHONPATH = "{configuration_directory}/lib" }'
        )
    environment: dict[str, str] = {}
    for variable, setting in value.items():
        if not isinstance(variable, str) or not variable or "=" in variable or "\0" in variable:
            raise ConfigurationError(
                f"{description}: 'environment' has the invalid variable name {variable!r}"
            )
        if not isinstance(setting, str) or "\0" in setting:
            raise ConfigurationError(
                f"{description}: environment variable '{variable}' must be set to text"
            )
        environment[variable] = setting.replace(
            _CONFIGURATION_DIRECTORY_PLACEHOLDER, str(directory)
        )
    return environment


def _parse_timeout(description: str, value: object) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigurationError(
            f"{description}: 'timeout_seconds' must be a positive number of seconds"
        )
    return float(value)


def _describe_entry(shown: str, index: int, raw_entry: dict[str, Any]) -> str:
    description = f"{shown}: implementations[{index}]"
    name = raw_entry.get("name")
    if isinstance(name, str) and name:
        description += f" ('{name}')"
    return description


def _non_empty_string(description: str, raw_entry: dict[str, Any], key: str) -> str:
    if key not in raw_entry:
        raise ConfigurationError(f"{description}: missing required key '{key}'")
    value = raw_entry[key]
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{description}: '{key}' must be a non-empty string")
    return value


def _parse_command(description: str, key: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            return split_command_text(value)
        except ValueError as error:
            raise ConfigurationError(f"{description}: '{key}': {error}") from error
    arguments = _list_of_non_empty_strings(value)
    if arguments:
        return tuple(arguments)
    raise ConfigurationError(
        f"{description}: '{key}' must be a command string or a non-empty list of non-empty strings"
    )
