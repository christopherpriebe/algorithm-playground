"""Key input for the stepper: key presses, their decoding, and where they come from.

A :class:`KeySource` supplies :class:`KeyPress` values. On a terminal that is
:class:`TerminalKeySource`, which reads single keys (POSIX ``termios``, no
Enter needed); otherwise it is :class:`LineKeySource`, which reads one command
per line. :func:`decode_key` and :func:`decode_line` turn the bytes or the text
into key presses. Tests pass their own source.

Keys: right arrow or ``n`` next, left arrow or ``p`` previous, ``g`` jump to a
frame, space pause or resume auto-advance, ``q`` quit.
"""

from __future__ import annotations

import os
import select
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Protocol, TextIO

ESCAPE_WAIT_SECONDS = 0.05
MAXIMUM_ESCAPE_BYTES = 8
PASTE_WAIT_SECONDS = 0.5
MAXIMUM_PASTE_BYTES = 4096
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
MAXIMUM_SHOWN_PASTE_CHARACTERS = 20


class Key(Enum):
    """What a key press asks the stepper to do."""

    NEXT = "next"
    PREVIOUS = "previous"
    JUMP = "jump"
    TOGGLE_PLAYBACK = "toggle playback"
    QUIT = "quit"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
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
        """Wait for the next key press; return ``None`` once ``timeout_seconds`` pass.

        ``None`` as the timeout waits without limit. The end of the input is a
        quit key.
        """
        ...

    def read_line(self, prompt: str) -> str | None:
        """Show ``prompt`` and return the line typed in answer, or ``None`` at the end of input."""
        ...


def decode_key(data: bytes) -> KeyPress:
    """Decode the bytes of one key press from a terminal."""
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
    """Decode one command typed on a line: ``n``, ``p``, ``g`` or ``g NUMBER``, ``pause``, ``q``."""
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


class LineKeySource:
    """Reads one command per line from a text stream (standard input when it is not a terminal).

    Without single-key input there is nothing to interrupt a running
    auto-advance, so a timeout simply waits that long and expires.
    """

    needs_enter = True

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        if timeout_seconds is not None:
            time.sleep(timeout_seconds)
            return None
        line = self._stream.readline()
        return KeyPress(Key.QUIT) if line == "" else decode_line(line)

    def read_line(self, prompt: str) -> str | None:
        print(prompt, end="", flush=True)
        line = self._stream.readline()
        return None if line == "" else line


class TerminalKeySource:
    """Reads single key presses from a terminal without waiting for Enter.

    The terminal is switched to cbreak mode (no line buffering, no echo, Ctrl-C
    still works) between :meth:`__enter__` and :meth:`__exit__`, and restored
    afterwards.
    """

    needs_enter = False

    def __init__(self, stream: TextIO, terminal_modules: tuple[ModuleType, ModuleType]) -> None:
        self._stream = stream
        self._termios, self._tty = terminal_modules
        self._saved: list[object] | None = None

    def __enter__(self) -> TerminalKeySource:
        descriptor = self._stream.fileno()
        self._saved = self._termios.tcgetattr(descriptor)
        self._tty.setcbreak(descriptor)
        return self

    def __exit__(self, *_: object) -> None:
        self._restore()

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        descriptor = self._stream.fileno()
        if not select.select([descriptor], [], [], timeout_seconds)[0]:
            return None
        data = os.read(descriptor, 1)
        if not data:
            return KeyPress(Key.QUIT)
        if data == b"\x1b":
            data += self._read_escape_sequence(descriptor)
            if data == PASTE_START:
                return self._read_paste(descriptor)
        elif data[0] >= 0xC0:
            data += self._read_continuation_bytes(descriptor, data[0])
        return decode_key(data)

    def read_line(self, prompt: str) -> str | None:
        self._restore()
        try:
            print(prompt, end="", flush=True)
            line = self._stream.readline()
        finally:
            self._tty.setcbreak(self._stream.fileno(), self._termios.TCSANOW)
        return None if line == "" else line

    def _read_escape_sequence(self, descriptor: int) -> bytes:
        """Collect the bytes that follow an escape byte (an arrow key sends three in all)."""
        collected = b""
        while len(collected) < MAXIMUM_ESCAPE_BYTES:
            if not select.select([descriptor], [], [], ESCAPE_WAIT_SECONDS)[0]:
                break
            byte = os.read(descriptor, 1)
            collected += byte
            if not byte or (len(collected) == 1 and byte not in (b"[", b"O")):
                break
            if len(collected) > 1 and 0x40 <= byte[0] <= 0x7E:
                break
        return collected

    def _read_continuation_bytes(self, descriptor: int, lead: int) -> bytes:
        """Collect the rest of a multi-byte UTF-8 character whose first byte is ``lead``."""
        missing = 3 if lead >= 0xF0 else 2 if lead >= 0xE0 else 1
        collected = b""
        while len(collected) < missing:
            if not select.select([descriptor], [], [], ESCAPE_WAIT_SECONDS)[0]:
                break
            byte = os.read(descriptor, 1)
            if not byte:
                break
            collected += byte
        return collected

    def _read_paste(self, descriptor: int) -> KeyPress:
        """Swallow a bracketed paste whole; it is one unknown key, whatever it contains."""
        collected = b""
        while not collected.endswith(PASTE_END) and len(collected) < MAXIMUM_PASTE_BYTES:
            if not select.select([descriptor], [], [], PASTE_WAIT_SECONDS)[0]:
                break
            byte = os.read(descriptor, 1)
            if not byte:
                break
            collected += byte
        text = collected.removesuffix(PASTE_END).decode("utf-8", errors="replace")
        if len(text) > MAXIMUM_SHOWN_PASTE_CHARACTERS:
            text = text[:MAXIMUM_SHOWN_PASTE_CHARACTERS] + "..."
        return KeyPress(Key.UNKNOWN, f"pasted text {text}")

    def _restore(self) -> None:
        if self._saved is not None:
            self._termios.tcsetattr(self._stream.fileno(), self._termios.TCSADRAIN, self._saved)


@contextmanager
def terminal_key_source(stream: TextIO | None = None) -> Iterator[KeySource]:
    """Yield the best key source for ``stream`` (default: standard input).

    A terminal gets single-key input when the platform has ``termios``;
    anything else, such as a pipe, gets line input.
    """
    stream = stream if stream is not None else sys.stdin
    modules = _terminal_modules()
    if modules is not None and _is_terminal(stream):
        with TerminalKeySource(stream, modules) as source:
            yield source
    else:
        yield LineKeySource(stream)


def _terminal_modules() -> tuple[ModuleType, ModuleType] | None:
    try:
        import termios
        import tty
    except ImportError:
        return None
    return termios, tty


def _is_terminal(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except ValueError:
        return False
