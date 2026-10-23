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

from collections.abc import Callable
from typing import TypeVar

from algorithm_playground.core._description import describe_error
from algorithm_playground.core._errors import AlgorithmPlaygroundError

__all__ = ["HookError", "call_hook"]

HookResult = TypeVar("HookResult")


class HookError(AlgorithmPlaygroundError, RuntimeError):
    """A hook of a problem raised, or returned something that cannot be used.

    The message says what the hook raised, for example ``The problem's
    fixtures hook raised RuntimeError: out of memory.``

    Args:
        hook: The name of the hook.
        error: What the hook raised.

    Attributes:
        hook: The name of the hook.
    """

    def __init__(self, hook: str, error: BaseException) -> None:
        super().__init__(f"The problem's {hook} hook raised {describe_error(error)}.")
        self.hook = hook


def call_hook(hook: str, call: Callable[[], HookResult]) -> HookResult:
    """Call a hook and turn whatever it raises into a :class:`HookError`.

    ``call`` should do everything with the hook's return value that can fail
    (iterating it, reading its attributes), so that a hook that returns
    something unusable is reported as the hook's failure too.

    Args:
        hook: The name of the hook, used in the error message.
        call: A function that calls the hook and uses its result.

    Returns:
        What ``call`` returns.

    Raises:
        HookError: If ``call`` raises. A :class:`HookError` raised by ``call``
            passes through unchanged.
    """
    try:
        return call()
    except HookError:
        raise
    except Exception as error:
        # A problem comes from outside this package, so any exception is the hook's failure.
        raise HookError(hook, error) from error
