"""Interactive stepper that walks through a sequence of "frames" in the terminal.

A frame is just a thunk that renders the current snapshot when called. The
stepper handles user input (next, previous, jump, quit) and optional
auto-advance with a configurable delay.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel


@dataclass(frozen=True)
class StepperOptions:
    """Tunables for the interactive stepper."""

    auto_advance: bool = False
    delay_milliseconds: int = 250


def step_through(
    frames: Sequence[Callable[[], None]],
    *,
    options: StepperOptions | None = None,
    header: str = "trace stepper",
) -> None:
    """Walk through ``frames`` interactively.

    Commands (each followed by Enter): ``n`` next, ``p`` previous,
    ``g <index>`` jump, ``q`` quit. When ``options.auto_advance`` is set,
    frames advance automatically with the configured delay until the last
    frame, after which the stepper waits for commands.
    """
    options = options or StepperOptions()
    console = Console()

    if not frames:
        console.print("[yellow]No frames to display.[/yellow]")
        return

    total = len(frames)
    index = 0
    while True:
        console.clear()
        console.print(
            Panel.fit(
                f"{header}  —  frame [bold]{index + 1}[/bold] / {total}",
                border_style="cyan",
            )
        )
        frames[index]()

        if options.auto_advance and index < total - 1:
            time.sleep(options.delay_milliseconds / 1000.0)
            index += 1
            continue

        console.print(
            "\n[dim]commands:[/dim] "
            "[bold]n[/bold]ext, "
            "[bold]p[/bold]revious, "
            "[bold]g[/bold] <index>, "
            "[bold]q[/bold]uit"
        )
        try:
            choice = console.input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return

        if choice in {"q", "quit", "exit"}:
            return
        if choice in {"", "n", "next"}:
            index = min(index + 1, total - 1)
            continue
        if choice in {"p", "previous"}:
            index = max(index - 1, 0)
            continue
        if choice.startswith("g"):
            target = _parse_jump_target(choice, total)
            if target is None:
                _warn(console, f"Could not parse jump target: {choice!r}")
                continue
            index = target
            continue
        _warn(console, f"Unknown command: {choice!r}")


def _parse_jump_target(choice: str, total: int) -> int | None:
    parts = choice.split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        requested = int(parts[1])
    except ValueError:
        return None
    if requested < 1 or requested > total:
        return None
    return requested - 1


def _warn(console: Console, message: str) -> None:
    console.print(f"[yellow]{message}[/yellow]")
    time.sleep(0.6)
