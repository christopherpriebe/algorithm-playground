"""The Typer command class that all commands use, for help and errors that read well.

Before version 0.27, Typer shows an argument in the help by the name of the
Python parameter (``problem_name``) next to its metavar (``PROBLEM``); later
versions show the metavar alone already. Some versions also show a suggestion
for a mistyped option as the repr of a tuple. This class shows the metavar alone
and repairs the message.
"""

from collections.abc import Sequence
from importlib.metadata import version
from typing import Any, Protocol, cast

from typer.core import TyperCommand

__all__ = ["ClickContext", "PassedArgument", "UserFacingCommand"]

FIRST_TYPER_SHOWING_METAVARS_ALONE = (0, 27)

# The context class of click is part of Typer, and its module changes between Typer versions
# (Typer 0.26 includes click), so it cannot be named here.
ClickContext = Any
# Arguments that go to TyperCommand unchanged; the parameters of TyperCommand differ between
# Typer versions.
PassedArgument = Any


def _typer_version() -> tuple[int, int]:
    major, minor, *_ = version("typer").split(".")
    return int(major), int(minor)


def _is_unknown_option_error(failure: Exception) -> bool:
    return hasattr(failure, "option_name") and hasattr(failure, "possibilities")


def _describe_suggestion(possibilities: Sequence[str]) -> str:
    if len(possibilities) == 1:
        return f" Did you mean {possibilities[0]}?"
    elif possibilities:
        return f" Did you mean one of {', '.join(possibilities)}?"
    else:
        return ""


class _UnknownOptionError(Protocol):
    """The parts of click's error for an unknown option that this module changes."""

    option_name: str
    possibilities: Sequence[str] | None
    message: str


class UserFacingCommand(TyperCommand):
    """A Typer command whose arguments are shown by their metavars and whose option errors are plain."""

    def __init__(self, *arguments: PassedArgument, **keywords: PassedArgument) -> None:
        super().__init__(*arguments, **keywords)
        if _typer_version() < FIRST_TYPER_SHOWING_METAVARS_ALONE:
            for parameter in self.params:
                if parameter.param_type_name == "argument" and parameter.metavar:
                    parameter.opts = []

    # Click names these two parameters ``ctx`` and ``args`` and always passes them by position.
    def parse_args(  # ty: ignore[invalid-method-override]
        self, context: ClickContext, arguments: list[str]
    ) -> list[str]:
        """Parse the arguments, explaining a mistyped option plainly.

        Args:
            context: The click context of the invocation.
            arguments: The command-line arguments to parse.

        Returns:
            The arguments that remain after parsing.
        """
        try:
            return super().parse_args(context, arguments)
        except Exception as failure:
            # The error for an unknown option is not one type that this module can name
            # across Typer versions, so recognize it by its attributes and re-raise the rest.
            if not _is_unknown_option_error(failure):
                raise
            error = cast(_UnknownOptionError, failure)
            suggestion = _describe_suggestion(sorted(error.possibilities or ()))
            error.message = f"No such option: {error.option_name}.{suggestion}"
            error.possibilities = None
            raise
