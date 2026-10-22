"""Key presses and frames shared by the stepper and key tests."""

from algorithm_playground.core import Frame
from algorithm_playground.visualization import Key, KeyPress

NEXT = KeyPress(Key.NEXT)
PREVIOUS = KeyPress(Key.PREVIOUS)
JUMP = KeyPress(Key.JUMP)
TOGGLE = KeyPress(Key.TOGGLE_PLAYBACK)
QUIT = KeyPress(Key.QUIT)


def build_frames(count: int) -> list[Frame]:
    """Build ``count`` frames whose body and caption carry their one-based number."""
    return [
        Frame(f"body {number}", f"caption {number}") for number in range(1, count + 1)
    ]
