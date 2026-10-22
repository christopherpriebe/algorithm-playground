"""Tests for reading the keys the stepper reacts to."""

import io
import os
import sys
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from rich.console import Console

from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.visualization import (
    Key,
    KeyPress,
    LineKeySource,
    TerminalKeySource,
    decode_key,
    decode_line,
    open_terminal_key_source,
    step_through,
)
from helpers.stepping import NEXT, PREVIOUS, QUIT, build_frames

# These modules exist on POSIX only; the terminal tests are skipped elsewhere.
if sys.platform != "win32":
    import pty
    import termios
    import tty


# The settings termios reports mix integers with a list of control characters.
TerminalSettings = list[Any]


posix_terminal = pytest.mark.skipif(
    sys.platform == "win32", reason="needs POSIX pseudo-terminals and termios"
)


class QuitWhenIdleKeySource:
    """Wrap a key source and end the session as soon as it has nothing more to read."""

    def __init__(self, source: TerminalKeySource) -> None:
        self._source = source
        self.needs_enter = source.needs_enter

    def read_key(
        self,
        timeout_seconds: float | None,  # noqa: ARG002  key source protocol parameter
    ) -> KeyPress | None:
        return self._source.read_key(0.05) or KeyPress(Key.QUIT)

    def read_line(self, prompt: str) -> str | None:
        return self._source.read_line(prompt)


def play_piped_commands(commands: str) -> tuple[list[str], str]:
    """Run the stepper over four frames with commands read from text, one per line.

    Args:
        commands: The commands, separated by line breaks.

    Returns:
        The bodies shown, in order, and the whole output.
    """
    console = Console(width=100, force_terminal=False, record=True)
    step_through(
        build_frames(4),
        key_source=LineKeySource(io.StringIO(commands)),
        console=console,
    )
    text = console.export_text()
    return [line.strip() for line in text.splitlines() if line.startswith("body")], text


def collect_presses(
    master: int, source: TerminalKeySource, typed: bytes
) -> list[KeyPress]:
    """Type bytes on a terminal and collect every key press until it falls quiet."""
    os.write(master, typed)
    received = []
    while (press := source.read_key(0.05)) is not None:
        received.append(press)
    return received


def read_terminal_settings(descriptor: int) -> TerminalSettings:
    """Read the terminal settings of a descriptor, without the flag the kernel sets by itself.

    Leaving the single-key mode makes the kernel mark pending input to be retyped (PENDIN),
    which is not a setting anybody chose and says nothing about whether the mode came back.
    """
    return clear_pending_input_flag(termios.tcgetattr(descriptor))


def clear_pending_input_flag(saved: TerminalSettings) -> TerminalSettings:
    """Copy terminal settings with the kernel's pending input flag cleared."""
    settings = list(saved)
    settings[3] = settings[3] & ~getattr(termios, "PENDIN", 0)
    return settings


def open_key_source(slave: int) -> TerminalKeySource:
    """Open a key source on the slave end of a pseudo-terminal."""
    stream = os.fdopen(slave, "r", closefd=False)
    return TerminalKeySource(stream, (termios, tty))


@pytest.fixture
def terminal() -> Iterator[tuple[int, TerminalKeySource]]:
    """A key source reading a pseudo-terminal, with the master end to type on."""
    master, slave = pty.openpty()
    stream = os.fdopen(slave, "r", closefd=False)
    source = TerminalKeySource(stream, (termios, tty))
    with source:
        yield master, source
    stream.close()
    os.close(master)
    os.close(slave)


@pytest.fixture
def line_mode_terminal() -> Iterator[tuple[int, int, TerminalSettings]]:
    """A pseudo-terminal in line mode with echo: the master, the slave and its settings."""
    master, slave = pty.openpty()
    mode = termios.tcgetattr(slave)
    mode[3] |= termios.ICANON | termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, mode)
    yield master, slave, termios.tcgetattr(slave)
    os.close(master)
    os.close(slave)


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (b"n", Key.NEXT),
        (b"N", Key.NEXT),
        (b"\r", Key.NEXT),
        (b"\x1b[C", Key.NEXT),
        (b"\x1bOC", Key.NEXT),
        (b"p", Key.PREVIOUS),
        (b"\x1b[D", Key.PREVIOUS),
        (b"\x1bOD", Key.PREVIOUS),
        (b"g", Key.JUMP),
        (b" ", Key.TOGGLE_PLAYBACK),
        (b"q", Key.QUIT),
        (b"\x03", Key.QUIT),
        (b"\x04", Key.QUIT),
        (b"x", Key.UNKNOWN),
        (b"\x1b[A", Key.UNKNOWN),
        (b"\x1b", Key.UNKNOWN),
    ],
)
def test_a_single_key_decodes_to_its_key(data: bytes, key: Key) -> None:
    """Test the bytes of a key decode to the key they stand for."""
    assert decode_key(data).key is key


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", KeyPress(Key.NEXT)),
        ("n", KeyPress(Key.NEXT)),
        ("Next", KeyPress(Key.NEXT)),
        ("p", KeyPress(Key.PREVIOUS)),
        ("g", KeyPress(Key.JUMP)),
        ("g 12", KeyPress(Key.JUMP, argument="12")),
        ("  jump   7 ", KeyPress(Key.JUMP, argument="7")),
        ("pause", KeyPress(Key.TOGGLE_PLAYBACK)),
        ("space", KeyPress(Key.TOGGLE_PLAYBACK)),
        ("q", KeyPress(Key.QUIT)),
        ("exit", KeyPress(Key.QUIT)),
        ("zzz", KeyPress(Key.UNKNOWN, argument="zzz")),
    ],
)
def test_a_command_typed_on_a_line_decodes_to_its_key_press(
    line: str, expected: KeyPress
) -> None:
    """Test a command typed on a line decodes to the key press it stands for."""
    assert decode_line(line) == expected


def test_reads_one_command_per_line_and_quits_at_the_end() -> None:
    """Test each line is one command and the end of the input is a quit."""
    source = LineKeySource(io.StringIO("n\np\ng 3\n\nq\n"))

    presses = [source.read_key(None) for _ in range(6)]

    assert presses == [
        NEXT,
        PREVIOUS,
        KeyPress(Key.JUMP, argument="3"),
        NEXT,
        QUIT,
        QUIT,
    ]


def test_asking_for_a_line_returns_the_line_typed() -> None:
    """Test asking for a line returns the next line of the input."""
    source = LineKeySource(io.StringIO("7\n"))

    assert source.read_line("which? ") == "7\n"


def test_asking_for_a_line_reports_the_end_of_input() -> None:
    """Test asking for a line returns nothing once the input has ended."""
    source = LineKeySource(io.StringIO("7\n"))
    source.read_line("which? ")

    assert source.read_line("which? ") is None


def test_asking_for_a_line_prints_the_prompt_each_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test the prompt is printed every time a line is asked for."""
    source = LineKeySource(io.StringIO("7\n"))

    source.read_line("which? ")
    source.read_line("which? ")

    assert capsys.readouterr().out == "which? which? "


def test_a_timeout_waits_and_expires_without_reading() -> None:
    """Test a timeout expires without consuming any input."""
    source = LineKeySource(io.StringIO("q\n"))

    assert source.read_key(0.0) is None
    assert source.read_key(None) == QUIT


def test_a_non_terminal_gets_line_input() -> None:
    """Test a stream that is not a terminal gets a line key source."""
    with open_terminal_key_source(io.StringIO("")) as source:
        assert isinstance(source, LineKeySource)
        assert source.needs_enter


def test_a_whole_session_from_piped_commands() -> None:
    """Test a session driven by piped commands shows the frames the commands select."""
    shown, _ = play_piped_commands("n\ng 4\np\nq\n")

    assert shown == ["body 1", "body 2", "body 4", "body 3"]


def test_the_legend_tells_a_piped_session_to_press_enter() -> None:
    """Test the legend of a session driven by lines says commands need Enter."""
    _, text = play_piped_commands("q\n")

    assert "then Enter" in text


@posix_terminal
@pytest.mark.parametrize(
    ("typed", "key"),
    [
        (b"n", Key.NEXT),
        (b"\x1b[C", Key.NEXT),
        (b"\x1b[D", Key.PREVIOUS),
        (b"\x1bOD", Key.PREVIOUS),
        (b"g", Key.JUMP),
        (b" ", Key.TOGGLE_PLAYBACK),
        (b"q", Key.QUIT),
        (b"\x1b[A", Key.UNKNOWN),
    ],
)
def test_keys_arrive_without_enter(
    terminal: tuple[int, TerminalKeySource], typed: bytes, key: Key
) -> None:
    """Test a key typed on a terminal is read at once, without Enter."""
    master, source = terminal
    os.write(master, typed)

    press = source.read_key(2.0)

    assert press is not None
    assert press.key is key


@posix_terminal
def test_a_key_after_an_arrow_is_not_swallowed_by_it(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test a key typed right after an arrow key is read as its own key press."""
    master, source = terminal
    os.write(master, b"\x1b[Cp")

    keys = [source.read_key(2.0), source.read_key(2.0)]

    assert keys == [NEXT, PREVIOUS]


@posix_terminal
def test_no_key_before_the_timeout_gives_none(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test reading a key returns nothing when none arrives before the timeout."""
    _, source = terminal

    assert source.read_key(0.01) is None


@posix_terminal
@pytest.mark.usefixtures("capsys")
def test_a_line_can_be_read_while_keys_are_single(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test a line can be read between single key presses."""
    master, source = terminal
    # The line is typed once the source has switched to line mode.
    threading.Timer(0.1, os.write, (master, b"12\n")).start()

    line = source.read_line("frame? ")

    assert line == "12\n"
    os.read(master, 100)  # the terminal echoed the typed line; leave nothing undrained
    os.write(master, b"n")
    assert source.read_key(2.0) == NEXT


@posix_terminal
@pytest.mark.parametrize(
    ("typed", "shown"),
    [
        (b"\x1b", "\x1b"),
        (b"\x1bx", "\x1bx"),
        (b"\x1b[1;5C", "\x1b[1;5C"),
        (b"\x1b[3~", "\x1b[3~"),
        ("é".encode(), "é"),
        ("€".encode(), "€"),
        ("🙂".encode(), "🙂"),
    ],
    ids=[
        "lone escape",
        "escape and letter",
        "modified arrow",
        "delete",
        "e acute",
        "euro",
        "emoji",
    ],
)
def test_one_key_gives_one_unknown_press(
    terminal: tuple[int, TerminalKeySource], typed: bytes, shown: str
) -> None:
    """Test a key of several bytes gives one unknown key press that carries its text."""
    master, source = terminal

    presses = collect_presses(master, source, typed)

    assert presses == [KeyPress(Key.UNKNOWN, argument=shown)]


@posix_terminal
def test_a_bracketed_paste_is_one_unknown_press(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test a bracketed paste gives one unknown key press carrying the pasted text."""
    master, source = terminal

    presses = collect_presses(master, source, b"\x1b[200~npq abc\x1b[201~")

    assert len(presses) == 1
    assert presses[0].key is Key.UNKNOWN
    assert presses[0].argument == "pasted text npq abc"


@posix_terminal
def test_a_long_paste_is_shortened_in_the_message(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test a long paste is shortened with an ellipsis in the key press."""
    master, source = terminal

    presses = collect_presses(master, source, b"\x1b[200~" + b"x" * 100 + b"\x1b[201~")

    assert presses == [
        KeyPress(Key.UNKNOWN, argument="pasted text " + "x" * 20 + "...")
    ]


@posix_terminal
def test_keys_after_a_paste_are_still_read(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test keys typed after a paste are read as key presses of their own."""
    master, source = terminal

    presses = collect_presses(master, source, b"\x1b[200~nn\x1b[201~p")

    assert [press.key for press in presses] == [Key.UNKNOWN, Key.PREVIOUS]


@posix_terminal
def test_a_multi_byte_key_in_a_session_gives_one_message(
    terminal: tuple[int, TerminalKeySource],
) -> None:
    """Test a multi-byte key in a stepper session is reported as unknown once."""
    master, source = terminal
    os.write(master, "é".encode())
    console = Console(width=100, force_terminal=False, record=True)

    step_through(
        build_frames(2), key_source=QuitWhenIdleKeySource(source), console=console
    )

    text = console.export_text()
    assert text.count("Unknown key or command") == 1
    assert "'é'" in text


@posix_terminal
def test_the_mode_is_single_key_inside_the_block(
    line_mode_terminal: tuple[int, int, TerminalSettings],
) -> None:
    """Test the terminal has no line buffering and no echo inside the key source block."""
    _, slave, _ = line_mode_terminal

    with open_key_source(slave):
        inside = termios.tcgetattr(slave)

    assert not inside[3] & termios.ICANON
    assert not inside[3] & termios.ECHO


@posix_terminal
def test_the_mode_is_restored_after_a_normal_exit(
    line_mode_terminal: tuple[int, int, TerminalSettings],
) -> None:
    """Test the terminal settings come back when the key source block ends normally."""
    _, slave, before = line_mode_terminal

    with open_key_source(slave):
        pass

    assert read_terminal_settings(slave) == clear_pending_input_flag(before)


@posix_terminal
def test_the_mode_is_restored_after_a_frame_raises_inside_the_stepper(
    line_mode_terminal: tuple[int, int, TerminalSettings],
) -> None:
    """Test the terminal settings come back when building a frame raises."""
    master, slave, before = line_mode_terminal
    source = open_key_source(slave)

    def build_frame(position: int) -> Frame:
        if position == 1:
            message = "frame build failed"
            raise RuntimeError(message)
        return Frame(str(position))

    def press_next_and_step() -> None:
        os.write(master, b"n")
        step_through(
            FrameSequence(3, build_frame),
            key_source=source,
            console=Console(width=80, force_terminal=False, record=True),
        )

    with pytest.raises(RuntimeError, match="frame build failed"), source:
        press_next_and_step()

    assert read_terminal_settings(slave) == clear_pending_input_flag(before)


@posix_terminal
def test_the_mode_is_restored_by_the_default_key_source_after_an_interrupt(
    line_mode_terminal: tuple[int, int, TerminalSettings],
) -> None:
    """Test the default key source restores the terminal settings after an interrupt."""
    _, slave, before = line_mode_terminal
    stream = os.fdopen(slave, "r", closefd=False)

    def raise_interrupt(_frame_number: int) -> Frame:
        message = "simulated Ctrl-C"
        raise KeyboardInterrupt(message)

    with (
        pytest.raises(KeyboardInterrupt, match="simulated Ctrl-C"),
        open_terminal_key_source(stream) as source,
    ):
        step_through(
            FrameSequence(2, raise_interrupt),
            key_source=source,
            console=Console(width=80, force_terminal=False, record=True),
        )

    assert read_terminal_settings(slave) == clear_pending_input_flag(before)
