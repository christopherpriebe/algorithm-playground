"""Typer arguments and options that several commands share."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated

import typer
from typer.models import OptionInfo

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


def finite_timeout(value: float) -> float:
    """Typer callback for ``--timeout``: reject ``nan`` and infinity."""
    if not math.isfinite(value):
        raise typer.BadParameter(f"Timeout must be a finite number, got {value}.")
    return value


def timeout_option(help_text: str) -> OptionInfo:
    """Return the ``--timeout`` option (seconds, finite, positive), described by ``help_text``."""
    return typer.Option("--timeout", min=0.001, callback=finite_timeout, help=help_text)


def json_option(help_text: str) -> OptionInfo:
    """Return the ``--json`` option, described by ``help_text``."""
    return typer.Option("--json", help=help_text, dir_okay=False, resolve_path=True)
