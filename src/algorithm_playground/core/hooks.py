"""Calling the hooks of a problem so that a hook that fails ends in an error that names it.

A problem comes from outside this package, so any of its hooks may raise. The
engines judge a run through ``verify`` and describe a failure through the
``describe`` hooks without ever letting a hook take them down. The hooks that
every command needs before anything runs (``fixtures``, ``generators``, and the
function of a generator) cannot be skipped, so they are called through
:func:`call_hook`, which turns whatever they raise into a :class:`HookError`.
The command-line front end reports that error and ends with the failure exit
code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from algorithm_playground.core._support import describe_error

HookResult = TypeVar("HookResult")


class HookError(RuntimeError):
    """A hook of a problem raised, or returned something that cannot be used.

    ``hook`` names the hook and the message says what it raised, for example
    ``The problem's fixtures hook raised RuntimeError: out of memory.``
    """

    def __init__(self, hook: str, error: BaseException) -> None:
        super().__init__(f"The problem's {hook} hook raised {describe_error(error)}.")
        self.hook = hook


def call_hook(hook: str, call: Callable[[], HookResult]) -> HookResult:
    """Return what ``call`` returns; raise :class:`HookError` naming ``hook`` if it raises.

    ``call`` should do everything with the hook's return value that can fail
    (iterating it, reading its attributes), so that a hook that returns
    something unusable is reported as the hook's failure too.
    """
    try:
        return call()
    except HookError:
        raise
    except Exception as error:
        raise HookError(hook, error) from error
