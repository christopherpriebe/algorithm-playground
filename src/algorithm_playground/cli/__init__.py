"""Typer-based command-line interface for the algorithm playground."""

from algorithm_playground.cli._dependencies import CommandDependencies
from algorithm_playground.cli._implementation_selection import (
    EnvironmentPolicy,
    SelectionError,
    build_selection_arguments,
    discover_configuration,
    require_single,
    select_implementations,
)
from algorithm_playground.cli._main import app

__all__ = [
    "CommandDependencies",
    "EnvironmentPolicy",
    "SelectionError",
    "app",
    "build_selection_arguments",
    "discover_configuration",
    "require_single",
    "select_implementations",
]
