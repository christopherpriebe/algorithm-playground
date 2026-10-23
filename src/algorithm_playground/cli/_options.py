"""Typer arguments and options that several commands share."""

import math
from pathlib import Path
from typing import Annotated, cast

import typer
from typer.models import OptionInfo

from algorithm_playground.cli._implementation_selection import EnvironmentPolicy

__all__ = [
    "BuildOption",
    "CommandOption",
    "ConfigurationOption",
    "ImplementationArgument",
    "ImplementationsArgument",
    "InheritEnvironmentOption",
    "NameOption",
    "ProblemModuleOption",
    "build_json_option",
    "build_timeout_option",
    "choose_environment_policy",
    "require_finite_timeout",
]

ImplementationsArgument = Annotated[
    list[str] | None,
    typer.Argument(
        metavar="[IMPLEMENTATION]...",
        help=(
            "Implementations to run: the name of an implementation in the configuration file, "
            "or the path of a runnable file. Defaults to every implementation configured "
            "for the problem."
        ),
    ),
]

ImplementationArgument = Annotated[
    str | None,
    typer.Argument(
        metavar="[IMPLEMENTATION]",
        help=(
            "The implementation to run: the name of an implementation in the configuration "
            "file, or the path of a runnable file."
        ),
    ),
]

CommandOption = Annotated[
    list[str] | None,
    typer.Option(
        "--command",
        help=(
            'Command text of an implementation, for example "node sort.js". The harness '
            "appends the input, output, and optional trace paths. May be repeated; see --name."
        ),
    ),
]

NameOption = Annotated[
    list[str] | None,
    typer.Option(
        "--name",
        help=(
            "Name for the --command in the same position, shown in tables and reports "
            "(default: the script name and the arguments after it). May be repeated."
        ),
    ),
]

ConfigurationOption = Annotated[
    Path | None,
    typer.Option(
        "--configuration",
        help=(
            "Configuration file describing implementations (default: algorithm-playground.toml "
            "in the current directory or the nearest parent directory that has one, looking "
            "up to a directory that contains .git, when present)."
        ),
        dir_okay=False,
        resolve_path=True,
    ),
]

ProblemModuleOption = Annotated[
    list[str] | None,
    typer.Option(
        "--problem-module",
        help=(
            "A Python module that registers problems: a module name, for example "
            "my_solutions.graphs (looked up in the current directory too, and in the "
            "python_paths of the configuration file), or the path of a .py file, for "
            "example graphs.py. May be repeated."
        ),
    ),
]

BuildOption = Annotated[
    bool,
    typer.Option(
        "--build/--no-build",
        help="Run each selected implementation's build command once before using it.",
    ),
]

InheritEnvironmentOption = Annotated[
    bool,
    typer.Option(
        "--inherit-environment",
        help=(
            "Give implementations named by path or --command the full environment instead of "
            "a minimal one. Configured implementations use their own setting."
        ),
    ),
]


def require_finite_timeout(value: float) -> float:
    """Reject ``nan`` and infinity; Typer callback for ``--timeout``.

    Args:
        value: The timeout in seconds.

    Returns:
        The value unchanged.

    Raises:
        typer.BadParameter: If the value is not a finite number.
    """
    if not math.isfinite(value):
        message = f"Timeout must be a finite number, got {value}."
        raise typer.BadParameter(message)
    return value


def build_timeout_option(help_text: str) -> OptionInfo:
    """Build the ``--timeout`` option (seconds, finite, positive).

    Args:
        help_text: The help shown for the option.

    Returns:
        The option, to be used in an ``Annotated`` parameter.
    """
    return cast(
        OptionInfo,
        typer.Option(
            "--timeout", min=0.001, callback=require_finite_timeout, help=help_text
        ),
    )


def build_json_option(help_text: str) -> OptionInfo:
    """Build the ``--json`` option.

    Args:
        help_text: The help shown for the option.

    Returns:
        The option, to be used in an ``Annotated`` parameter.
    """
    return cast(
        OptionInfo,
        typer.Option("--json", help=help_text, dir_okay=False, resolve_path=True),
    )


def choose_environment_policy(*, inherit_environment: bool) -> EnvironmentPolicy:
    """Translate the ``--inherit-environment`` option into the policy it stands for.

    Args:
        inherit_environment: Whether the option was given.

    Returns:
        :attr:`EnvironmentPolicy.INHERIT` when it was given, else
        :attr:`EnvironmentPolicy.MINIMAL`.
    """
    if inherit_environment:
        return EnvironmentPolicy.INHERIT
    return EnvironmentPolicy.MINIMAL
