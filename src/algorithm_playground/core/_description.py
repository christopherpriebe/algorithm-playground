"""Describing values and errors for failure reports.

A failure report shows an input and an output as text of limited length.
:func:`truncate_text` and :func:`describe_sequence` are the building blocks of a
problem's ``describe_input`` and ``describe_output`` hooks: the first cuts any
text, the second knows how to show a long sequence, optionally around the
position that matters. :func:`describe_error` names an exception for use inside
a larger message.
"""

from collections.abc import Sequence

__all__ = ["ELLIPSIS", "describe_error", "describe_sequence", "truncate_text"]

ELLIPSIS = "..."
_SEPARATOR = ", "
_SHORTEST_ITEM_CHARACTERS = 1 + len(_SEPARATOR)


class _Window:
    """The items ``low`` up to ``high`` of a sequence, shown with what is left out."""

    def __init__(self, values: Sequence[object], centre: int) -> None:
        self._values = values
        self._low = centre
        self._high = centre + 1
        self._pieces = [repr(values[centre])]

    def text(self) -> str:
        """Return the window as text, with the count of values and the shown indices."""
        return self._render(self._low, self._high, self._pieces)

    def can_grow_toward_start(self, limit: int) -> bool:
        """Say whether the item before the window fits.

        Args:
            limit: The most characters the text may have.

        Returns:
            ``True`` if there is such an item and the text stays within ``limit``.
        """
        position = self._low - 1
        if position < 0:
            return False
        return (
            len(
                self._render(
                    position, self._high, [repr(self._values[position]), *self._pieces]
                )
            )
            <= limit
        )

    def can_grow_toward_end(self, limit: int) -> bool:
        """Say whether the item after the window fits.

        Args:
            limit: The most characters the text may have.

        Returns:
            ``True`` if there is such an item and the text stays within ``limit``.
        """
        position = self._high
        if position >= len(self._values):
            return False
        return (
            len(
                self._render(
                    self._low,
                    position + 1,
                    [*self._pieces, repr(self._values[position])],
                )
            )
            <= limit
        )

    def grow_toward_start(self) -> None:
        """Add the item before the window."""
        self._low -= 1
        self._pieces.insert(0, repr(self._values[self._low]))

    def grow_toward_end(self) -> None:
        """Add the item after the window."""
        self._pieces.append(repr(self._values[self._high]))
        self._high += 1

    def _render(self, low: int, high: int, pieces: Sequence[str]) -> str:
        count = len(self._values)
        before = f"{ELLIPSIS}{_SEPARATOR}" if low > 0 else ""
        after = f"{_SEPARATOR}{ELLIPSIS}" if high < count else ""
        where = ""
        if low > 0:
            last = high - 1
            where = (
                f", index {last} shown"
                if low == last
                else f", indices {low} to {last} shown"
            )
        return f"[{before}{_SEPARATOR.join(pieces)}{after}] ({count} values{where})"


def describe_error(error: BaseException) -> str:
    """Name an exception for use inside a larger message.

    Args:
        error: The exception to describe.

    Returns:
        ``ErrorType: message``.
    """
    return f"{type(error).__name__}: {error}"


def truncate_text(text: str, limit: int) -> str:
    """Shorten text to at most ``limit`` characters.

    Args:
        text: The text to shorten.
        limit: The most characters the result may have.

    Returns:
        ``text`` if it fits, otherwise its start followed by ``...``. A limit
        too small for the ``...`` cuts the text without it.
    """
    if len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return text[: max(limit, 0)]
    return text[: limit - len(ELLIPSIS)] + ELLIPSIS


def describe_sequence(
    values: Sequence[object], limit: int, focus: int | None = None
) -> str:
    """Show a sequence as ``[a, b, c]`` in at most about ``limit`` characters.

    A sequence that fits is shown whole. A longer one shows as many items as
    fit, followed by ``...`` and its length: ``[3, 1, 4, ...] (1000 values)``.
    With ``focus``, the shown items are a window around that position instead
    of the start, and the text says which indices they are:
    ``[..., 7, 8, 9, ...] (1000 values, indices 497 to 503 shown)``.

    Args:
        values: The sequence to show.
        limit: About the most characters the text may have.
        focus: The position that matters, for example the first element of an
            output that is wrong. A position outside the sequence is moved to
            the nearest end.

    Returns:
        The text.
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
        if focus is not None and window.can_grow_toward_start(limit):
            window.grow_toward_start()
            growing = True
        if window.can_grow_toward_end(limit):
            window.grow_toward_end()
            growing = True
    return window.text()
