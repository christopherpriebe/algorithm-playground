"""Format a file after Claude edits it.

Claude Code runs this as a ``PostToolUse`` hook for ``Edit`` and ``Write``.
It reads the hook payload from stdin, finds the edited file, and runs the
matching formatter on that file alone: ruff from the project environment
for Python, ``rustfmt`` with the workspace edition for Rust. Other files are
ignored. The script always exits 0; a formatter error, usually a syntax
error, is handed to Claude as additional context.
"""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
EXTENSION_SUFFIX = ".exe" if sys.platform == "win32" else ""
DEFAULT_EDITION = "2024"


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


def _edited_file(payload: dict[str, object]) -> Path | None:
    """Return the file the tool call touched.

    Args:
        payload: The hook payload.

    Returns:
        The path from ``tool_input.file_path``, or ``None`` if absent.
    """
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    return Path(file_path) if isinstance(file_path, str) and file_path else None


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


def _rust_edition(project_dir: Path) -> str:
    """Read the Rust edition from the workspace manifest.

    Args:
        project_dir: The project root holding ``Cargo.toml``.

    Returns:
        The ``workspace.package.edition`` or ``package.edition`` value, or
        the template default when neither is readable.
    """
    try:
        with (project_dir / "Cargo.toml").open("rb") as manifest:
            data = tomllib.load(manifest)
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_EDITION
    for table in (
        data.get("workspace", {}).get("package", {}),
        data.get("package", {}),
    ):
        edition = table.get("edition") if isinstance(table, dict) else None
        if isinstance(edition, str):
            return edition
    return DEFAULT_EDITION


def _format(file: Path, project_dir: Path) -> str | None:
    """Run the formatter that matches the file.

    Args:
        file: The edited file.
        project_dir: The project root.

    Returns:
        An error message when formatting failed or the formatter is
        missing, otherwise ``None``.
    """
    if file.suffix in PYTHON_SUFFIXES:
        ruff = _venv_tool(project_dir, "ruff")
        if ruff is None:
            return "ruff is not installed in the project environment; run `uv sync`."
        argv = [str(ruff), "format", "--quiet", str(file)]
    elif file.suffix == ".rs" and (project_dir / "Cargo.toml").is_file():
        argv = ["rustfmt", "--edition", _rust_edition(project_dir), str(file)]
    else:
        return None
    try:
        result = subprocess.run(
            argv, cwd=project_dir, capture_output=True, text=True, check=False
        )
    except OSError as error:
        return f"{argv[0]} could not be run: {error}"
    if result.returncode == 0:
        return None
    return f"{Path(argv[0]).name} failed on {file}:\n{result.stdout}{result.stderr}".rstrip()


def main() -> int:
    """Format the edited file and report any formatter error to Claude.

    Returns:
        Always ``0``; feedback travels as JSON on stdout.
    """
    payload = _payload()
    file = _edited_file(payload)
    if file is None or not file.is_file():
        return 0
    error = _format(file, _project_dir(payload))
    if error is not None:
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": error,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
