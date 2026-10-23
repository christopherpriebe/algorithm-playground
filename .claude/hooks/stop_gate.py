"""Refuse to end a turn while the fast checks fail.

Claude Code runs this as a ``Stop`` hook. When the project has uncommitted
changes, it runs ruff, ty, and pytest from the project environment, plus
``cargo check`` and a ``uv sync`` (to rebuild the extension) when the
project has a ``Cargo.toml``. If any check fails, it answers with a block
decision whose reason carries the output, so Claude keeps working instead of
ending the turn. A failure identical to the one reported at the previous
stop lets the turn end, so a stuck turn cannot loop. The script always exits
0; decisions travel as JSON.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LAST_FAILURE_FILE = Path(".claude", ".stop-gate-last")
EXTENSION_SUFFIX = ".exe" if sys.platform == "win32" else ""
VOLATILE = re.compile(r"\b\d+(?:\.\d+)?s\b|\[gw\d+\]|0x[0-9a-f]+")


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


def _tree_is_clean(project_dir: Path) -> bool:
    """Report whether git sees no changes in the project.

    Args:
        project_dir: The directory to inspect.

    Returns:
        ``True`` when ``git status`` succeeds and prints nothing.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return status.returncode == 0 and not status.stdout.strip()


def _venv_tool(project_dir: Path, name: str) -> Path | None:
    """Locate a tool in the project environment.

    Args:
        project_dir: The project root.
        name: The executable name, such as ``ruff``.

    Returns:
        The path to the executable, or ``None`` when it is not installed.
    """
    venv = project_dir / os.environ.get("UV_PROJECT_ENVIRONMENT", ".venv")
    bin_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    candidate = bin_dir / f"{name}{EXTENSION_SUFFIX}"
    return candidate if candidate.is_file() else None


def _run(argv: list[str], project_dir: Path) -> str | None:
    """Run one check in the project.

    Args:
        argv: The command line.
        project_dir: The directory to run in.

    Returns:
        The command and its output when it failed, or ``None`` when it
        passed.
    """
    result = subprocess.run(
        argv,
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    shown = " ".join(
        Path(argv[0]).name if index == 0 else part for index, part in enumerate(argv)
    )
    return f"$ {shown}\n{result.stdout}{result.stderr}".rstrip()


def _python_checks(project_dir: Path) -> list[str]:
    """Run ruff and ty from the project environment.

    Args:
        project_dir: The project root.

    Returns:
        The failure reports, empty when everything passed.
    """
    reports: list[str] = []
    for tool, *args in (
        ("ruff", "format", "--check", "."),
        ("ruff", "check", "."),
        ("ty", "check"),
    ):
        executable = _venv_tool(project_dir, tool)
        if executable is None:
            reports.append(
                f"{tool} is not installed in the project environment; run `uv sync`."
            )
            continue
        report = _run([str(executable), *args], project_dir)
        if report is not None:
            reports.append(report)
    return reports


def _rust_checks(project_dir: Path) -> list[str]:
    """Check the Rust workspace and rebuild the extension.

    Args:
        project_dir: The project root.

    Returns:
        The failure reports, empty when the crates compile and the
        extension was rebuilt. A failed ``cargo check`` skips the rebuild.
    """
    report = _run(
        ["cargo", "check", "--workspace", "--all-targets", "--quiet"], project_dir
    )
    if report is not None:
        return [report]
    report = _run(["uv", "sync", "--frozen", "--quiet"], project_dir)
    return [] if report is None else [report]


def _test_checks(project_dir: Path) -> list[str]:
    """Run the test suite from the project environment.

    Args:
        project_dir: The project root.

    Returns:
        The failure report, empty when the tests passed.
    """
    pytest = _venv_tool(project_dir, "pytest")
    if pytest is None:
        return ["pytest is not installed in the project environment; run `uv sync`."]
    report = _run([str(pytest), "--quiet", "--exitfirst", "--no-header"], project_dir)
    return [] if report is None else [report]


def _is_repeat(project_dir: Path, reports: list[str]) -> bool:
    """Record the failure and report whether it matches the previous one.

    Args:
        project_dir: The project root holding the marker.
        reports: The failure reports; empty clears the marker.

    Returns:
        ``True`` when the same failures, ignoring timings and worker ids,
        were already reported at the last stop.
    """
    marker = project_dir / LAST_FAILURE_FILE
    if not reports:
        marker.unlink(missing_ok=True)
        return False
    normalized = VOLATILE.sub("", "\n".join(reports))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    try:
        previous = marker.read_text(encoding="utf-8").strip()
    except OSError:
        previous = ""
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest, encoding="utf-8")
    return digest == previous


def main() -> int:
    """Run the checks and block the stop while they fail.

    Returns:
        Always ``0``; the decision travels as JSON on stdout.
    """
    payload = _payload()
    project_dir = _project_dir(payload)
    if _tree_is_clean(project_dir):
        return 0
    reports = _python_checks(project_dir)
    if (project_dir / "Cargo.toml").is_file():
        rust_reports = _rust_checks(project_dir)
        reports.extend(rust_reports)
        if rust_reports:
            reports.append("pytest skipped: the extension could not be rebuilt.")
            rust_reports = None
    else:
        rust_reports = []
    if rust_reports is not None:
        reports.extend(_test_checks(project_dir))
    if not reports:
        return 0
    if _is_repeat(project_dir, reports):
        sys.stdout.write(
            json.dumps(
                {
                    "systemMessage": "Stop gate: the same failures as at the previous stop remain; "
                    "letting the turn end."
                }
            )
        )
        return 0
    sys.stdout.write(
        json.dumps(
            {
                "decision": "block",
                "reason": "Stop gate failed. Fix these before finishing:\n\n"
                + "\n\n".join(reports),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
