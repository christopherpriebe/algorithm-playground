"""Helpers that write executable scripts, for tests that run real processes."""

import stat
import sys
import textwrap
from pathlib import Path

# The instrumented sorters, run as real processes by the tests that count operations.
INSTRUMENTED_SORT = Path(__file__).resolve().parent / "instrumented_sort.py"
INSTRUMENTED_INSERTION = f"{sys.executable} {INSTRUMENTED_SORT} insertion"

SORTER_TEMPLATE = """\
    #!/usr/bin/env python3
    import struct, sys, time
    with open(sys.argv[1], "rb") as stream:
        raw = stream.read()
    count = struct.unpack_from("<Q", raw)[0]
    if LOG_PATH is not None:
        with open(LOG_PATH, "a") as log:
            log.write(LABEL + "\\n")
    time.sleep(SLEEP_SECONDS)
    if count > FAIL_ABOVE:
        print("too many elements", file=sys.stderr)
        sys.exit(1)
    values = sorted(struct.unpack_from(f"<{count}i", raw, 8))
    with open(sys.argv[2], "wb") as stream:
        stream.write(struct.pack(f"<Q{count}i", count, *values))
    """


def write_executable(path: Path, body: str) -> Path:
    """Write a dedented script to a path and mark it executable.

    Args:
        path: Where to write the script.
        body: The script text; common leading indentation is removed.

    Returns:
        The path of the script.
    """
    path.write_text(textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def write_sorter(
    path: Path,
    *,
    log_path: Path | None = None,
    label: str = "sorter",
    sleep_seconds: float = 0.0,
    fail_above: int | None = None,
) -> Path:
    """Write a correct sorter with optional logging, delay, and a failure threshold.

    Args:
        path: Where to write the sorter.
        log_path: A file that receives ``label`` on a line of its own for every run.
        label: The text logged to ``log_path``.
        sleep_seconds: How long every run waits before it sorts.
        fail_above: The sorter exits with an error for inputs with more elements than this.

    Returns:
        The path of the sorter.
    """
    body = (
        SORTER_TEMPLATE.replace("LOG_PATH", repr(str(log_path)) if log_path else "None")
        .replace("LABEL", repr(label))
        .replace("SLEEP_SECONDS", repr(sleep_seconds))
        .replace("FAIL_ABOVE", repr(fail_above) if fail_above is not None else "10**18")
    )
    return write_executable(path, body)
