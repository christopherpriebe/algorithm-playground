"""Key input for the stepper: key presses, their decoding, and where they come from.

A :class:`KeySource` supplies :class:`KeyPress` values. On a terminal that is
:class:`TerminalKeySource`, which reads single keys (POSIX ``termios``, no
Enter needed); otherwise it is :class:`LineKeySource`, which reads one command
per line. :func:`decode_key` and :func:`decode_line` turn the bytes or the text
into key presses. Tests pass their own source.

Keys: right arrow or ``n`` next, left arrow or ``p`` previous, ``g`` jump to a
frame, space pause or resume auto-advance, ``q`` quit.
"""

import os
import select
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Protocol, Self, TextIO

try:
    import termios
    import tty
except ImportError:  # termios and tty exist on POSIX only.
    termios = None
    tty = None

__all__ = [
    "ESCAPE_WAIT_SECONDS",
    "MAXIMUM_ESCAPE_BYTES",
    "MAXIMUM_PASTE_BYTES",
    "MAXIMUM_SHOWN_PASTE_CHARACTERS",
    "PASTE_END",
    "PASTE_START",
    "PASTE_WAIT_SECONDS",
    "Key",
    "KeyPress",
    "KeySource",
    "LineKeySource",
    "TerminalKeySource",
    "decode_key",
    "decode_line",
    "open_terminal_key_source",
]

ESCAPE_WAIT_SECONDS = 0.05
MAXIMUM_ESCAPE_BYTES = 8
PASTE_WAIT_SECONDS = 0.5
MAXIMUM_PASTE_BYTES = 4096
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
MAXIMUM_SHOWN_PASTE_CHARACTERS = 20
ESCAPE_FINAL_BYTE_MINIMUM = 0x40
ESCAPE_FINAL_BYTE_MAXIMUM = 0x7E
UTF8_MULTI_BYTE_LEAD_MINIMUM = 0xC0
UTF8_THREE_CONTINUATION_LEAD_MINIMUM = 0xF0
UTF8_TWO_CONTINUATION_LEAD_MINIMUM = 0xE0


def _is_terminal(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except ValueError:  # A closed stream is not a terminal.
        return False


def _read_byte(descriptor: int, wait_seconds: float) -> bytes:
    """Read one byte, waiting at most ``wait_seconds``; return nothing on a timeout or the end.

    Returns:
        The byte read, or no bytes on a timeout or at the end of the input.
    """
    if select.select([descriptor], [], [], wait_seconds)[0]:
        return os.read(descriptor, 1)
    return b""


def _is_end_of_escape_sequence(collected: bytes) -> bool:
    """Tell whether the last byte of ``collected`` completes the sequence after an escape byte.

    Returns:
        Whether the sequence is complete.
    """
    if len(collected) == 1:
        return collected not in (b"[", b"O")
    return ESCAPE_FINAL_BYTE_MINIMUM <= collected[-1] <= ESCAPE_FINAL_BYTE_MAXIMUM


def _read_escape_sequence(descriptor: int) -> bytes:
    """Collect the bytes that follow an escape byte (an arrow key sends three in all).

    Returns:
        The bytes that followed the escape byte.
    """
    collected = b""
    while len(collected) < MAXIMUM_ESCAPE_BYTES:
        byte = _read_byte(descriptor, ESCAPE_WAIT_SECONDS)
        if not byte:
            break
        collected += byte
        if _is_end_of_escape_sequence(collected):
            break
    return collected


def _count_continuation_bytes(lead: int) -> int:
    """Return how many bytes follow the first byte ``lead`` of a multi-byte UTF-8 character.

    Returns:
        The number of continuation bytes.
    """
    if lead >= UTF8_THREE_CONTINUATION_LEAD_MINIMUM:
        return 3
    if lead >= UTF8_TWO_CONTINUATION_LEAD_MINIMUM:
        return 2
    return 1


def _read_continuation_bytes(descriptor: int, lead: int) -> bytes:
    """Collect the rest of a multi-byte UTF-8 character whose first byte is ``lead``.

    Returns:
        The continuation bytes that arrived.
    """
    missing = _count_continuation_bytes(lead)
    collected = b""
    while len(collected) < missing:
        byte = _read_byte(descriptor, ESCAPE_WAIT_SECONDS)
        if not byte:
            break
        collected += byte
    return collected


def _read_paste_text(descriptor: int) -> str:
    """Swallow a bracketed paste whole and return its text, shortened when it is long.

    Returns:
        The pasted text, cut to ``MAXIMUM_SHOWN_PASTE_CHARACTERS`` characters.
    """
    collected = b""
    while not collected.endswith(PASTE_END) and len(collected) < MAXIMUM_PASTE_BYTES:
        byte = _read_byte(descriptor, PASTE_WAIT_SECONDS)
        if not byte:
            break
        collected += byte
    text = collected.removesuffix(PASTE_END).decode("utf-8", errors="replace")
    if len(text) > MAXIMUM_SHOWN_PASTE_CHARACTERS:
        return text[:MAXIMUM_SHOWN_PASTE_CHARACTERS] + "..."
    return text


class Key(Enum):
    """What a key press asks the stepper to do."""

    NEXT = "next"
    PREVIOUS = "previous"
    JUMP = "jump"
    TOGGLE_PLAYBACK = "toggle playback"
    QUIT = "quit"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class KeyPress:
    """A decoded key press.

    ``argument`` is the text that came with the key: the frame number of a
    line command such as ``g 12``, or the unrecognized text of an unknown key.
    """

    key: Key
    argument: str | None = None


class KeySource(Protocol):
    """Where the stepper gets its input from."""

    # Whether commands are confirmed with Enter (shown in the key legend).
    needs_enter: bool

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        """Wait for the next key press.

        The end of the input is a quit key.

        Args:
            timeout_seconds: How long to wait, or ``None`` to wait without limit.

        Returns:
            The key press, or ``None`` once the timeout has passed.
        """
        ...

    def read_line(self, prompt: str) -> str | None:
        """Show a prompt and read the line typed in answer.

        Args:
            prompt: The text to show before reading.

        Returns:
            The line, or ``None`` at the end of the input.
        """
        ...


class LineKeySource:
    """Reads one command per line from a text stream (standard input when it is not a terminal).

    Without single-key input there is nothing to interrupt a running
    auto-advance, so a timeout simply waits that long and expires.
    """

    needs_enter = True

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        """Wait for the next key press, which is a line typed.

        Args:
            timeout_seconds: How long to wait without reading, or ``None`` to read a line.

        Returns:
            The key press, ``None`` once a timeout has passed, or a quit key at the
            end of the input.
        """
        if timeout_seconds is not None:
            time.sleep(timeout_seconds)
            return None
        line = self._stream.readline()
        return KeyPress(Key.QUIT) if line == "" else decode_line(line)

    def read_line(self, prompt: str) -> str | None:
        """Show a prompt and read the line typed in answer.

        Args:
            prompt: The text to show before reading.

        Returns:
            The line, or ``None`` at the end of the input.
        """
        print(prompt, end="", flush=True)  # noqa: T201  the prompt is part of the interaction, not a log
        line = self._stream.readline()
        return None if line == "" else line


class TerminalKeySource:
    """Reads single key presses from a terminal without waiting for Enter.

    The terminal is switched to cbreak mode (no line buffering, no echo, Ctrl-C
    still works) while its ``with`` block runs, and restored
    afterwards.
    """

    needs_enter = False

    def __init__(
        self, stream: TextIO, terminal_modules: tuple[ModuleType, ModuleType]
    ) -> None:
        self._stream = stream
        self._termios, self._tty = terminal_modules
        self._saved: list[object] | None = None

    def __enter__(self) -> Self:
        descriptor = self._stream.fileno()
        self._saved = self._termios.tcgetattr(descriptor)
        self._tty.setcbreak(descriptor)
        return self

    def __exit__(self, *_: object) -> None:
        self._restore()

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        """Wait for the next key press, without waiting for Enter.

        Args:
            timeout_seconds: How long to wait, or ``None`` to wait without limit.

        Returns:
            The key press, ``None`` once the timeout has passed, or a quit key at the
            end of the input.
        """
        descriptor = self._stream.fileno()
        if not select.select([descriptor], [], [], timeout_seconds)[0]:
            return None
        data = os.read(descriptor, 1)
        if not data:
            return KeyPress(Key.QUIT)
        if data == b"\x1b":
            data += _read_escape_sequence(descriptor)
            if data == PASTE_START:
                return KeyPress(
                    Key.UNKNOWN, f"pasted text {_read_paste_text(descriptor)}"
                )
            return decode_key(data)
        if data[0] >= UTF8_MULTI_BYTE_LEAD_MINIMUM:
            return decode_key(data + _read_continuation_bytes(descriptor, data[0]))
        return decode_key(data)

    def read_line(self, prompt: str) -> str | None:
        """Show a prompt and read the line typed in answer, then return to single-key input.

        Args:
            prompt: The text to show before reading.

        Returns:
            The line, or ``None`` at the end of the input.
        """
        self._restore()
        try:
            print(prompt, end="", flush=True)  # noqa: T201  the prompt is part of the interaction, not a log
            line = self._stream.readline()
        finally:
            self._tty.setcbreak(self._stream.fileno(), self._termios.TCSANOW)
        return None if line == "" else line

    def _restore(self) -> None:
        if self._saved is not None:
            self._termios.tcsetattr(
                self._stream.fileno(), self._termios.TCSADRAIN, self._saved
            )


def decode_key(data: bytes) -> KeyPress:
    """Decode the bytes of one key press from a terminal.

    Args:
        data: The bytes the terminal sent for the key.

    Returns:
        The key press; an unknown key carries its text as the argument.
    """
    if data in (b"n", b"N", b"\r", b"\n", b"\x1b[C", b"\x1bOC"):
        return KeyPress(Key.NEXT)
    if data in (b"p", b"P", b"\x1b[D", b"\x1bOD"):
        return KeyPress(Key.PREVIOUS)
    if data in (b"g", b"G"):
        return KeyPress(Key.JUMP)
    if data == b" ":
        return KeyPress(Key.TOGGLE_PLAYBACK)
    if data in (b"q", b"Q", b"\x03", b"\x04"):
        return KeyPress(Key.QUIT)
    return KeyPress(Key.UNKNOWN, data.decode("utf-8", errors="replace"))


def decode_line(line: str) -> KeyPress:
    """Decode one command typed on a line: ``n``, ``p``, ``g`` or ``g NUMBER``, ``pause``, ``q``.

    Args:
        line: The text typed, with or without the line break.

    Returns:
        The key press; a jump carries the text after ``g`` as the argument, and
        an unknown command carries its text.
    """
    text = line.strip().lower()
    word, _, argument = text.partition(" ")
    if word in ("", "n", "next"):
        return KeyPress(Key.NEXT)
    if word in ("p", "previous"):
        return KeyPress(Key.PREVIOUS)
    if word in ("g", "jump"):
        return KeyPress(Key.JUMP, argument.strip() or None)
    if word in ("pause", "play", "resume", "space"):
        return KeyPress(Key.TOGGLE_PLAYBACK)
    if word in ("q", "quit", "exit"):
        return KeyPress(Key.QUIT)
    return KeyPress(Key.UNKNOWN, text)


@contextmanager
def open_terminal_key_source(stream: TextIO | None = None) -> Generator[KeySource]:
    """Provide the best key source for a stream.

    A terminal gets single-key input when the platform has ``termios``;
    anything else, such as a pipe, gets line input.

    Args:
        stream: The stream to read keys from (default: standard input).

    Yields:
        The key source, with the terminal restored when the block ends.
    """
    chosen_stream = stream if stream is not None else sys.stdin
    if termios is not None and tty is not None and _is_terminal(chosen_stream):
        with TerminalKeySource(chosen_stream, (termios, tty)) as source:
            yield source
    else:
        yield LineKeySource(chosen_stream)
