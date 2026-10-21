"""Tests for the stepper: its state logic, key decoding, key sources, and playback loop."""

from __future__ import annotations

import io
import os
import sys
import threading
from collections.abc import Iterable
from typing import Any

import pytest
from rich.console import Console

from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.visualization.keys import (
    Key,
    KeyPress,
    LineKeySource,
    TerminalKeySource,
    decode_key,
    decode_line,
    terminal_key_source,
)
from algorithm_playground.visualization.stepper import (
    StepperOptions,
    StepperState,
    next_state,
    parse_jump_target,
    step_through,
)

NEXT, PREVIOUS = KeyPress(Key.NEXT), KeyPress(Key.PREVIOUS)
JUMP, TOGGLE, QUIT = KeyPress(Key.JUMP), KeyPress(Key.TOGGLE_PLAYBACK), KeyPress(Key.QUIT)


class ScriptedKeys:
    """A key source that plays a script: each read takes the next item (``None`` is a timeout)."""

    needs_enter = False

    def __init__(self, script: Iterable[KeyPress | None], lines: Iterable[str | None] = ()) -> None:
        self._script = list(script)
        self._lines = list(lines)
        self.timeouts: list[float | None] = []
        self.prompts: list[str] = []

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        self.timeouts.append(timeout_seconds)
        return self._script.pop(0) if self._script else QUIT

    def read_line(self, prompt: str) -> str | None:
        self.prompts.append(prompt)
        return self._lines.pop(0) if self._lines else None


def frames(count: int) -> list[Frame]:
    return [Frame(f"body {number}", f"caption {number}") for number in range(1, count + 1)]


def play(
    count: int,
    keys: ScriptedKeys,
    *,
    options: StepperOptions | None = None,
    notices: tuple[str, ...] = (),
) -> tuple[list[str], str]:
    """Run the stepper; return the bodies shown, in order, and the whole output."""
    console = Console(width=100, force_terminal=False, record=True)
    step_through(frames(count), options=options, notices=notices, key_source=keys, console=console)
    text = console.export_text()
    return [line.strip() for line in text.splitlines() if line.startswith("body")], text


class TestNextState:
    def state(self, index: int, *, playing: bool = False) -> StepperState:
        return StepperState(index, 5, playing)

    def test_next_and_previous_stay_inside_the_frames(self) -> None:
        assert next_state(self.state(2), NEXT).index == 3
        assert next_state(self.state(4), NEXT).index == 4
        assert next_state(self.state(2), PREVIOUS).index == 1
        assert next_state(self.state(0), PREVIOUS).index == 0

    def test_a_timeout_advances_and_stops_playing_at_the_last_frame(self) -> None:
        assert next_state(self.state(1, playing=True), None) == self.state(2, playing=True)
        assert next_state(self.state(3, playing=True), None) == self.state(4, playing=False)

    def test_space_pauses_and_resumes_but_cannot_resume_at_the_end(self) -> None:
        assert next_state(self.state(1, playing=True), TOGGLE).playing is False
        assert next_state(self.state(1), TOGGLE).playing is True
        assert next_state(self.state(4), TOGGLE).playing is False

    def test_the_state_rejects_a_frame_that_does_not_exist(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            StepperState(5, 5, False)


class TestDecoding:
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
    def test_single_keys(self, data: bytes, key: Key) -> None:
        assert decode_key(data).key is key

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("", KeyPress(Key.NEXT)),
            ("n", KeyPress(Key.NEXT)),
            ("Next", KeyPress(Key.NEXT)),
            ("p", KeyPress(Key.PREVIOUS)),
            ("g", KeyPress(Key.JUMP)),
            ("g 12", KeyPress(Key.JUMP, "12")),
            ("  jump   7 ", KeyPress(Key.JUMP, "7")),
            ("pause", KeyPress(Key.TOGGLE_PLAYBACK)),
            ("space", KeyPress(Key.TOGGLE_PLAYBACK)),
            ("q", KeyPress(Key.QUIT)),
            ("exit", KeyPress(Key.QUIT)),
            ("zzz", KeyPress(Key.UNKNOWN, "zzz")),
        ],
    )
    def test_commands_typed_on_a_line(self, line: str, expected: KeyPress) -> None:
        assert decode_line(line) == expected

    @pytest.mark.parametrize(
        ("text", "target"),
        [("1", 0), (" 5 ", 4), ("0", None), ("6", None), ("-1", None), ("two", None), ("", None)],
    )
    def test_jump_targets_are_one_based_and_checked(self, text: str, target: int | None) -> None:
        assert parse_jump_target(text, 5) == target


class TestPlayback:
    def test_next_and_previous_walk_the_frames_and_q_ends(self) -> None:
        shown, _ = play(5, ScriptedKeys([NEXT, NEXT, PREVIOUS, QUIT]))
        assert shown == ["body 1", "body 2", "body 3", "body 2"]

    def test_the_end_of_input_ends_the_stepper(self) -> None:
        shown, _ = play(3, ScriptedKeys([NEXT]))
        assert shown == ["body 1", "body 2"]

    def test_stepping_past_either_end_stays_on_the_edge_frame(self) -> None:
        shown, _ = play(2, ScriptedKeys([PREVIOUS, NEXT, NEXT, QUIT]))
        assert shown == ["body 1", "body 1", "body 2", "body 2"]

    def test_jump_asks_for_a_frame_number(self) -> None:
        keys = ScriptedKeys([JUMP, QUIT], lines=["4"])
        shown, _ = play(5, keys)
        assert shown == ["body 1", "body 4"]
        assert keys.prompts == ["jump to frame (1-5): "]

    def test_a_jump_typed_with_its_number_does_not_ask(self) -> None:
        keys = ScriptedKeys([KeyPress(Key.JUMP, "3"), QUIT])
        shown, _ = play(5, keys)
        assert shown == ["body 1", "body 3"]
        assert keys.prompts == []

    def test_a_bad_jump_target_keeps_the_frame_and_says_why(self) -> None:
        shown, text = play(5, ScriptedKeys([KeyPress(Key.JUMP, "9"), QUIT]))
        assert shown == ["body 1", "body 1"]
        assert "Could not use '9' as a frame number: use 1 to 5" in text

    def test_the_end_of_input_while_asking_for_a_target_ends_the_stepper(self) -> None:
        shown, _ = play(5, ScriptedKeys([JUMP, NEXT], lines=[None]))
        assert shown == ["body 1"]

    def test_an_unknown_key_is_reported_and_changes_nothing(self) -> None:
        shown, text = play(3, ScriptedKeys([KeyPress(Key.UNKNOWN, "x"), QUIT]))
        assert shown == ["body 1", "body 1"]
        assert "Unknown key or command: 'x'" in text

    def test_every_frame_shows_its_caption_the_frame_number_and_the_notices(self) -> None:
        _, text = play(2, ScriptedKeys([NEXT, QUIT]), notices=("Trace warning: look here",))
        assert "frame 1 / 2" in text and "frame 2 / 2" in text
        assert "caption 1" in text and "caption 2" in text
        assert text.count("Trace warning: look here") == 2

    def test_the_legend_names_the_keys(self) -> None:
        _, text = play(2, ScriptedKeys([QUIT]))
        assert "right arrow or n next" in text
        assert "q quit" in text

    def test_no_frames_prints_a_message_and_the_notices(self) -> None:
        console = Console(width=100, force_terminal=False, record=True)
        step_through([], notices=["Trace warning: x"], key_source=ScriptedKeys([]), console=console)
        text = console.export_text()
        assert "No frames to display." in text
        assert "Trace warning: x" in text


class TestAutoAdvance:
    options = StepperOptions(auto_advance=True, delay_milliseconds=40)

    def test_it_advances_on_each_timeout_and_stops_at_the_last_frame(self) -> None:
        keys = ScriptedKeys([None, None, QUIT])
        shown, _ = play(3, keys, options=self.options)
        assert shown == ["body 1", "body 2", "body 3"]
        assert keys.timeouts == [0.04, 0.04, None]

    def test_space_pauses_and_resumes_playback(self) -> None:
        keys = ScriptedKeys([TOGGLE, TOGGLE, None, QUIT])
        shown, text = play(5, keys, options=self.options)
        assert shown == ["body 1", "body 1", "body 1", "body 2"]
        assert keys.timeouts == [0.04, None, 0.04, 0.04]
        assert "[paused]" in text and "[playing]" in text

    def test_a_manual_step_while_playing_keeps_playing(self) -> None:
        keys = ScriptedKeys([NEXT, QUIT])
        play(5, keys, options=self.options)
        assert keys.timeouts == [0.04, 0.04]

    def test_without_auto_advance_there_is_no_timeout_and_no_status(self) -> None:
        keys = ScriptedKeys([NEXT, QUIT])
        _, text = play(3, keys)
        assert keys.timeouts == [None, None]
        assert "[paused]" not in text and "[playing]" not in text

    def test_a_single_frame_has_nothing_to_play(self) -> None:
        keys = ScriptedKeys([QUIT])
        play(1, keys, options=self.options)
        assert keys.timeouts == [None]


class TestLineKeySource:
    def test_reads_one_command_per_line_and_quits_at_the_end(self) -> None:
        source = LineKeySource(io.StringIO("n\np\ng 3\n\nq\n"))
        presses = [source.read_key(None) for _ in range(6)]
        assert presses == [NEXT, PREVIOUS, KeyPress(Key.JUMP, "3"), NEXT, QUIT, QUIT]

    def test_asks_for_a_line_and_reports_the_end_of_input(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = LineKeySource(io.StringIO("7\n"))
        assert source.read_line("which? ") == "7\n"
        assert source.read_line("which? ") is None
        assert capsys.readouterr().out == "which? which? "

    def test_a_timeout_waits_and_expires_without_reading(self) -> None:
        source = LineKeySource(io.StringIO("q\n"))
        assert source.read_key(0.0) is None
        assert source.read_key(None) == QUIT

    def test_a_non_terminal_gets_line_input(self) -> None:
        with terminal_key_source(io.StringIO("")) as source:
            assert isinstance(source, LineKeySource)
            assert source.needs_enter

    def test_a_whole_session_from_piped_commands(self) -> None:
        console = Console(width=100, force_terminal=False, record=True)
        step_through(
            frames(4),
            key_source=LineKeySource(io.StringIO("n\ng 4\np\nq\n")),
            console=console,
        )
        text = console.export_text()
        shown = [line.strip() for line in text.splitlines() if line.startswith("body")]
        assert shown == ["body 1", "body 2", "body 4", "body 3"]
        assert "then Enter" in text


posix_terminal = pytest.mark.skipif(
    sys.platform == "win32", reason="needs POSIX pseudo-terminals and termios"
)


@posix_terminal
class TestTerminalKeySource:
    @pytest.fixture
    def terminal(self) -> Iterable[tuple[int, TerminalKeySource]]:
        import pty
        import termios
        import tty

        master, slave = pty.openpty()
        stream = os.fdopen(slave, "r", closefd=False)
        source = TerminalKeySource(stream, (termios, tty))
        with source:
            yield master, source
        stream.close()
        os.close(master)
        os.close(slave)

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
        self, terminal: tuple[int, TerminalKeySource], typed: bytes, key: Key
    ) -> None:
        master, source = terminal
        os.write(master, typed)
        press = source.read_key(2.0)
        assert press is not None and press.key is key

    def test_a_key_after_an_arrow_is_not_swallowed_by_it(
        self, terminal: tuple[int, TerminalKeySource]
    ) -> None:
        master, source = terminal
        os.write(master, b"\x1b[Cp")
        keys = [source.read_key(2.0), source.read_key(2.0)]
        assert keys == [NEXT, PREVIOUS]

    def test_no_key_before_the_timeout_gives_none(
        self, terminal: tuple[int, TerminalKeySource]
    ) -> None:
        assert terminal[1].read_key(0.01) is None

    def test_a_line_can_be_read_while_keys_are_single(
        self, terminal: tuple[int, TerminalKeySource], capsys: pytest.CaptureFixture[str]
    ) -> None:
        master, source = terminal
        threading.Timer(0.1, os.write, (master, b"12\n")).start()
        assert source.read_line("frame? ") == "12\n"
        os.read(master, 100)  # the terminal echoed the typed line; leave nothing undrained
        os.write(master, b"n")
        assert source.read_key(2.0) == NEXT


@posix_terminal
class TestEscapeAndUnicodeKeys:
    """Keys that are more than one byte arrive as one key press, not as several."""

    @pytest.fixture
    def terminal(self) -> Iterable[tuple[int, TerminalKeySource]]:
        import pty
        import termios
        import tty

        master, slave = pty.openpty()
        stream = os.fdopen(slave, "r", closefd=False)
        with TerminalKeySource(stream, (termios, tty)) as source:
            yield master, source
        stream.close()
        os.close(master)
        os.close(slave)

    @staticmethod
    def presses(master: int, source: TerminalKeySource, typed: bytes) -> list[KeyPress]:
        os.write(master, typed)
        received = []
        while (press := source.read_key(0.05)) is not None:
            received.append(press)
        return received

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
        self, terminal: tuple[int, TerminalKeySource], typed: bytes, shown: str
    ) -> None:
        master, source = terminal
        assert self.presses(master, source, typed) == [KeyPress(Key.UNKNOWN, shown)]

    def test_a_bracketed_paste_is_one_unknown_press(
        self, terminal: tuple[int, TerminalKeySource]
    ) -> None:
        master, source = terminal
        presses = self.presses(master, source, b"\x1b[200~npq abc\x1b[201~")
        assert len(presses) == 1
        assert presses[0].key is Key.UNKNOWN
        assert presses[0].argument == "pasted text npq abc"

    def test_a_long_paste_is_shortened_in_the_message(
        self, terminal: tuple[int, TerminalKeySource]
    ) -> None:
        master, source = terminal
        presses = self.presses(master, source, b"\x1b[200~" + b"x" * 100 + b"\x1b[201~")
        assert presses == [KeyPress(Key.UNKNOWN, "pasted text " + "x" * 20 + "...")]

    def test_keys_after_a_paste_are_still_read(
        self, terminal: tuple[int, TerminalKeySource]
    ) -> None:
        master, source = terminal
        presses = self.presses(master, source, b"\x1b[200~nn\x1b[201~p")
        assert [press.key for press in presses] == [Key.UNKNOWN, Key.PREVIOUS]

    def test_a_multi_byte_key_in_a_session_gives_one_message(
        self, terminal: tuple[int, TerminalKeySource]
    ) -> None:
        master, source = terminal
        os.write(master, "é".encode())
        console = Console(width=100, force_terminal=False, record=True)
        step_through(frames(2), key_source=_ThenQuit(source), console=console)
        text = console.export_text()
        assert text.count("Unknown key or command") == 1
        assert "'é'" in text


class _ThenQuit:
    """Wrap a key source and end the session as soon as it has nothing more to read."""

    def __init__(self, source: TerminalKeySource) -> None:
        self._source = source
        self.needs_enter = source.needs_enter

    def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
        return self._source.read_key(0.05) or KeyPress(Key.QUIT)

    def read_line(self, prompt: str) -> str | None:
        return self._source.read_line(prompt)


def settings_of(descriptor: int) -> list[Any]:
    """The terminal settings of a descriptor, without the flag the kernel sets by itself.

    Leaving the single-key mode makes the kernel mark pending input to be retyped (PENDIN),
    which is not a setting anybody chose and says nothing about whether the mode came back.
    """
    import termios

    return settings_of_saved(termios.tcgetattr(descriptor))


def settings_of_saved(saved: list[Any]) -> list[Any]:
    import termios

    settings = list(saved)
    settings[3] = settings[3] & ~getattr(termios, "PENDIN", 0)
    return settings


@posix_terminal
class TestTerminalRestoration:
    @pytest.fixture
    def terminal(self) -> Iterable[tuple[int, int, list[Any]]]:
        import pty
        import termios

        master, slave = pty.openpty()
        mode = termios.tcgetattr(slave)
        mode[3] |= termios.ICANON | termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, mode)
        yield master, slave, termios.tcgetattr(slave)
        os.close(master)
        os.close(slave)

    @staticmethod
    def open_source(slave: int) -> tuple[TerminalKeySource, object]:
        import termios
        import tty

        stream = os.fdopen(slave, "r", closefd=False)
        return TerminalKeySource(stream, (termios, tty)), stream

    def test_the_mode_is_single_key_inside_and_restored_after_a_normal_exit(
        self, terminal: tuple[int, int, list[Any]]
    ) -> None:
        import termios

        _, slave, before = terminal
        source, _ = self.open_source(slave)
        with source:
            inside = termios.tcgetattr(slave)
            assert not inside[3] & termios.ICANON and not inside[3] & termios.ECHO
        assert settings_of(slave) == settings_of_saved(before)

    def test_the_mode_is_restored_after_a_frame_raises_inside_the_stepper(
        self, terminal: tuple[int, int, list[Any]]
    ) -> None:

        master, slave, before = terminal
        source, _ = self.open_source(slave)

        def build(position: int) -> Frame:
            if position == 1:
                raise RuntimeError("frame build failed")
            return Frame(str(position))

        with pytest.raises(RuntimeError, match="frame build failed"), source:
            os.write(master, b"n")
            step_through(
                FrameSequence(3, build),
                key_source=source,
                console=Console(width=80, force_terminal=False, record=True),
            )
        assert settings_of(slave) == settings_of_saved(before)

    def test_the_mode_is_restored_by_the_default_key_source_after_an_interrupt(
        self, terminal: tuple[int, int, list[Any]]
    ) -> None:

        _, slave, before = terminal
        stream = os.fdopen(slave, "r", closefd=False)

        def interrupt(frame_number: int) -> Frame:
            raise KeyboardInterrupt

        with (
            pytest.raises(KeyboardInterrupt),
            terminal_key_source(stream) as source,
        ):
            step_through(
                FrameSequence(2, interrupt),
                key_source=source,
                console=Console(width=80, force_terminal=False, record=True),
            )
        assert settings_of(slave) == settings_of_saved(before)


class TestInterrupt:
    def test_ctrl_c_ends_the_stepper_and_is_passed_on_to_the_caller(self) -> None:
        class Interrupted:
            needs_enter = True

            def read_key(self, timeout_seconds: float | None) -> KeyPress | None:
                raise KeyboardInterrupt

            def read_line(self, prompt: str) -> str | None:
                return None

        console = Console(width=80, force_terminal=False, record=True)
        with pytest.raises(KeyboardInterrupt):
            step_through(frames(2), key_source=Interrupted(), console=console)
