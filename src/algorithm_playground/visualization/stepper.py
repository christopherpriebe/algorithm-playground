"""Interactive stepper: plays back the frames a problem returns.

The stepper owns playback; a problem only supplies
:class:`~algorithm_playground.core.frames.Frame` objects. The state logic needs
no terminal: :class:`StepperState` and :func:`next_state` decide where the
stepper goes next. Key input comes from :mod:`algorithm_playground.visualization.keys`,
and :func:`step_through` draws the current frame and runs the loop.

Keys: right arrow or ``n`` next, left arrow or ``p`` previous, ``g`` jump to a
frame (it asks for the number), space pause or resume auto-advance, ``q`` quit.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from algorithm_playground.core.frames import Frame
from algorithm_playground.visualization.keys import (
    Key,
    KeyPress,
    KeySource,
    terminal_key_source,
)

__all__ = [
    "StepperOptions",
    "StepperState",
    "next_state",
    "parse_jump_target",
    "show_frame",
    "step_through",
]


def _print_notices(console: Console, notices: Sequence[str]) -> None:
    for notice in notices:
        console.print(Text(notice, style="yellow"))


def _read_jump_text(press: KeyPress, source: KeySource, total: int) -> str | None:
    """Return the frame number typed for a jump, asking for it when the key came without one."""
    if press.argument is not None:
        return press.argument
    else:
        return source.read_line(f"jump to frame (1-{total}): ")


def _build_legend(state: "StepperState", source: KeySource, options: "StepperOptions") -> str:
    if source.needs_enter:
        keys = "(then Enter) n next, p previous, g NUMBER jump, pause auto-advance, q quit"
    else:
        keys = (
            "right arrow or n next, left arrow or p previous, g jump, space pause or resume, q quit"
        )
    status = ("   [playing]" if state.playing else "   [paused]") if options.auto_advance else ""
    return f"\nkeys: {keys}{status}"


def _run(
    frames: Sequence[Frame], *, options: "StepperOptions", source: KeySource, screen: "_Screen"
) -> None:
    total = len(frames)
    state = StepperState(0, total, playing=options.auto_advance and total > 1)
    delay = options.delay_milliseconds / 1000.0
    message = ""
    while True:
        legend = _build_legend(state, source, options)
        screen.draw(frames[state.index], state, legend=legend, message=message)
        message = ""
        press = source.read_key(delay if state.playing else None)
        if press is None or press.key in (Key.NEXT, Key.PREVIOUS, Key.TOGGLE_PLAYBACK):
            state = next_state(state, press)
        elif press.key is Key.QUIT:
            return
        elif press.key is Key.UNKNOWN:
            message = f"Unknown key or command: {press.argument!r}"
        else:
            text = _read_jump_text(press, source, total)
            if text is None:
                return
            target = parse_jump_target(text, total)
            if target is None:
                message = f"Could not use {text.strip()!r} as a frame number: use 1 to {total}"
            else:
                state = replace(state, index=target)


@dataclass(frozen=True)
class StepperOptions:
    """Tunables for the interactive stepper."""

    auto_advance: bool = False
    delay_milliseconds: int = 250


@dataclass(frozen=True)
class StepperState:
    """Which frame is shown and whether auto-advance is running."""

    index: int
    total: int
    playing: bool

    def __post_init__(self) -> None:
        if not 0 <= self.index < self.total:
            raise ValueError(f"Frame {self.index} is out of range for {self.total} frames")

    @property
    def is_at_last_frame(self) -> bool:
        """Whether the last frame is the one shown."""
        return self.index == self.total - 1


@dataclass(frozen=True)
class _Screen:
    """Where the stepper draws and what stays on screen under every frame."""

    console: Console
    header: str
    notices: Sequence[str]

    def draw(self, frame: Frame, state: StepperState, *, legend: str, message: str) -> None:
        """Clear the screen and draw a frame under the header, with the key legend below it.

        Args:
            frame: The frame to show.
            state: Which frame it is.
            legend: The text that names the keys.
            message: A one-off notice shown after the standing ones; may be empty.
        """
        if self.console.is_terminal:
            self.console.clear()
        title = Text.assemble(
            f"{self.header}  \u2014  frame ", (str(state.index + 1), "bold"), f" / {state.total}"
        )
        self.console.print(Panel.fit(title, border_style="cyan"))
        show_frame(self.console, frame)
        self.console.print(Text(legend, style="dim"))
        _print_notices(self.console, [*self.notices, *([message] if message else [])])


def next_state(state: StepperState, press: KeyPress | None) -> StepperState:
    """Compute the state after a key press.

    Jumping and quitting are not handled here, because they need the caller.
    Auto-advance stops by itself when the last frame is reached.

    Args:
        state: The state before the key press.
        press: The key press, or ``None`` when the auto-advance delay passed.

    Returns:
        The state after the key press; the same state for a key not handled here.
    """
    key = None if press is None else press.key
    if key is None or key is Key.NEXT:
        index = min(state.index + 1, state.total - 1)
        return replace(state, index=index, playing=state.playing and index < state.total - 1)
    elif key is Key.PREVIOUS:
        return replace(state, index=max(state.index - 1, 0))
    elif key is Key.TOGGLE_PLAYBACK:
        return replace(state, playing=not state.playing and not state.is_at_last_frame)
    else:
        return state


def parse_jump_target(text: str, total: int) -> int | None:
    """Turn a frame number typed by a person into a frame index.

    Args:
        text: The text typed, counting frames from 1.
        total: The number of frames.

    Returns:
        The 0-based index of the frame, or ``None`` if the text is not a frame number.
    """
    try:
        requested = int(text.strip())
    except ValueError:
        return None
    if 1 <= requested <= total:
        return requested - 1
    else:
        return None


def show_frame(console: Console, frame: Frame) -> None:
    """Print one frame: its picture, then its caption.

    Args:
        console: Where to print.
        frame: The frame to show.
    """
    console.print(Text.from_ansi(frame.body))
    if frame.caption:
        console.print(Text(frame.caption, style="bold"))


def step_through(
    frames: Sequence[Frame],
    *,
    options: StepperOptions | None = None,
    header: str = "trace stepper",
    notices: Sequence[str] = (),
    key_source: KeySource | None = None,
    console: Console | None = None,
) -> None:
    """Walk through frames interactively.

    With ``options.auto_advance`` the stepper starts playing: it moves to the
    next frame after ``options.delay_milliseconds`` until the last frame, and
    a space pauses and resumes it. Ctrl-C ends the stepper with the terminal
    restored.

    Args:
        frames: The frames to show.
        options: How the stepper plays (default: no auto-advance).
        header: The title shown above every frame.
        notices: Warnings shown under every frame.
        key_source: Where key presses come from (default: adapts to the terminal).
        console: Where to print (default: a new console).

    Raises:
        KeyboardInterrupt: If the person presses Ctrl-C, so the caller decides
            the exit status.
    """
    options = options or StepperOptions()
    console = console or Console()
    if not frames:
        console.print("[yellow]No frames to display.[/yellow]")
        _print_notices(console, notices)
        return
    screen = _Screen(console, header, notices)
    try:
        if key_source is None:
            with terminal_key_source() as source:
                _run(frames, options=options, source=source, screen=screen)
        else:
            _run(frames, options=options, source=key_source, screen=screen)
    except KeyboardInterrupt:
        console.print()
        raise
