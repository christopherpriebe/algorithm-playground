"""Enforce the tool boundaries of the project's subagent roles.

Claude Code runs this as a ``PreToolUse`` hook for ``Edit``, ``Write``, and
``Bash``. Inside a subagent the payload carries ``agent_type``; the hook
denies what the role's description promises it never does. The implementer
may not edit anything under ``tests/``. The reviewer may only run read-only
shell commands: git inspection, the project's checkers, and common file
viewers. Outside those roles the hook does nothing. It always exits 0;
decisions travel as JSON.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TESTS_DIR = "tests"
SEGMENT_SEPARATOR = re.compile(r"\|\||&&|\||;|\n")
FORBIDDEN = re.compile(r"[&$`<>]")
REVIEWER_COMMAND = re.compile(
    r"^\s*("
    r"git\s+(status|diff|log|show|blame)"
    r"|uv\s+run\s+(--frozen\s+)?(pytest|nox|ruff|ty|coverage)"
    r"|uv\s+tree"
    r"|cargo\s+(check|test|clippy|doc|tree|metadata)"
    r"|ls|cat|head|tail|wc|grep|rg|find|pwd|diff|tree|sort|uniq|cut|file|stat|du"
    r")\b"
)


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


def _deny(reason: str) -> None:
    """Deny the tool call with a reason Claude sees.

    Args:
        reason: Why the call is refused and what to do instead.
    """
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _edits_tests(payload: dict[str, object], project_dir: Path) -> bool:
    """Report whether an Edit or Write targets the tests directory.

    Args:
        payload: The hook payload.
        project_dir: The project root.

    Returns:
        ``True`` when ``tool_input.file_path`` resolves under ``tests/``.
    """
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str):
        return False
    return Path(file_path).resolve().is_relative_to((project_dir / TESTS_DIR).resolve())


def _is_read_only_command(payload: dict[str, object]) -> bool:
    """Report whether a Bash command only inspects.

    Args:
        payload: The hook payload.

    Returns:
        ``True`` when every pipeline segment starts with an allowed program
        and no redirection, substitution, or backgrounding appears.
    """
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    if not isinstance(command, str):
        return False
    segments = [part for part in SEGMENT_SEPARATOR.split(command) if part.strip()]
    return bool(segments) and all(
        REVIEWER_COMMAND.match(part) and not FORBIDDEN.search(part) for part in segments
    )


def main() -> int:
    """Apply the role's boundary to the tool call.

    Returns:
        Always ``0``; decisions travel as JSON on stdout.
    """
    payload = _payload()
    agent_type = payload.get("agent_type")
    tool_name = payload.get("tool_name")
    if agent_type == "implementer" and tool_name in {"Edit", "Write"}:
        if _edits_tests(payload, _project_dir(payload)):
            _deny(
                "The implementer never edits tests/. The tests are the contract. If one looks "
                "wrong or impossible to satisfy, put it under a Blocked heading in your report."
            )
    elif (
        agent_type == "reviewer"
        and tool_name == "Bash"
        and not _is_read_only_command(payload)
    ):
        _deny(
            "The reviewer is read-only. Allowed: git status/diff/log/show/blame, uv run "
            "pytest/nox/ruff/ty, cargo check/test/clippy/doc, and file viewers such as cat, "
            "grep, rg, find, head, tail, without redirection or substitution."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
