"""Show usage in the status line and record it for the usage guard.

Claude Code runs this as the ``statusLine`` command, passing session state as
JSON on stdin after every assistant message. The script prints a one-line
status and writes the ``rate_limits`` block, which only claude.ai
subscription sessions carry, to ``.claude/usage.json`` in the project. The
usage guard and marathon driver hooks read that file.
"""

import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

USAGE_FILE = Path(".claude", "usage.json")
WINDOWS = (("five_hour", "5h"), ("seven_day", "7d"))


def _payload() -> dict[str, object]:
    """Read the status line payload from stdin.

    Returns:
        The decoded JSON object, or an empty dict if stdin is not a JSON
        object.
    """
    try:
        payload: object = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items()}


def _project_dir(payload: dict[str, object]) -> Path:
    """Return the project root the session started in.

    Args:
        payload: The status line payload.

    Returns:
        ``workspace.project_dir`` when present, otherwise ``cwd``.
    """
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        project_dir = workspace.get("project_dir")
        if isinstance(project_dir, str) and project_dir:
            return Path(project_dir)
    return Path(str(payload.get("cwd", ".")))


def _write_usage(project_dir: Path, payload: dict[str, object]) -> None:
    """Record the rate-limit windows for the hooks, replacing atomically.

    A directory that cannot be written is ignored; the status line must
    never fail the session.

    Args:
        project_dir: The project root.
        payload: The status line payload.
    """
    rate_limits = payload.get("rate_limits")
    record = {
        "written_at": int(time.time()),
        "session_id": payload.get("session_id"),
        "rate_limits": rate_limits if isinstance(rate_limits, dict) else None,
    }
    target = project_dir / USAGE_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=target.parent, prefix="usage-", suffix=".tmp"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record))
        Path(temporary).replace(target)
    except OSError:
        return


def _window_label(rate_limits: dict[object, object], name: str) -> str | None:
    """Format one rate-limit window for the status line.

    Args:
        rate_limits: The ``rate_limits`` block of the payload.
        name: The window key, such as ``five_hour``.

    Returns:
        ``"23% (resets 14:05)"``, or ``None`` when the window is absent.
    """
    window = rate_limits.get(name)
    if not isinstance(window, dict):
        return None
    used = window.get("used_percentage")
    if not isinstance(used, int | float):
        return None
    label = f"{used:.0f}%"
    resets_at = window.get("resets_at")
    if isinstance(resets_at, int | float):
        local = datetime.fromtimestamp(resets_at, tz=UTC).astimezone()
        label += local.strftime(" (resets %H:%M)")
    return label


def main() -> int:
    """Write the usage record and print the status line.

    Returns:
        Always ``0``; the status line must never fail the session.
    """
    payload = _payload()
    _write_usage(_project_dir(payload), payload)
    parts: list[str] = []
    model = payload.get("model")
    if isinstance(model, dict) and isinstance(model.get("display_name"), str):
        parts.append(str(model["display_name"]))
    context = payload.get("context_window")
    if isinstance(context, dict) and isinstance(
        context.get("used_percentage"), int | float
    ):
        parts.append(f"ctx {context['used_percentage']:.0f}%")
    rate_limits = payload.get("rate_limits")
    if isinstance(rate_limits, dict):
        for name, short in WINDOWS:
            label = _window_label(rate_limits, name)
            if label is not None:
                parts.append(f"{short} {label}")
    sys.stdout.write(" | ".join(parts) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
