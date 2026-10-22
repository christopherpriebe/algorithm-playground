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

import importlib
import math
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from algorithm_playground.core._errors import AlgorithmPlaygroundError
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._registry import (
    ProblemLoadError,
    ProblemSourceKind,
    list_problems,
    load_problem_modules,
)
from algorithm_playground.core._support import display_path, split_command_text

__all__ = [
    "DEFAULT_CONFIGURATION_FILE_NAME",
    "Configuration",
    "ConfigurationError",
    "ConfiguredImplementation",
    "check_configured_problems",
    "find_configuration",
    "load_configuration",
    "load_configured_problems",
]

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
_NEWER_VERSION_HINT = "If the file was written for a newer algorithm-playground, upgrade this installation."


def _read_document(path: Path, shown: str) -> Mapping[str, object]:
    """Read the TOML document at ``path`` and check its top-level keys.

    Args:
        path: The configuration file.
        shown: The path as shown to users.

    Returns:
        The parsed document.

    Raises:
        ConfigurationError: If the file is missing, unreadable, not valid TOML,
            or holds an unknown top-level key.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        message = f"{shown}: configuration file not found"
        raise ConfigurationError(message) from error
    except (OSError, UnicodeDecodeError) as error:
        message = f"{shown}: could not read configuration file: {error}"
        raise ConfigurationError(message) from error
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        message = f"{shown}: invalid TOML: {error}"
        raise ConfigurationError(message) from error

    unknown_keys = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown_keys:
        allowed = ", ".join(sorted(_TOP_LEVEL_KEYS))
        message = (
            f"{shown}: unknown top-level key(s): {', '.join(unknown_keys)}. "
            f"Allowed keys: {allowed}. {_NEWER_VERSION_HINT}"
        )
        raise ConfigurationError(message)
    return document


def _describe_entry(shown: str, index: int, raw_entry: Mapping[str, object]) -> str:
    description = f"{shown}: implementations[{index}]"
    name = raw_entry.get("name")
    if isinstance(name, str) and name:
        description += f" ('{name}')"
    return description


def _list_of_non_empty_strings(value: object) -> list[str] | None:
    """Return ``value`` if it is a list of non-empty strings, else ``None``."""
    if not isinstance(value, list):
        return None
    strings: list[str] = [item for item in value if isinstance(item, str) and item]
    return strings if len(strings) == len(value) else None


def _is_module_name(text: str) -> bool:
    return all(part.isidentifier() for part in text.split("."))


def _parse_problem_modules(shown: str, value: object) -> tuple[str, ...]:
    names = _list_of_non_empty_strings(value)
    if names is not None and all(_is_module_name(name) for name in names):
        return tuple(dict.fromkeys(names))
    message = (
        f"{shown}: 'problem_modules' must be a list of module names, "
        'for example ["solutions_problems.graphs"]'
    )
    raise ConfigurationError(message)


def _parse_python_paths(path: Path, shown: str, value: object) -> tuple[Path, ...]:
    items = _list_of_non_empty_strings(value)
    if items is None:
        message = f"{shown}: 'python_paths' must be a list of non-empty directory names"
        raise ConfigurationError(message)
    directories: list[Path] = []
    for item in items:
        directory = (path.parent / item).resolve()
        if not directory.is_dir():
            message = f"{shown}: 'python_paths' entry '{item}' is not a directory ({directory})"
            raise ConfigurationError(message)
        directories.append(directory)
    return tuple(dict.fromkeys(directories))


def _entry_tables(shown: str, value: object) -> list[Mapping[str, object]]:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        # TOML tables are dictionaries with text keys.
        return cast(list[Mapping[str, object]], value)
    message = (
        f"{shown}: 'implementations' must be an array of tables ([[implementations]])"
    )
    raise ConfigurationError(message)


def _non_empty_string(
    description: str, raw_entry: Mapping[str, object], key: str
) -> str:
    if key not in raw_entry:
        message = f"{description}: missing required key '{key}'"
        raise ConfigurationError(message)
    value = raw_entry[key]
    if not isinstance(value, str) or not value:
        message = f"{description}: '{key}' must be a non-empty string"
        raise ConfigurationError(message)
    return value


def _parse_command(description: str, key: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            return split_command_text(value)
        except ValueError as error:
            message = f"{description}: '{key}': {error}"
            raise ConfigurationError(message) from error
    arguments = _list_of_non_empty_strings(value)
    if arguments is not None and len(arguments) > 0:
        return tuple(arguments)
    message = f"{description}: '{key}' must be a command string or a non-empty list of non-empty strings"
    raise ConfigurationError(message)


def _parse_environment(
    description: str, value: object, directory: Path
) -> dict[str, str]:
    """Check an ``environment`` table and fill in the configuration directory.

    Args:
        description: Names the entry in messages.
        value: The ``environment`` value from the file.
        directory: The directory that replaces the configuration directory placeholder.

    Returns:
        The variables to set.

    Raises:
        ConfigurationError: If ``value`` is not a table of variable names to text.
    """
    if not isinstance(value, dict):
        message = (
            f"{description}: 'environment' must be a table of variable names to text values, "
            'for example environment = { PYTHONPATH = "{configuration_directory}/lib" }'
        )
        raise ConfigurationError(message)
    environment: dict[str, str] = {}
    for variable, setting in value.items():
        if (
            not isinstance(variable, str)
            or not variable
            or "=" in variable
            or "\0" in variable
        ):
            message = f"{description}: 'environment' has the invalid variable name {variable!r}"
            raise ConfigurationError(message)
        if not isinstance(setting, str) or "\0" in setting:
            message = (
                f"{description}: environment variable '{variable}' must be set to text"
            )
            raise ConfigurationError(message)
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
        message = (
            f"{description}: 'timeout_seconds' must be a positive number of seconds"
        )
        raise ConfigurationError(message)
    return float(value)


def _parse_working_directory(
    description: str, raw_entry: Mapping[str, object], configuration_directory: Path
) -> Path:
    if "working_directory" not in raw_entry:
        return configuration_directory
    relative = _non_empty_string(description, raw_entry, "working_directory")
    return (configuration_directory / relative).resolve()


def _is_environment_inherited(
    description: str, raw_entry: Mapping[str, object]
) -> bool:
    inherit_environment = raw_entry.get("inherit_environment", False)
    if not isinstance(inherit_environment, bool):
        message = f"{description}: 'inherit_environment' must be true or false"
        raise ConfigurationError(message)
    return inherit_environment


def _parse_entry(
    path: Path, *, shown: str, index: int, raw_entry: Mapping[str, object]
) -> "ConfiguredImplementation":
    description = _describe_entry(shown, index, raw_entry)

    unknown_keys = sorted(set(raw_entry) - _IMPLEMENTATION_KEYS)
    if unknown_keys:
        allowed = ", ".join(sorted(_IMPLEMENTATION_KEYS))
        message = (
            f"{description}: unknown key(s): {', '.join(unknown_keys)}. "
            f"Allowed keys: {allowed}. {_NEWER_VERSION_HINT}"
        )
        raise ConfigurationError(message)

    name = _non_empty_string(description, raw_entry, "name")
    problem_name = _non_empty_string(description, raw_entry, "problem")
    if "command" not in raw_entry:
        message = f"{description}: missing required key 'command'"
        raise ConfigurationError(message)
    command = _parse_command(description, "command", raw_entry["command"])
    build_command = (
        _parse_command(description, "build_command", raw_entry["build_command"])
        if "build_command" in raw_entry
        else None
    )
    configuration_directory = path.parent.resolve()
    implementation = Implementation(
        name=name,
        command=command,
        working_directory=_parse_working_directory(
            description, raw_entry, configuration_directory
        ),
        build_command=build_command,
        inherit_environment=_is_environment_inherited(description, raw_entry),
        environment=_parse_environment(
            description, raw_entry.get("environment", {}), configuration_directory
        ),
        timeout_seconds=_parse_timeout(description, raw_entry.get("timeout_seconds")),
    )
    return ConfiguredImplementation(
        problem_name=problem_name, implementation=implementation
    )


def _parse_entries(
    path: Path, shown: str, value: object
) -> tuple["ConfiguredImplementation", ...]:
    """Parse the ``implementations`` tables, rejecting a name used twice for one problem.

    Args:
        path: The configuration file.
        shown: The path as shown to users.
        value: The ``implementations`` value from the file.

    Returns:
        The parsed entries, in file order.

    Raises:
        ConfigurationError: If an entry is invalid or repeats a name for a problem.
    """
    configured: list[ConfiguredImplementation] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_entry in enumerate(_entry_tables(shown, value)):
        entry = _parse_entry(path, shown=shown, index=index, raw_entry=raw_entry)
        key = (entry.problem_name, entry.implementation.name)
        if key in seen:
            message = (
                f"{_describe_entry(shown, index, raw_entry)}: duplicate implementation name "
                f"'{key[1]}' for problem '{key[0]}'"
            )
            raise ConfigurationError(message)
        seen.add(key)
        configured.append(entry)
    return tuple(configured)


class ConfigurationError(AlgorithmPlaygroundError, ValueError):
    """Raised when a configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True, slots=True)
class ConfiguredImplementation:
    """An implementation together with the problem it solves."""

    problem_name: str
    implementation: Implementation


@dataclass(frozen=True, slots=True)
class Configuration:
    """The parsed contents of a configuration file.

    Args:
        path: The configuration file.
        configured_implementations: The implementations, in file order.
        problem_modules: The modules to import so that the problems they
            register can be used.
        python_paths: The directories to add to the front of ``sys.path``.
    """

    path: Path
    configured_implementations: tuple[ConfiguredImplementation, ...] = ()
    problem_modules: tuple[str, ...] = ()
    python_paths: tuple[Path, ...] = ()

    @property
    def display_path(self) -> str:
        """Path as shown to users, relative to the current directory when inside it."""
        return display_path(self.path)

    def implementations_for(self, problem_name: str) -> tuple[Implementation, ...]:
        """Return the implementations configured for a problem.

        Args:
            problem_name: The name of the problem.

        Returns:
            The implementations, in file order.
        """
        return tuple(
            entry.implementation
            for entry in self.configured_implementations
            if entry.problem_name == problem_name
        )

    def find(
        self, problem_name: str, implementation_name: str
    ) -> Implementation | None:
        """Look up an implementation of a problem by name.

        Args:
            problem_name: The name of the problem.
            implementation_name: The name of the implementation.

        Returns:
            The implementation, or ``None`` if there is none of that name.
        """
        for implementation in self.implementations_for(problem_name):
            if implementation.name == implementation_name:
                return implementation
        return None


def find_configuration(directory: Path) -> Path | None:
    """Find the default configuration file of a directory or of the nearest one above it.

    The search starts in ``directory`` and moves up one directory at a time.
    It stops after the first directory that contains a ``.git`` entry (the
    root of a repository) and at the root of the file system.

    Args:
        directory: Where the search starts.

    Returns:
        The path of the file, or ``None`` when it found none.
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
    """Read and validate a configuration file.

    The file may start with a byte order mark, which some editors add.

    Raise :class:`ConfigurationError` if the file is missing, unreadable, not valid
    TOML, or holds an unknown key, an invalid value, or the same implementation name
    twice for one problem.

    Args:
        path: The configuration file.

    Returns:
        The parsed configuration.
    """
    shown = display_path(path)
    document = _read_document(path, shown)
    problem_modules = _parse_problem_modules(shown, document.get("problem_modules", []))
    python_paths = _parse_python_paths(path, shown, document.get("python_paths", []))
    return Configuration(
        path=path,
        configured_implementations=_parse_entries(
            path, shown, document.get("implementations", [])
        ),
        problem_modules=problem_modules,
        python_paths=python_paths,
    )


def load_configured_problems(configuration: Configuration) -> tuple[str, ...]:
    """Make the problems a configuration asks for available.

    Add ``python_paths`` to the front of ``sys.path``, then import the
    ``problem_modules``.

    Args:
        configuration: The configuration.

    Returns:
        One warning for each module that registered no problem.

    Raises:
        ConfigurationError: If a module cannot be imported. The message names
            the file and the module.
    """
    new_paths = [
        str(path) for path in configuration.python_paths if str(path) not in sys.path
    ]
    if new_paths:
        sys.path[:0] = new_paths
        importlib.invalidate_caches()
    try:
        return load_problem_modules(
            configuration.problem_modules, ProblemSourceKind.CONFIGURATION
        )
    except ProblemLoadError as error:
        message = f"{configuration.display_path}: {error}"
        raise ConfigurationError(message) from error


def check_configured_problems(configuration: Configuration) -> None:
    """Require every implementation's ``problem`` to be a registered problem.

    Call it after all problem modules are loaded.

    Args:
        configuration: The configuration.

    Raises:
        ConfigurationError: For the first implementation that names an unknown
            problem.
    """
    known = list_problems()
    for entry in configuration.configured_implementations:
        if entry.problem_name not in known:
            message = (
                f"{configuration.display_path}: implementation '{entry.implementation.name}' "
                f"names unknown problem '{entry.problem_name}'. Registered problems: "
                f"{', '.join(known) or '(none)'}. A problem from your own module must be listed "
                "in 'problem_modules' (or loaded with --problem-module)."
            )
            raise ConfigurationError(message)
