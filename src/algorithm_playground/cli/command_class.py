"""The Typer command class that all commands use, for help and errors that read well.

Before version 0.27, Typer shows an argument in the help by the name of the
Python parameter (``problem_name``) next to its metavar (``PROBLEM``); later
versions show the metavar alone already. Some versions also show a suggestion
for a mistyped option as the repr of a tuple. This class shows the metavar alone
and repairs the message.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

from typer.core import TyperCommand

FIRST_TYPER_SHOWING_METAVARS_ALONE = (0, 27)


def _typer_version() -> tuple[int, int]:
    major, minor, *_ = version("typer").split(".")
    return int(major), int(minor)


class UserFacingCommand(TyperCommand):
    """A Typer command whose arguments are shown by their metavars and whose option errors are plain."""

    def __init__(self, *arguments: Any, **keywords: Any) -> None:
        super().__init__(*arguments, **keywords)
        if _typer_version() >= FIRST_TYPER_SHOWING_METAVARS_ALONE:
            return
        for parameter in self.params:
            if parameter.param_type_name == "argument" and parameter.metavar:
                parameter.opts = []

    # Click names these two parameters ``ctx`` and ``args`` and always passes them by position.
    def parse_args(  # ty: ignore[invalid-method-override]
        self, context: Any, arguments: list[str]
    ) -> list[str]:
        try:
            return super().parse_args(context, arguments)
        except Exception as failure:
            if not (hasattr(failure, "option_name") and hasattr(failure, "possibilities")):
                raise
            error: Any = failure
            possibilities = sorted(error.possibilities or ())
            suggestion = ""
            if len(possibilities) == 1:
                suggestion = f" Did you mean {possibilities[0]}?"
            elif possibilities:
                suggestion = f" Did you mean one of {', '.join(possibilities)}?"
            error.message = f"No such option: {error.option_name}.{suggestion}"
            error.possibilities = None
            raise
