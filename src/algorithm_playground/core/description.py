"""Shortening values for failure reports: :func:`truncate_text` and :func:`describe_sequence`.

A failure report shows an input and an output as text of limited length. These
are the building blocks of a problem's ``describe_input`` and
``describe_output`` hooks: the first cuts any text, the second knows how to
show a long sequence, optionally around the position that matters.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

ELLIPSIS = "..."
_SEPARATOR = ", "
_SHORTEST_ITEM_CHARACTERS = 1 + len(_SEPARATOR)


def truncate_text(text: str, limit: int) -> str:
    """Shorten ``text`` to at most ``limit`` characters, ending in ``...`` when it was cut."""
    if len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return text[: max(limit, 0)]
    return text[: limit - len(ELLIPSIS)] + ELLIPSIS


def describe_sequence(values: Sequence[Any], limit: int, focus: int | None = None) -> str:
    """Show ``values`` as ``[a, b, c]`` in at most about ``limit`` characters.

    A sequence that fits is shown whole. A longer one shows as many items as
    fit, followed by ``...`` and its length: ``[3, 1, 4, ...] (1000 values)``.
    With ``focus``, the position that matters (for example the first element of
    an output that is wrong), the shown items are a window around that
    position instead of the start, and the text says which indices they are:
    ``[..., 7, 8, 9, ...] (1000 values, indices 497 to 503 shown)``. A
    ``focus`` outside the sequence is moved to its nearest end.
    """
    count = len(values)
    if count * _SHORTEST_ITEM_CHARACTERS <= limit + len(_SEPARATOR):
        whole = f"[{_SEPARATOR.join(repr(item) for item in values)}]"
        if len(whole) <= limit:
            return whole
    if count == 0:
        return truncate_text("[]", limit)
    window = _Window(values, 0 if focus is None else min(max(focus, 0), count - 1))
    if len(window.text()) > limit:
        return truncate_text(window.text(), limit)
    growing = True
    while growing:
        growing = False
        for toward_start in (True, False) if focus is not None else (False,):
            growing |= window.grow(toward_start, limit)
    return window.text()


class _Window:
    """The items ``low`` up to ``high`` of a sequence, shown with what is left out."""

    def __init__(self, values: Sequence[Any], centre: int) -> None:
        self._values = values
        self._low = centre
        self._high = centre + 1
        self._pieces = [repr(values[centre])]

    def text(self) -> str:
        count = len(self._values)
        before = f"{ELLIPSIS}{_SEPARATOR}" if self._low > 0 else ""
        after = f"{_SEPARATOR}{ELLIPSIS}" if self._high < count else ""
        where = ""
        if self._low > 0:
            last = self._high - 1
            where = (
                f", index {last} shown"
                if self._low == last
                else f", indices {self._low} to {last} shown"
            )
        return f"[{before}{_SEPARATOR.join(self._pieces)}{after}] ({count} values{where})"

    def grow(self, toward_start: bool, limit: int) -> bool:
        """Add the next item on one side if the text still fits; say whether it did."""
        position = self._low - 1 if toward_start else self._high
        if not 0 <= position < len(self._values):
            return False
        piece = repr(self._values[position])
        before = (self._low, self._high, list(self._pieces))
        if toward_start:
            self._low = position
            self._pieces.insert(0, piece)
        else:
            self._high = position + 1
            self._pieces.append(piece)
        if len(self.text()) <= limit:
            return True
        self._low, self._high, self._pieces = before
        return False
