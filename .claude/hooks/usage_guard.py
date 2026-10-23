"""Keep Claude from starting work the usage window cannot finish.

Claude Code runs this as a ``PreToolUse`` hook for every tool. It reads the
``.claude/usage.json`` record that the status line script keeps current and
checks the 5-hour and weekly windows. At the warn threshold it attaches a
notice, at most once every few minutes, telling Claude to reach a checkpoint
and not start another step. At the stop threshold it denies every tool call
except what a checkpoint needs: reads, ``git status/diff/log/show/add/commit``
(plus ``stash`` and ``restore`` to shelve broken work), edits to the run
ledger under ``.claude/runs/``, task-list and scheduling tools, and loading
tool schemas. A reading is trusted until its window resets, since usage within
a window only rises. Sessions without usage data, such as API-key sessions,
pass through. The script always exits 0; decisions travel as JSON.

Thresholds come from ``CLAUDE_USAGE_WARN_PERCENT`` and
``CLAUDE_USAGE_STOP_PERCENT`` when set.
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

NOTICE_INTERVAL_SECONDS = 5 * 60
USAGE_FILE = Path(".claude", "usage.json")
NOTICE_FILE = Path(".claude", "usage-notice")
LEDGER_DIR = Path(".claude", "runs")
WINDOWS = (("five_hour", "5-hour"), ("seven_day", "weekly"))
CHECKPOINT_TOOLS = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "ToolSearch",
        "AskUserQuestion",
        "CronCreate",
        "CronList",
        "CronDelete",
        "ScheduleWakeup",
        "TodoWrite",
        "TaskCreate",
        "TaskUpdate",
        "TaskList",
        "TaskGet",
    }
)
CHECKPOINT_TOOL_PREFIXES = ("mcp__ccd_turn__",)
CHECKPOINT_COMMAND = re.compile(
    r"^\s*git\s+(status|diff|log|show|add|commit|stash|restore)\b"
)
COMMAND_SEPARATOR = re.compile(r"&&|;|\n")
FORBIDDEN = re.compile(r"[|&$`<>]")


@dataclass(frozen=True, slots=True)
class Reading:
    """One usage window that has not reset yet."""

    label: str
    used: float
    resets_at: float


def _threshold(name: str, default: float) -> float:
    """Read a percentage threshold from the environment.

    Args:
        name: The environment variable.
        default: The value when the variable is unset or not a number.

    Returns:
        The threshold as a percentage.
    """
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _payload() -> dict[str, object]:
    """Read the hook payload from stdin.

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
    """Return the project root.

    Args:
        payload: The hook payload.

    Returns:
        ``CLAUDE_PROJECT_DIR`` when set, else the git top level of the
        payload's ``cwd``, else the nearest ancestor holding ``.claude/``,
        else that ``cwd``.
    """
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if env_dir:
        return Path(env_dir)
    cwd = Path(str(payload.get("cwd", ".")))
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    for candidate in (cwd, *cwd.resolve().parents):
        if (candidate / ".claude").is_dir():
            return candidate
    return cwd


def read_windows(project_dir: Path) -> list[Reading]:
    """Load the usage windows that are still counting.

    Args:
        project_dir: The project root holding ``.claude/usage.json``.

    Returns:
        The windows with a numeric percentage and a reset time in the
        future, or an empty list when the record is missing or has no
        rate-limit data.
    """
    try:
        record: object = json.loads(
            (project_dir / USAGE_FILE).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(record, dict):
        return []
    now = time.time()
    rate_limits = record.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return []
    readings: list[Reading] = []
    for name, label in WINDOWS:
        window = rate_limits.get(name)
        if not isinstance(window, dict):
            continue
        used = window.get("used_percentage")
        resets_at = window.get("resets_at")
        if not isinstance(used, int | float) or not isinstance(resets_at, int | float):
            continue
        if resets_at > now:
            readings.append(Reading(label, float(used), float(resets_at)))
    return readings


def describe(reading: Reading) -> str:
    """Describe a window for Claude.

    Args:
        reading: The window.

    Returns:
        ``"5-hour window at 83%, resets at 14:05 (in 1h02m)"``.
    """
    local = datetime.fromtimestamp(reading.resets_at, tz=UTC).astimezone()
    remaining = max(0, int(reading.resets_at - time.time()))
    hours, minutes = divmod(remaining // 60, 60)
    return (
        f"{reading.label} window at {reading.used:.0f}%, "
        f"resets at {local:%H:%M} (in {hours}h{minutes:02d}m)"
    )


def _is_checkpoint_command(command: object) -> bool:
    """Report whether a shell command only performs checkpoint git calls.

    Args:
        command: The ``command`` field of a Bash tool call.

    Returns:
        ``True`` when each ``&&``, ``;`` or newline-separated segment is a
        checkpoint git subcommand and the command uses no pipes,
        redirection, substitution, or backgrounding.
    """
    if not isinstance(command, str):
        return False
    segments = [part for part in COMMAND_SEPARATOR.split(command) if part.strip()]
    return bool(segments) and all(
        CHECKPOINT_COMMAND.match(part) and not FORBIDDEN.search(part)
        for part in segments
    )


def _is_ledger_edit(file_path: object, project_dir: Path) -> bool:
    """Report whether an edit targets the run ledger directory.

    Args:
        file_path: The ``file_path`` field of an Edit or Write tool call.
        project_dir: The project root.

    Returns:
        ``True`` when the path resolves under ``.claude/runs/``.
    """
    if not isinstance(file_path, str):
        return False
    ledger_dir = (project_dir / LEDGER_DIR).resolve()
    return Path(file_path).resolve().is_relative_to(ledger_dir)


def _is_checkpoint_action(payload: dict[str, object], project_dir: Path) -> bool:
    """Report whether the tool call is one a checkpoint needs.

    Args:
        payload: The hook payload.
        project_dir: The project root.

    Returns:
        ``True`` for reads, checkpoint git commands, edits to the run
        ledger, task-list tools, scheduling tools, and schema loading.
    """
    tool_name = payload.get("tool_name")
    if tool_name in CHECKPOINT_TOOLS:
        return True
    if isinstance(tool_name, str) and tool_name.startswith(CHECKPOINT_TOOL_PREFIXES):
        return True
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    if tool_name == "Bash":
        return _is_checkpoint_command(tool_input.get("command"))
    if tool_name in {"Edit", "Write"}:
        return _is_ledger_edit(tool_input.get("file_path"), project_dir)
    return False


def _notice_due(project_dir: Path) -> bool:
    """Rate-limit the warning to one per interval.

    Args:
        project_dir: The project root holding the notice marker.

    Returns:
        ``True`` when a notice should be attached now.
    """
    marker = project_dir / NOTICE_FILE
    now = time.time()
    try:
        last = float(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = 0.0
    if now - last < NOTICE_INTERVAL_SECONDS:
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(now), encoding="utf-8")
    except OSError:
        return True
    return True


def _emit(output: dict[str, object]) -> None:
    """Send a hook response to Claude Code.

    Args:
        output: The ``hookSpecificOutput`` fields.
    """
    sys.stdout.write(
        json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **output}})
    )


def main() -> int:
    """Warn or block based on the usage windows.

    Returns:
        Always ``0``; decisions travel in the JSON output.
    """
    warn_percent = _threshold("CLAUDE_USAGE_WARN_PERCENT", 80.0)
    stop_percent = _threshold("CLAUDE_USAGE_STOP_PERCENT", 92.0)
    payload = _payload()
    project_dir = _project_dir(payload)
    readings = read_windows(project_dir)
    if not readings:
        return 0
    worst = max(readings, key=lambda reading: reading.used)
    if worst.used >= stop_percent:
        if _is_checkpoint_action(payload, project_dir):
            _emit(
                {
                    "additionalContext": (
                        f"Usage guard: {describe(worst)}. Only checkpoint actions are allowed: "
                        "finish the commit and the run ledger, schedule the resume, then end the turn."
                    )
                }
            )
            return 0
        _emit(
            {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Usage guard: {describe(worst)}. Do not start new work. Reach a checkpoint: "
                    "commit what passes (or `git stash` what doesn't), set the run ledger under "
                    ".claude/runs/ to paused with the reset time, schedule a one-shot resume with "
                    "CronCreate a few minutes after the reset, tell the user, and end the turn. "
                    "Allowed until then: Read, Grep, Glob, ToolSearch, "
                    "git status/diff/log/show/add/commit/stash/restore, edits under .claude/runs/, "
                    "CronCreate, and the task list."
                ),
            }
        )
        return 0
    if worst.used >= warn_percent and _notice_due(project_dir):
        _emit(
            {
                "additionalContext": (
                    f"Usage guard: {describe(worst)}. Finish the current step and reach a checkpoint "
                    "(gate, commit, ledger). Do not start another step; pause the run instead."
                )
            }
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
