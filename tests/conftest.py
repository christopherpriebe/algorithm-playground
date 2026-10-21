"""Shared pytest fixtures for the algorithm-playground test suite."""

from __future__ import annotations

import stat
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def examples_sorting_dir(repo_root: Path) -> Path:
    return repo_root / "examples" / "sorting"


@pytest.fixture(scope="session")
def python_sort_executable(examples_sorting_dir: Path) -> Path:
    path = examples_sorting_dir / "python_sort.py"
    if not path.exists():
        pytest.skip(f"Reference executable not found: {path}")
    return path


@pytest.fixture(scope="session")
def c_qsort_executable(examples_sorting_dir: Path) -> Path:
    path = examples_sorting_dir / "c_qsort"
    if not path.exists():
        pytest.skip("C reference executable not built: run 'make -C examples/sorting'")
    return path


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture(scope="session")
def truncated_output_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A sorter whose output header promises more elements than the file holds."""
    return _write_executable(
        tmp_path_factory.mktemp("broken") / "truncated_output.py",
        """\
        #!/usr/bin/env python3
        import struct, sys
        with open(sys.argv[2], "wb") as stream:
            stream.write(struct.pack("<Q", 5))
        """,
    )


@pytest.fixture(scope="session")
def malformed_trace_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A correct sorter whose trace header promises snapshots it never writes."""
    return _write_executable(
        tmp_path_factory.mktemp("broken") / "malformed_trace.py",
        """\
        #!/usr/bin/env python3
        import struct, sys
        with open(sys.argv[1], "rb") as stream:
            raw = stream.read()
        count = struct.unpack_from("<Q", raw)[0]
        values = sorted(struct.unpack_from(f"<{count}i", raw, 8))
        with open(sys.argv[2], "wb") as stream:
            stream.write(struct.pack("<Q", count) + struct.pack(f"<{count}i", *values))
        if len(sys.argv) == 4:
            with open(sys.argv[3], "wb") as stream:
                stream.write(struct.pack("<II", 0, 3))
        """,
    )
