"""Top-level Typer application that wires up the subcommands."""

import functools
import sys
from collections.abc import Callable
from typing import Annotated, ParamSpec, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

# Importing the problems package triggers built-in problem registration.
import algorithm_playground.problems  # noqa: F401
from algorithm_playground import __version__
from algorithm_playground.cli.benchmark_command import benchmark_command
from algorithm_playground.cli.command_class import UserFacingCommand
from algorithm_playground.cli.context import FAILURE_EXIT_CODE
from algorithm_playground.cli.debug_command import debug_command
from algorithm_playground.cli.list_command import list_command
from algorithm_playground.cli.test_command import test_command
from algorithm_playground.core.hooks import HookError

__all__ = ["INTERRUPTED_EXIT_CODE", "app"]

INTERRUPTED_EXIT_CODE = 130

CommandParameters = ParamSpec("CommandParameters")
CommandResult = TypeVar("CommandResult")

app = typer.Typer(
    name="algorithm-playground",
    help=(
        "A learning and benchmarking sandbox for algorithms. Drive any command "
        "that implements a problem's binary I/O contract, and compare implementations."
    ),
    no_args_is_help=True,
    subcommand_metavar="COMMAND [ARGUMENTS]...",
    add_completion=False,
)


def _show_version(requested: bool) -> None:
    if requested:
        typer.echo(f"algorithm-playground {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Options that apply to every command."""


def _end_cleanly(
    command: Callable[CommandParameters, CommandResult],
) -> Callable[CommandParameters, CommandResult]:
    """Make a command end with a message and an exit code where it would end with a traceback.

    Ctrl-C ends it with exit code 130, the shell convention. A hook of the
    problem that raises where no command guarded it, for example while the cases
    are generated, ends it with the hook's name and exit code 1.

    Args:
        command: The command function to wrap.

    Returns:
        A function with the signature of ``command`` that exits instead of raising.
    """

    @functools.wraps(command)
    def run(
        *arguments: CommandParameters.args, **keywords: CommandParameters.kwargs
    ) -> CommandResult:
        try:
            return command(*arguments, **keywords)
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            raise typer.Exit(code=INTERRUPTED_EXIT_CODE) from None
        except HookError as error:
            Console(stderr=True).print(f"[red]{escape(str(error))}[/red]", soft_wrap=True)
            raise typer.Exit(code=FAILURE_EXIT_CODE) from None

    return run


app.command(
    "list",
    cls=UserFacingCommand,
    help=(
        "List all registered problems and the implementations in a configuration file, "
        "or the details of one problem."
    ),
)(_end_cleanly(list_command))
app.command(
    "test",
    cls=UserFacingCommand,
    help="Run implementations against a problem's fixtures and seeded random cases.",
)(_end_cleanly(test_command))
app.command(
    "benchmark",
    cls=UserFacingCommand,
    help="Benchmark and compare implementations on seeded random inputs across sizes.",
)(_end_cleanly(benchmark_command))
app.command(
    "debug",
    cls=UserFacingCommand,
    help="Step through an implementation's trace output for a single input.",
)(_end_cleanly(debug_command))


if __name__ == "__main__":
    app()
