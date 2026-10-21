"""The setup every command shares: consoles, problems, implementations, and builds.

:class:`CommandContext` turns what the user typed into the objects a command
needs and reports each failure the same way: a message on standard error and
an exit code, ``2`` for a usage or configuration error and ``1`` for a build
failure or a command that cannot be started. The selection rules live in
:mod:`algorithm_playground.cli.implementation_selection`; this module only
connects them to the terminal.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

from algorithm_playground.cli.implementation_selection import (
    SelectionError,
    discover_configuration,
    require_single,
    select_implementations,
)
from algorithm_playground.core.cases import Case, CaseError, resolve_case
from algorithm_playground.core.configuration import (
    Configuration,
    ConfigurationError,
    check_configured_problems,
    load_configured_problems,
)
from algorithm_playground.core.hooks import HookError
from algorithm_playground.core.hooks import call_hook as call_guarded
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.registry import (
    ProblemLoadError,
    ProblemSourceKind,
    UnknownProblemError,
    get_problem,
    load_entry_point_problems,
    load_problem_modules,
)
from algorithm_playground.core.runner import BuildError, build_implementations, check_can_start

USAGE_ERROR_EXIT_CODE = 2
FAILURE_EXIT_CODE = 1

HookResult = TypeVar("HookResult")


@dataclass(frozen=True)
class BuildOutcome:
    """Which selected implementations are ready to run, which failed to build and which cannot start.

    ``unrunnable`` maps the name of an implementation whose command cannot be
    started (not found, not executable) to the reason.
    """

    ready: tuple[Implementation, ...]
    failures: Mapping[str, BuildError]
    unrunnable: Mapping[str, str]

    @property
    def unavailable(self) -> frozenset[str]:
        """The names of the implementations that were left out of the run."""
        return frozenset(self.failures) | frozenset(self.unrunnable)


class CommandContext:
    """The consoles and configuration of one command invocation.

    Creating it loads every source of problems in this order: installed entry
    points (a failing one is a warning), the configuration file with its
    ``python_paths`` and ``problem_modules``, then the ``--problem-module``
    values, which may also be Python files and are looked up in the current
    directory. A module that registers no problem is a warning. Afterwards
    every problem the configuration names must exist. ``configuration`` is
    ``None`` when there is no configuration file. Any failure is a usage error.
    """

    def __init__(
        self, configuration_path: Path | None, problem_modules: Sequence[str] | None
    ) -> None:
        self.console = Console()
        self.error_console = Console(stderr=True)
        self.warn(*load_entry_point_problems())
        self.configuration = self._load_configuration(configuration_path)
        try:
            if self.configuration is not None:
                self.warn(*load_configured_problems(self.configuration))
            self.warn(
                *load_problem_modules(
                    problem_modules or (),
                    ProblemSourceKind.OPTION,
                    search_directories=(Path.cwd(),),
                )
            )
            if self.configuration is not None:
                check_configured_problems(self.configuration)
        except ConfigurationError as error:
            self.fail(f"Configuration error: {error}")
        except ProblemLoadError as error:
            self.fail(str(error))

    def warn(self, *messages: str) -> None:
        """Print each message as a warning on standard error."""
        for message in messages:
            self.error_console.print(f"[yellow]Warning: {escape(message)}[/yellow]", soft_wrap=True)

    def fail(self, message: str, *, code: int = USAGE_ERROR_EXIT_CODE) -> NoReturn:
        """Print ``message`` as an error on standard error and exit with ``code``."""
        self.error_console.print(f"[red]{escape(message)}[/red]", soft_wrap=True)
        raise typer.Exit(code=code)

    def call_hook(self, hook: str, call: Callable[[], HookResult]) -> HookResult:
        """Call a hook of a problem; if it raises, name the hook and exit with the failure code.

        A problem comes from outside this package, so a bug in one of its hooks
        must end in a message that says which hook, not in a traceback.
        """
        try:
            return call_guarded(hook, call)
        except HookError as error:
            self.fail(str(error), code=FAILURE_EXIT_CODE)

    def get_problem(self, problem_name: str) -> Problem[Any, Any, Any]:
        """Return the registered problem; exit with a usage error if there is none."""
        try:
            return get_problem(problem_name)
        except UnknownProblemError as error:
            self.fail(str(error))

    def resolve_case(self, problem: Problem[Any, Any, Any], identifier: str) -> Case[Any]:
        """Rebuild the case named by ``identifier``; exit with a usage error if there is none."""
        try:
            return resolve_case(problem, identifier)
        except CaseError as error:
            self.fail(str(error))

    def select_implementations(
        self,
        problem_name: str,
        *,
        selectors: Sequence[str] | None,
        command_texts: Sequence[str] | None,
        command_names: Sequence[str] | None = None,
        inherit_environment: bool,
    ) -> tuple[Implementation, ...]:
        """Resolve the implementations to run; exit with a usage error when that is impossible."""
        try:
            return select_implementations(
                problem_name,
                selectors or (),
                command_texts or (),
                configuration=self.configuration,
                inherit_environment=inherit_environment,
                command_names=command_names or (),
            )
        except SelectionError as error:
            self.fail(str(error))

    def require_single(
        self, implementations: Sequence[Implementation], *, command_name: str
    ) -> Implementation:
        """Return the only selected implementation; exit with a usage error if there are more."""
        try:
            return require_single(implementations, command_name=command_name)
        except SelectionError as error:
            self.fail(str(error))

    def build(self, implementations: Sequence[Implementation], *, build: bool) -> BuildOutcome:
        """Build the selected implementations unless ``build`` is false, then check they can start.

        Each build is announced and each failure is printed once, with the
        build's output, on standard error. After the builds, the command of each
        implementation is checked once, without running it, so that a program
        that was not found or is not executable is reported at once and not for
        every case. An implementation that failed either way is left out of
        :attr:`BuildOutcome.ready`. Exit with the failure code when none is left
        to run.
        """
        failures: dict[str, BuildError] = {}
        if build:

            def announce(implementation: Implementation) -> None:
                command = shlex.join(implementation.build_command or ())
                self.error_console.print(
                    f"[dim]Building {escape(implementation.name)}: {escape(command)}[/dim]",
                    soft_wrap=True,
                )

            def report_failure(_implementation: Implementation, error: BuildError) -> None:
                self.error_console.print(f"[red]{escape(str(error))}[/red]", soft_wrap=True)

            failures = build_implementations(
                implementations, on_build_started=announce, on_build_failed=report_failure
            )
        unrunnable: dict[str, str] = {}
        for implementation in implementations:
            if implementation.name in failures:
                continue
            reason = check_can_start(implementation)
            if reason is not None:
                unrunnable[implementation.name] = reason
                self.error_console.print(
                    f"[red]Cannot run {escape(implementation.name)}: {escape(reason)}[/red]",
                    soft_wrap=True,
                )
        ready = tuple(
            implementation
            for implementation in implementations
            if implementation.name not in failures and implementation.name not in unrunnable
        )
        if not ready:
            reason = "built" if not unrunnable else "started"
            self.fail(
                f"No implementation could be {reason}, so nothing was run.", code=FAILURE_EXIT_CODE
            )
        return BuildOutcome(ready=ready, failures=failures, unrunnable=unrunnable)

    def check_json_path(self, path: Path | None) -> None:
        """Exit with a usage error if a report could not be written to ``path``.

        Call it before any work is done, so that a mistyped path does not cost
        the run. ``None`` means no report was asked for.
        """
        if path is None:
            return
        if path.is_dir():
            self.fail(f"--json needs the path of a file, but {path} is a directory.")
        ancestor = path.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            self.fail(f"--json cannot create {path}: {ancestor} is not a directory.")
        if not os.access(ancestor, os.W_OK | os.X_OK) or (
            path.exists() and not os.access(path, os.W_OK)
        ):
            self.fail(f"--json cannot write {path}: permission denied.")

    def check_directory_path(self, path: Path | None, option: str) -> None:
        """Exit with a usage error if ``path`` could not be a directory to write files in.

        ``path`` may not exist yet, as long as the directory above it can hold
        it; the option itself has already refused a file. ``None`` means the
        option was not given.
        """
        if path is None:
            return
        ancestor = path
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            self.fail(f"{option} cannot create {path}: {ancestor} is not a directory.")
        if not os.access(ancestor, os.W_OK | os.X_OK):
            self.fail(f"{option} cannot write in {path}: permission denied.")

    def write_json(self, path: Path, document: dict[str, Any], *, label: str) -> None:
        """Write ``document`` to ``path`` as JSON, creating directories, and say so.

        ``label`` names the report in the message, for example ``test report``.
        A file that cannot be written is a usage error.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, indent=2, sort_keys=True))
        except OSError as error:
            self.fail(f"Could not write the {label} to {path}: {error.strerror or error}")
        self.console.print(f"[green]Wrote {label} to {escape(str(path))}[/green]", soft_wrap=True)

    def _load_configuration(self, configuration_path: Path | None) -> Configuration | None:
        try:
            return discover_configuration(configuration_path, Path.cwd())
        except ConfigurationError as error:
            self.fail(f"Configuration error: {error}")
