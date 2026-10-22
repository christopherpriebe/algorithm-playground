"""Tests for stepping through frames: state, playback, auto-advance."""

import sys
from collections.abc import Iterable

import pytest
from rich.console import Console

from algorithm_playground.visualization import (
    Key,
    KeyPress,
    StepperOptions,
    StepperState,
    compute_next_state,
    parse_jump_target,
    step_through,
)
from helpers.stepping import JUMP, NEXT, PREVIOUS, QUIT, TOGGLE, build_frames


class ScriptedKeys:
    """A key source that plays a script: each read takes the next item (``None`` is a timeout)."""

    needs_enter = False

    def __init__(
        self, script: Iterable[KeyPress | None], lines: Iterable[str | None] = ()
    ) -> None:
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


class InterruptedKeys:
    """A key source whose reads are interrupted, as when the user presses Ctrl-C."""

    needs_enter = True

    def read_key(
        self,
        timeout_seconds: float | None,  # noqa: ARG002  key source protocol parameter
    ) -> KeyPress | None:
        message = "simulated Ctrl-C"
        raise KeyboardInterrupt(message)

    def read_line(
        self,
        prompt: str,  # noqa: ARG002  key source protocol parameter
    ) -> str | None:
        return None


def play(
    count: int,
    keys: ScriptedKeys,
    *,
    options: StepperOptions | None = None,
    notices: tuple[str, ...] = (),
) -> tuple[list[str], str]:
    """Run the stepper; return the bodies shown, in order, and the whole output."""
    console = Console(width=100, force_terminal=False, record=True)
    step_through(
        build_frames(count),
        options=options,
        notices=notices,
        key_source=keys,
        console=console,
    )
    text = console.export_text()
    return [line.strip() for line in text.splitlines() if line.startswith("body")], text


def build_state(index: int, *, playing: bool = False) -> StepperState:
    """Build a state on a frame of five, playing or paused."""
    return StepperState(index, 5, playing)


# These modules exist on POSIX only; the terminal tests are skipped elsewhere.
if sys.platform != "win32":
    pass


@pytest.mark.parametrize(
    ("index", "key_press", "expected_index"),
    [
        (2, NEXT, 3),
        (4, NEXT, 4),
        (2, PREVIOUS, 1),
        (0, PREVIOUS, 0),
    ],
    ids=["next", "next-at-last-frame", "previous", "previous-at-first-frame"],
)
def test_next_and_previous_stay_inside_the_frames(
    index: int, key_press: KeyPress, expected_index: int
) -> None:
    """Test next and previous move one frame and stop at the first and last frame."""
    state = compute_next_state(build_state(index), key_press)

    assert state.index == expected_index


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (1, build_state(2, playing=True)),
        (3, build_state(4, playing=False)),
    ],
    ids=["advances", "stops-playing-at-the-last-frame"],
)
def test_a_timeout_advances_and_stops_playing_at_the_last_frame(
    index: int, expected: StepperState
) -> None:
    """Test a timeout advances one frame and stops playback on reaching the last frame."""
    state = compute_next_state(build_state(index, playing=True), None)

    assert state == expected


@pytest.mark.parametrize(
    ("state", "expected_playing"),
    [
        (build_state(1, playing=True), False),
        (build_state(1), True),
        (build_state(4), False),
    ],
    ids=["pauses", "resumes", "cannot-resume-at-the-end"],
)
def test_space_pauses_and_resumes_but_cannot_resume_at_the_end(
    state: StepperState, *, expected_playing: bool
) -> None:
    """Test the toggle key pauses and resumes playback, but cannot resume at the last frame."""
    assert compute_next_state(state, TOGGLE).playing is expected_playing


def test_the_state_rejects_a_frame_that_does_not_exist() -> None:
    """Test a state on a frame outside the frames is rejected."""
    with pytest.raises(ValueError, match="out of range"):
        StepperState(5, 5, False)


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("1", 0),
        (" 5 ", 4),
        ("0", None),
        ("6", None),
        ("-1", None),
        ("two", None),
        ("", None),
    ],
)
def test_jump_targets_are_one_based_and_checked(text: str, target: int | None) -> None:
    """Test a jump target is read as a one-based frame number and checked against the count."""
    assert parse_jump_target(text, 5) == target


def test_next_and_previous_walk_the_frames_and_q_ends() -> None:
    """Test next and previous walk through the frames until quit."""
    shown, _ = play(5, ScriptedKeys([NEXT, NEXT, PREVIOUS, QUIT]))

    assert shown == ["body 1", "body 2", "body 3", "body 2"]


def test_the_end_of_input_ends_the_stepper() -> None:
    """Test the stepper ends when the keys run out."""
    shown, _ = play(3, ScriptedKeys([NEXT]))

    assert shown == ["body 1", "body 2"]


def test_stepping_past_either_end_stays_on_the_edge_frame() -> None:
    """Test stepping past the first or last frame shows the edge frame again."""
    shown, _ = play(2, ScriptedKeys([PREVIOUS, NEXT, NEXT, QUIT]))

    assert shown == ["body 1", "body 1", "body 2", "body 2"]


def test_jump_asks_for_a_frame_number() -> None:
    """Test jumping asks for a frame number and shows that frame."""
    keys = ScriptedKeys([JUMP, QUIT], lines=["4"])

    shown, _ = play(5, keys)

    assert shown == ["body 1", "body 4"]
    assert keys.prompts == ["jump to frame (1-5): "]


def test_a_jump_typed_with_its_number_does_not_ask() -> None:
    """Test a jump that comes with its frame number shows that frame without asking."""
    keys = ScriptedKeys([KeyPress(Key.JUMP, "3"), QUIT])

    shown, _ = play(5, keys)

    assert shown == ["body 1", "body 3"]
    assert keys.prompts == []


def test_a_bad_jump_target_keeps_the_frame_and_says_why() -> None:
    """Test a jump to a frame that does not exist keeps the frame and explains."""
    shown, text = play(5, ScriptedKeys([KeyPress(Key.JUMP, "9"), QUIT]))

    assert shown == ["body 1", "body 1"]
    assert "Could not use '9' as a frame number: use 1 to 5" in text


def test_the_end_of_input_while_asking_for_a_target_ends_the_stepper() -> None:
    """Test the stepper ends when the input ends while it asks for a frame number."""
    shown, _ = play(5, ScriptedKeys([JUMP, NEXT], lines=[None]))

    assert shown == ["body 1"]


def test_an_unknown_key_is_reported_and_changes_nothing() -> None:
    """Test an unknown key is reported and keeps the frame."""
    shown, text = play(3, ScriptedKeys([KeyPress(Key.UNKNOWN, "x"), QUIT]))

    assert shown == ["body 1", "body 1"]
    assert "Unknown key or command: 'x'" in text


def test_every_frame_shows_its_frame_number() -> None:
    """Test every frame is shown with its number out of the total."""
    _, text = play(2, ScriptedKeys([NEXT, QUIT]))

    assert "frame 1 / 2" in text
    assert "frame 2 / 2" in text


def test_every_frame_shows_its_caption() -> None:
    """Test every frame is shown with its caption."""
    _, text = play(2, ScriptedKeys([NEXT, QUIT]))

    assert "caption 1" in text
    assert "caption 2" in text


def test_every_frame_shows_the_notices() -> None:
    """Test the notices are shown with every frame."""
    _, text = play(2, ScriptedKeys([NEXT, QUIT]), notices=("Trace warning: look here",))

    assert text.count("Trace warning: look here") == 2


def test_the_legend_names_the_keys() -> None:
    """Test the legend names the keys that step and quit."""
    _, text = play(2, ScriptedKeys([QUIT]))

    assert "right arrow or n next" in text
    assert "q quit" in text


def test_no_frames_prints_a_message_and_the_notices() -> None:
    """Test a trace without frames prints a message and the notices."""
    console = Console(width=100, force_terminal=False, record=True)

    step_through(
        [],
        notices=["Trace warning: x"],
        key_source=ScriptedKeys([]),
        console=console,
    )

    text = console.export_text()
    assert "No frames to display." in text
    assert "Trace warning: x" in text


AUTO_ADVANCE_OPTIONS = StepperOptions(auto_advance=True, delay_milliseconds=40)


def test_it_advances_on_each_timeout_and_stops_at_the_last_frame() -> None:
    """Test playback advances on each timeout and stops at the last frame."""
    keys = ScriptedKeys([None, None, QUIT])

    shown, _ = play(3, keys, options=AUTO_ADVANCE_OPTIONS)

    assert shown == ["body 1", "body 2", "body 3"]
    assert keys.timeouts == [0.04, 0.04, None]


def test_space_pauses_and_resumes_playback() -> None:
    """Test the toggle key pauses playback and resumes it."""
    keys = ScriptedKeys([TOGGLE, TOGGLE, None, QUIT])

    shown, _ = play(5, keys, options=AUTO_ADVANCE_OPTIONS)

    assert shown == ["body 1", "body 1", "body 1", "body 2"]
    assert keys.timeouts == [0.04, None, 0.04, 0.04]


def test_the_status_shows_whether_playback_is_paused_or_playing() -> None:
    """Test the status line shows both paused and playing."""
    keys = ScriptedKeys([TOGGLE, TOGGLE, None, QUIT])

    _, text = play(5, keys, options=AUTO_ADVANCE_OPTIONS)

    assert "[paused]" in text
    assert "[playing]" in text


def test_a_manual_step_while_playing_keeps_playing() -> None:
    """Test stepping by hand during playback keeps playing."""
    keys = ScriptedKeys([NEXT, QUIT])

    play(5, keys, options=AUTO_ADVANCE_OPTIONS)

    assert keys.timeouts == [0.04, 0.04]


def test_without_auto_advance_there_is_no_timeout() -> None:
    """Test keys are read without a timeout when auto-advance is off."""
    keys = ScriptedKeys([NEXT, QUIT])

    play(3, keys)

    assert keys.timeouts == [None, None]


def test_without_auto_advance_there_is_no_status() -> None:
    """Test the status line is not shown when auto-advance is off."""
    _, text = play(3, ScriptedKeys([NEXT, QUIT]))

    assert "[paused]" not in text
    assert "[playing]" not in text


def test_a_single_frame_has_nothing_to_play() -> None:
    """Test a single frame is read without a timeout even with auto-advance on."""
    keys = ScriptedKeys([QUIT])

    play(1, keys, options=AUTO_ADVANCE_OPTIONS)

    assert keys.timeouts == [None]


def test_ctrl_c_ends_the_stepper_and_is_passed_on_to_the_caller() -> None:
    """Test an interrupt ends the stepper and reaches the caller."""
    console = Console(width=80, force_terminal=False, record=True)

    with pytest.raises(KeyboardInterrupt, match="simulated Ctrl-C"):
        step_through(build_frames(2), key_source=InterruptedKeys(), console=console)
