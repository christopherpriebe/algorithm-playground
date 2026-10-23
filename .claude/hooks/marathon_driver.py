"""Send Claude back to the next step of an active marathon run.

Claude Code runs this as a ``Stop`` hook. It looks for run ledgers under
``.claude/runs/`` whose frontmatter says ``status: active``. When one has
unchecked steps, the hook blocks the stop and names the next step, so a long
run keeps going without a human prompt. It nudges only when the run has
progressed since the previous nudge, so a stuck run ends the turn instead of
looping, and it stays quiet while the ledger is paused or done or while the
usage record is at or past the warn threshold. The script always exits 0;
the block decision travels as JSON.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

USAGE_FILE = Path(".claude", "usage.json")
LEDGER_DIR = Path(".claude", "runs")
WINDOWS = ("five_hour", "seven_day")
STATUS = re.compile(r"""^status:\s*["']?(\w+)["']?\s*$""", re.MULTILINE)
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
STEP = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\[([ xX])\]\s*(.+?)\s*$", re.MULTILINE)


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


def _usage_percent(project_dir: Path) -> float:
    """Return the highest percentage among the usage windows still counting.

    Args:
        project_dir: The project root holding ``.claude/usage.json``.

    Returns:
        The percentage, or ``0.0`` when no usage data exists.
    """
    try:
        record: object = json.loads(
            (project_dir / USAGE_FILE).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not isinstance(record, dict):
        return 0.0
    now = time.time()
    rate_limits = record.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return 0.0
    worst = 0.0
    for name in WINDOWS:
        window = rate_limits.get(name)
        if not isinstance(window, dict):
            continue
        used = window.get("used_percentage")
        resets_at = window.get("resets_at")
        if (
            isinstance(used, int | float)
            and isinstance(resets_at, int | float)
            and resets_at > now
        ):
            worst = max(worst, float(used))
    return worst


def _active_ledger(project_dir: Path) -> Path | None:
    """Find the ledger of an active run.

    Args:
        project_dir: The project root.

    Returns:
        The first ledger whose frontmatter says ``status: active``, or
        ``None``.
    """
    ledger_dir = project_dir / LEDGER_DIR
    if not ledger_dir.is_dir():
        return None
    for ledger in sorted(ledger_dir.glob("*.md")):
        frontmatter = FRONTMATTER.match(ledger.read_text(encoding="utf-8"))
        if frontmatter is None:
            continue
        status = STATUS.search(frontmatter.group(1))
        if status is not None and status.group(1).lower() == "active":
            return ledger
    return None


def _nudge_is_new(ledger: Path, completed: int) -> bool:
    """Record a nudge and report whether the run progressed since the last one.

    Args:
        ledger: The run ledger.
        completed: The number of checked steps now.

    Returns:
        ``True`` when this is the first nudge or more steps are checked than
        at the previous nudge.
    """
    marker = ledger.with_suffix(".nudge")
    try:
        previous = int(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = -1
    try:
        marker.write_text(str(completed), encoding="utf-8")
    except OSError:
        return False
    return completed > previous


def main() -> int:
    """Block the stop while an active run has steps left and is progressing.

    Returns:
        Always ``0``; a block decision travels as JSON on stdout.
    """
    warn_percent = _threshold("CLAUDE_USAGE_WARN_PERCENT", 80.0)
    payload = _payload()
    project_dir = _project_dir(payload)
    ledger = _active_ledger(project_dir)
    if ledger is None:
        return 0
    steps = STEP.findall(ledger.read_text(encoding="utf-8"))
    completed = sum(1 for mark, _ in steps if mark != " ")
    pending = [
        (number, text)
        for number, (mark, text) in enumerate(steps, start=1)
        if mark == " "
    ]
    if not pending:
        return 0
    if _usage_percent(project_dir) >= warn_percent:
        return 0
    if not _nudge_is_new(ledger, completed):
        return 0
    number, text = pending[0]
    sys.stdout.write(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    f"Marathon '{ledger.stem}': {completed} of {len(steps)} steps done and the run "
                    f"is active. Continue with step {number}: {text}\n"
                    "Finish it, run the gate, commit, check it off in the ledger, and keep going. "
                    "If you must stop (usage warning, blocked, or the user asked), set "
                    "`status: paused` in the ledger first so this hook stays quiet."
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
