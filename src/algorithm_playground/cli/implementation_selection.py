"""Decide which implementations a command runs.

The commands accept implementations three ways: by the name of an entry in a
configuration file, as a path to a runnable file, and as command text
(``--command "node sort.js"``). This module turns those inputs into
:class:`~algorithm_playground.core.implementation.Implementation` objects with
unique names. It never prints and knows nothing about Typer, so the rules can
be tested directly; the CLI layer renders the errors it raises.
"""

import shlex
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from algorithm_playground.core.configuration import (
    DEFAULT_CONFIGURATION_FILE_NAME,
    Configuration,
    find_configuration,
    load_configuration,
)
from algorithm_playground.core.implementation import Implementation

__all__ = [
    "EnvironmentPolicy",
    "SelectionError",
    "discover_configuration",
    "require_single",
    "select_implementations",
    "selection_arguments",
]


def _configured_for(
    problem_name: str, configuration: Configuration | None
) -> tuple[Implementation, ...]:
    if configuration is None:
        raise SelectionError(
            f"No implementation was given for problem '{problem_name}'. Pass the path of a "
            'runnable file, use --command "program arguments", or describe implementations '
            f"in a {DEFAULT_CONFIGURATION_FILE_NAME} file in the current directory or a parent "
            "directory (or pass --configuration PATH)."
        )
    configured = configuration.implementations_for(problem_name)
    if not configured:
        raise SelectionError(
            f"No implementation was given for problem '{problem_name}', and "
            f"{configuration.display_path} configures none for it. Pass the path of a runnable file, "
            'use --command "program arguments", or add an [[implementations]] entry for '
            "this problem to the configuration file."
        )
    return configured


def _unknown_selector_message(
    problem_name: str, text: str, configuration: Configuration | None
) -> str:
    if configuration is None:
        known = (
            f"no configuration file was found (looked for {DEFAULT_CONFIGURATION_FILE_NAME} "
            "in the current directory and its parents, up to a directory that contains .git; "
            "--configuration PATH names another)"
        )
    else:
        names = [
            implementation.name
            for implementation in configuration.implementations_for(problem_name)
        ]
        listing = ", ".join(f"'{name}'" for name in names) if names else "none"
        known = (
            f"implementations configured in {configuration.display_path} for '{problem_name}': "
            f"{listing}"
        )
    return f"'{text}' is neither a configured implementation name nor an existing file; {known}."


def _apply_environment_policy(
    implementation: Implementation, environment_policy: "EnvironmentPolicy"
) -> Implementation:
    if environment_policy is EnvironmentPolicy.INHERIT:
        return replace(implementation, inherit_environment=True)
    else:
        return implementation


def _resolve_selector(
    problem_name: str,
    text: str,
    configuration: Configuration | None,
    *,
    environment_policy: "EnvironmentPolicy",
) -> "_Candidate":
    if configuration is not None:
        configured = configuration.find(problem_name, text)
        if configured is not None:
            return _Candidate(configured)
    path = Path(text)
    if not path.is_file():
        raise SelectionError(_unknown_selector_message(problem_name, text, configuration))
    implementation = Implementation.from_executable(path)
    return _Candidate(
        _apply_environment_policy(implementation, environment_policy), fallback_name=text
    )


def _resolve_command_text(
    text: str, name: str | None, environment_policy: "EnvironmentPolicy"
) -> "_Candidate":
    try:
        implementation = Implementation.from_command_text(text, name=name)
    except ValueError as error:
        raise SelectionError(f"Invalid --command or --name value: {error}") from error
    return _Candidate(
        _apply_environment_policy(implementation, environment_policy),
        fallback_name=text if name is None else None,
    )


def _assign_unique_names(candidates: "Sequence[_Candidate]") -> tuple[Implementation, ...]:
    """Prefer each candidate's own name; use the typed text only where names collide."""
    counts = Counter(candidate.implementation.name for candidate in candidates)
    implementations: list[Implementation] = []
    for candidate in candidates:
        implementation = candidate.implementation
        if counts[implementation.name] > 1 and candidate.fallback_name is not None:
            implementation = replace(implementation, name=candidate.fallback_name)
        implementations.append(implementation)

    duplicates = sorted(
        name for name, count in Counter(item.name for item in implementations).items() if count > 1
    )
    if duplicates:
        listing = ", ".join(f"'{name}'" for name in duplicates)
        raise SelectionError(
            f"Implementation names must be unique, but these were given more than once: {listing}."
        )
    return tuple(implementations)


class SelectionError(ValueError):
    """Raised when the implementations named on the command line cannot be resolved."""


class EnvironmentPolicy(Enum):
    """The environment given to implementations named by path or command text."""

    MINIMAL = "minimal"
    INHERIT = "inherit"


@dataclass(frozen=True)
class _Candidate:
    """An implementation with the name it would get if it is unique."""

    implementation: Implementation
    fallback_name: str | None = None


def discover_configuration(
    configuration_path: Path | None, directory: Path
) -> Configuration | None:
    """Load the configuration the user asked for, or the default one in a directory.

    Args:
        configuration_path: The configuration file named on the command line, if any.
        directory: Where to look for the default configuration file when none is named.

    Returns:
        The configuration, or ``None`` when none is named and the directory has no
        default configuration file.

    Raises:
        algorithm_playground.core.configuration.ConfigurationError: If a file that
            should be read is missing or invalid.
    """
    if configuration_path is not None:
        return load_configuration(configuration_path)
    default_path = find_configuration(directory)
    return load_configuration(default_path) if default_path is not None else None


def select_implementations(
    problem_name: str,
    selectors: Sequence[str],
    command_texts: Sequence[str],
    *,
    configuration: Configuration | None,
    environment_policy: EnvironmentPolicy = EnvironmentPolicy.MINIMAL,
    command_names: Sequence[str] = (),
) -> tuple[Implementation, ...]:
    """Resolve what the user named into implementations with unique names.

    The result lists the selectors first, then the commands, each group in the
    order given. When both are empty, every implementation configured for the
    problem is used.

    Args:
        problem_name: The problem the implementations are for.
        selectors: The positional arguments: each is the name of an implementation
            configured for the problem, or else the path of an existing file.
        command_texts: The ``--command`` values.
        configuration: The configuration file in use, if any.
        environment_policy: The environment of implementations given as paths or
            command text; configured ones keep their own setting.
        command_names: The ``--name`` values that name the commands in order (there
            may be fewer names than commands, never more).

    Returns:
        The implementations, with unique names.

    Raises:
        SelectionError: If a name or path cannot be resolved, a command is invalid,
            there are more names than commands, or two implementations share a name.
    """
    if len(command_names) > len(command_texts):
        raise SelectionError(
            f"--name was given {len(command_names)} times, but there are only "
            f"{len(command_texts)} --command values to name. Each --name names the "
            "--command in the same position."
        )
    if not selectors and not command_texts:
        return _configured_for(problem_name, configuration)

    candidates = [
        _resolve_selector(problem_name, text, configuration, environment_policy=environment_policy)
        for text in selectors
    ]
    candidates.extend(
        _resolve_command_text(
            text,
            command_names[position] if position < len(command_names) else None,
            environment_policy,
        )
        for position, text in enumerate(command_texts)
    )
    return _assign_unique_names(candidates)


def require_single(
    implementations: Sequence[Implementation], *, command_name: str
) -> Implementation:
    """Return the only implementation, or explain that the command needs exactly one.

    Args:
        implementations: The selected implementations.
        command_name: The command that needs exactly one, named in the error.

    Returns:
        The only implementation.

    Raises:
        SelectionError: If there is not exactly one implementation.
    """
    if len(implementations) == 1:
        return implementations[0]
    names = ", ".join(f"'{implementation.name}'" for implementation in implementations)
    raise SelectionError(
        f"'{command_name}' needs exactly one implementation, but {len(implementations)} were "
        f"selected ({names}). Name the one to run."
    )


def selection_arguments(
    problem_name: str, implementation: Implementation, configuration: Configuration | None
) -> tuple[str, ...]:
    """Return command-line arguments that select an implementation again.

    A configured implementation is named; any other is given as ``--command``
    with its full command (a file is already an absolute path).

    Args:
        problem_name: The problem the implementation is for.
        implementation: The implementation to select again.
        configuration: The configuration file in use, if any.

    Returns:
        The arguments to pass to a command.
    """
    if configuration is not None and configuration.find(problem_name, implementation.name) == (
        implementation
    ):
        return (implementation.name,)
    arguments = ("--command", shlex.join(implementation.command))
    if implementation.inherit_environment:
        return (*arguments, "--inherit-environment")
    return arguments
