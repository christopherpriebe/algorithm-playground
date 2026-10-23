"""The setup every command shares: consoles, problems, implementations, and builds.

:class:`CommandContext` turns what the user typed into the objects a command
needs and reports each failure the same way: a message on standard error and
an exit code, ``2`` for a usage or configuration error and ``1`` for a build
failure or a command that cannot be started. The selection rules are
in :func:`~algorithm_playground.cli.select_implementations`; this module only
connects them to the terminal.
"""

import json
import os
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

from algorithm_playground.cli._dependencies import CommandDependencies
from algorithm_playground.cli._implementation_selection import (
    EnvironmentPolicy,
    SelectionError,
    discover_configuration,
    require_single,
    select_implementations,
)
from algorithm_playground.core._cases import AnyCase, CaseError, resolve_case
from algorithm_playground.core._configuration import (
    Configuration,
    ConfigurationError,
    check_configured_problems,
    load_configured_problems,
)
from algorithm_playground.core._dimensions import Size, parse_size
from algorithm_playground.core._hooks import HookError
from algorithm_playground.core._hooks import call_hook as call_guarded
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._problem import AnyProblem
from algorithm_playground.core._registry import (
    ProblemLoadError,
    ProblemSourceKind,
    UnknownProblemError,
    get_problem,
    load_entry_point_problems,
    load_problem_modules,
)
from algorithm_playground.core._report import JsonObject
from algorithm_playground.core._runner import (
    BuildError,
    build_implementations,
)

__all__ = [
    "FAILURE_EXIT_CODE",
    "USAGE_ERROR_EXIT_CODE",
    "BuildOutcome",
    "CommandContext",
]

USAGE_ERROR_EXIT_CODE = 2
FAILURE_EXIT_CODE = 1

HookResult = TypeVar("HookResult")


def _remove_digit_separators(text: str) -> str:
    """Remove the underscores from the values of a size, leaving the dimension names alone.

    Args:
        text: The text of a size.

    Returns:
        The text without underscores in the values.
    """
    parts = []
    for part in text.split(":"):
        label, separator, digits = part.partition("=")
        parts.append(
            f"{label}={digits.replace('_', '')}" if separator else part.replace("_", "")
        )
    return ":".join(parts)


def _nearest_existing_ancestor(path: Path) -> Path:
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    return ancestor


def _find_unrunnable(
    implementations: Sequence[Implementation],
    failures: Mapping[str, BuildError],
    check_can_start: Callable[[Implementation], str | None],
) -> dict[str, str]:
    """Map the name of each implementation that did not fail to build and cannot start to why.

    Returns:
        The reason, by implementation name, for each implementation that cannot start.
    """
    unrunnable: dict[str, str] = {}
    for implementation in implementations:
        if implementation.name in failures:
            continue
        reason = check_can_start(implementation)
        if reason is not None:
            unrunnable[implementation.name] = reason
    return unrunnable


def _describe_missing_readiness(unrunnable: Mapping[str, str]) -> str:
    """Say what no implementation could do: be built, or else be started.

    Returns:
        The sentence for the message.
    """
    reason = "started" if unrunnable else "built"
    return f"No implementation could be {reason}, so nothing was run."


@dataclass(frozen=True, slots=True)
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
        self,
        configuration_path: Path | None,
        problem_modules: Sequence[str] | None,
        *,
        dependencies: CommandDependencies,
    ) -> None:
        self.dependencies = dependencies
        self.console = Console()
        self.error_console = Console(stderr=True)
        self.warn(*load_entry_point_problems())
        self.configuration = self._load_configuration(configuration_path)
        self._load_problems(problem_modules or ())

    def warn(self, *messages: str) -> None:
        """Print each message as a warning on standard error.

        Args:
            *messages: The warnings, printed literally.
        """
        for message in messages:
            self.error_console.print(
                f"[yellow]Warning: {escape(message)}[/yellow]", soft_wrap=True
            )

    def fail(self, message: str, *, code: int = USAGE_ERROR_EXIT_CODE) -> NoReturn:
        """Print a message as an error on standard error and exit.

        Args:
            message: The error, printed literally.
            code: The exit code.

        Raises:
            typer.Exit: Always.
        """
        self.error_console.print(f"[red]{escape(message)}[/red]", soft_wrap=True)
        raise typer.Exit(code=code)

    def call_hook(self, hook: str, call: Callable[[], HookResult]) -> HookResult:
        """Call a hook of a problem; if it raises, name the hook and exit with the failure code.

        A problem comes from outside this package, so a bug in one of its hooks
        must end in a message that says which hook, not in a traceback.

        Args:
            hook: The name of the hook, for the message.
            call: Calls the hook and returns its result.

        Returns:
            What ``call`` returns.
        """
        try:
            return call_guarded(hook, call)
        except HookError as error:
            self.fail(str(error), code=FAILURE_EXIT_CODE)

    def get_problem(self, problem_name: str) -> AnyProblem:
        """Return the registered problem, or exit with a usage error if there is none.

        Args:
            problem_name: The name of the problem.

        Returns:
            The problem.
        """
        try:
            return get_problem(problem_name)
        except UnknownProblemError as error:
            self.fail(str(error))

    def parse_size(self, problem: AnyProblem, text: str) -> Size:
        """Parse the text of a size, or exit with a usage error if it does not fit the problem.

        Underscores between the digits of a value are accepted (``1_000``).

        Args:
            problem: The problem whose dimensions the size names.
            text: The text of the size: a plain number for a problem with one
                dimension, else ``name=N`` parts separated by colons.

        Returns:
            The size.
        """
        try:
            return parse_size(_remove_digit_separators(text), problem.dimensions)
        except CaseError as error:
            self.fail(str(error))

    def resolve_case(self, problem: AnyProblem, identifier: str) -> AnyCase:
        """Rebuild the case named by an identifier, or exit with a usage error if there is none.

        Args:
            problem: The problem the case belongs to.
            identifier: The identifier of the case.

        Returns:
            The case.
        """
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
        environment_policy: EnvironmentPolicy,
    ) -> tuple[Implementation, ...]:
        """Resolve the implementations to run, or exit with a usage error if that is impossible.

        Args:
            problem_name: The problem the implementations are for.
            selectors: The names or paths given as arguments.
            command_texts: The ``--command`` values.
            command_names: The ``--name`` values.
            environment_policy: The environment of implementations given as paths or
                command text.

        Returns:
            The implementations, with unique names.
        """
        try:
            return select_implementations(
                problem_name,
                selectors or (),
                command_texts or (),
                configuration=self.configuration,
                environment_policy=environment_policy,
                command_names=command_names or (),
            )
        except SelectionError as error:
            self.fail(str(error))

    def require_single(
        self, implementations: Sequence[Implementation], *, command_name: str
    ) -> Implementation:
        """Return the only selected implementation, or exit with a usage error if there is not exactly one.

        Args:
            implementations: The selected implementations.
            command_name: The command that needs exactly one, named in the error.

        Returns:
            The only implementation.
        """
        try:
            return require_single(implementations, command_name=command_name)
        except SelectionError as error:
            self.fail(str(error))

    def build_and_check(
        self, implementations: Sequence[Implementation]
    ) -> BuildOutcome:
        """Build the selected implementations, then check they can start.

        Each build is announced and each failure is printed once, with the
        build's output, on standard error. Then the command of each
        implementation is checked as :meth:`check_startable` does. Exit with the failure
        code when none is left to run.

        Args:
            implementations: The selected implementations.

        Returns:
            Which implementations are ready, failed to build, or cannot start.
        """
        failures = build_implementations(
            implementations,
            on_build_started=self._announce_build,
            on_build_failed=self._report_build_failure,
        )
        return self._check_startable(implementations, failures)

    def check_startable(
        self, implementations: Sequence[Implementation]
    ) -> BuildOutcome:
        """Check that the command of each implementation can start, without building.

        The check does not run anything, so that a program that was not found or
        is not executable is reported at once and not for every case. An
        implementation that cannot start is left out of
        :attr:`BuildOutcome.ready`. Exit with the failure code when none is left
        to run.

        Args:
            implementations: The selected implementations.

        Returns:
            Which implementations are ready and which cannot start.
        """
        return self._check_startable(implementations, {})

    def check_json_path(self, path: Path | None) -> None:
        """Check that a report could be written to a path, before any work is done.

        Exit with a usage error if the report could not be written.

        Args:
            path: The ``--json`` path, or ``None`` when no report was asked for.
        """
        if path is None:
            return
        if path.is_dir():
            self.fail(f"--json needs the path of a file, but {path} is a directory.")
        ancestor = _nearest_existing_ancestor(path.parent)
        if not ancestor.is_dir():
            self.fail(f"--json cannot create {path}: {ancestor} is not a directory.")
        if not os.access(ancestor, os.W_OK | os.X_OK) or (
            path.exists() and not os.access(path, os.W_OK)
        ):
            self.fail(f"--json cannot write {path}: permission denied.")

    def check_directory_path(self, path: Path | None, option: str) -> None:
        """Check that a path could be a directory to write files in.

        The path may not exist yet, as long as the directory above it can hold it;
        the option itself has already refused a file. Exit with a usage error if the
        directory could not be written.

        Args:
            path: The path given to the option, or ``None`` when it was not given.
            option: The name of the option, for the message.
        """
        if path is None:
            return
        ancestor = _nearest_existing_ancestor(path)
        if not ancestor.is_dir():
            self.fail(f"{option} cannot create {path}: {ancestor} is not a directory.")
        if not os.access(ancestor, os.W_OK | os.X_OK):
            self.fail(f"{option} cannot write in {path}: permission denied.")

    def write_json(self, path: Path, document: JsonObject, *, label: str) -> None:
        """Write a document to a path as JSON, creating directories, and say so.

        Exit with a usage error if the file cannot be written.

        Args:
            path: The file to write.
            document: The JSON document.
            label: Names the report in the message, for example ``test report``.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, indent=2, sort_keys=True))
        except OSError as error:
            self.fail(
                f"Could not write the {label} to {path}: {error.strerror or error}"
            )
        self.console.print(
            f"[green]Wrote {label} to {escape(str(path))}[/green]", soft_wrap=True
        )

    def _load_configuration(
        self, configuration_path: Path | None
    ) -> Configuration | None:
        try:
            return discover_configuration(configuration_path, Path.cwd())
        except ConfigurationError as error:
            self.fail(f"Configuration error: {error}")

    def _load_problems(self, problem_modules: Sequence[str]) -> None:
        try:
            if self.configuration is not None:
                self.warn(*load_configured_problems(self.configuration))
            self.warn(
                *load_problem_modules(
                    problem_modules,
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

    def _announce_build(self, implementation: Implementation) -> None:
        command = shlex.join(implementation.build_command or ())
        self.error_console.print(
            f"[dim]Building {escape(implementation.name)}: {escape(command)}[/dim]",
            soft_wrap=True,
        )

    def _report_build_failure(
        self, _implementation: Implementation, error: BuildError
    ) -> None:
        self.error_console.print(f"[red]{escape(str(error))}[/red]", soft_wrap=True)

    def _check_startable(
        self,
        implementations: Sequence[Implementation],
        failures: Mapping[str, BuildError],
    ) -> BuildOutcome:
        unrunnable = _find_unrunnable(
            implementations, failures, self.dependencies.check_can_start
        )
        for name, reason in unrunnable.items():
            self.error_console.print(
                f"[red]Cannot run {escape(name)}: {escape(reason)}[/red]",
                soft_wrap=True,
            )
        ready = tuple(
            implementation
            for implementation in implementations
            if implementation.name not in failures
            and implementation.name not in unrunnable
        )
        if not ready:
            self.fail(_describe_missing_readiness(unrunnable), code=FAILURE_EXIT_CODE)
        return BuildOutcome(ready=ready, failures=failures, unrunnable=unrunnable)
