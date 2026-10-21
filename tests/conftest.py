"""Shared pytest fixtures for the algorithm-playground test suite."""

from __future__ import annotations

import shutil
import stat
import sys
import tempfile
import textwrap
from collections.abc import Callable, Iterator
from itertools import islice
from pathlib import Path

import pytest
from misbehaving import PROBLEM_NAME, faulty_problem_class

from algorithm_playground.cli import test_command
from algorithm_playground.core import registry
from algorithm_playground.core.problem import VerificationResult
from algorithm_playground.problems.sorting import SortingProblem

REPO_ROOT = Path(__file__).resolve().parent.parent


class ExplodingVerificationProblem(SortingProblem):
    """The sorting problem with a verifier that raises, to test how the engines cope."""

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        raise RuntimeError("verifier exploded")


@pytest.fixture
def exploding_problem() -> SortingProblem:
    return ExplodingVerificationProblem()


@pytest.fixture(autouse=True)
def _isolate_problem_loading(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Undo what a test registers or adds to the import path, so tests cannot leak problems."""
    registered = dict(registry._REGISTRY)
    sources = dict(registry._SOURCES)
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(registered)
    registry._SOURCES.clear()
    registry._SOURCES.update(sources)


@pytest.fixture
def register_other_problem() -> Callable[[str], None]:
    """Register a copy of the sorting problem under another name (undone after the test)."""

    def register(name: str) -> None:
        registry.register_problem(type("OtherProblem", (SortingProblem,), {"name": name}))

    return register


@pytest.fixture
def register_faulty_problem() -> Callable[[str], str]:
    """Register the problem whose ``fault`` hook raises (undone after the test); return its name."""

    def register(fault: str = "") -> str:
        registry.register_problem(faulty_problem_class(fault))
        return PROBLEM_NAME

    return register


@pytest.fixture
def forget_modules() -> Iterator[Callable[..., None]]:
    """Drop modules from ``sys.modules`` now and after the test, so they import afresh."""
    names: list[str] = []

    def forget(*module_names: str) -> None:
        names.extend(module_names)
        for name in module_names:
            sys.modules.pop(name, None)

    yield forget
    for name in names:
        sys.modules.pop(name, None)


@pytest.fixture
def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the runner's scratch directories into the test's own temporary directory."""
    root = tmp_path / "scratch"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def sorting_fixture_count() -> int:
    return len(list(SortingProblem().fixtures()))


@pytest.fixture(scope="session")
def examples_sorting_directory(repository_root: Path) -> Path:
    return repository_root / "examples" / "sorting"


@pytest.fixture(scope="session")
def python_sort_executable(examples_sorting_directory: Path) -> Path:
    path = examples_sorting_directory / "python_sort.py"
    if not path.exists():
        pytest.skip(f"Reference executable not found: {path}")
    return path


@pytest.fixture(scope="session")
def c_qsort_executable(examples_sorting_directory: Path) -> Path:
    path = examples_sorting_directory / "c_qsort"
    if not path.exists():
        pytest.skip("C reference executable not built: run 'make -C examples/sorting'")
    return path


@pytest.fixture
def plain_sort_script(tmp_path: Path, python_sort_executable: Path) -> Path:
    """A copy of the reference sorter without the executable bit, to run through an interpreter."""
    script = tmp_path / "plain sort.py"
    shutil.copyfile(python_sort_executable, script)
    return script


@pytest.fixture
def only_first_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restrict ``test`` to the first fixture of the sorting problem and no random cases.

    For tests that do not depend on the number of cases and should not pay for them.
    """
    original = SortingProblem.fixtures

    def first_fixture(self: SortingProblem) -> Iterator:
        return islice(original(self), 1)

    monkeypatch.setattr(SortingProblem, "fixtures", first_fixture)
    monkeypatch.setattr(test_command, "DEFAULT_RANDOM_CASE_COUNT", 0)


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture(scope="session")
def write_executable() -> Callable[[Path, str], Path]:
    """Write a dedented script to a path and mark it executable; return the path."""
    return _write_executable


@pytest.fixture(scope="session")
def truncated_output_executable(
    tmp_path_factory: pytest.TempPathFactory, write_executable: Callable[[Path, str], Path]
) -> Path:
    """A sorter whose output header promises more elements than the file holds."""
    return write_executable(
        tmp_path_factory.mktemp("broken") / "truncated_output.py",
        """\
        #!/usr/bin/env python3
        import struct, sys
        with open(sys.argv[2], "wb") as stream:
            stream.write(struct.pack("<Q", 5))
        """,
    )


@pytest.fixture(scope="session")
def malformed_trace_executable(
    tmp_path_factory: pytest.TempPathFactory, write_executable: Callable[[Path, str], Path]
) -> Path:
    """A correct sorter whose trace header promises snapshots it never writes."""
    return write_executable(
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


@pytest.fixture(scope="session")
def unsorted_output_executable(
    tmp_path_factory: pytest.TempPathFactory, write_executable: Callable[[Path, str], Path]
) -> Path:
    """A well-formed but wrong "sorter" that copies its input to the output unchanged."""
    return write_executable(
        tmp_path_factory.mktemp("broken") / "unsorted_output.py",
        """\
        #!/usr/bin/env python3
        import shutil, sys
        shutil.copyfile(sys.argv[1], sys.argv[2])
        """,
    )


@pytest.fixture(scope="session")
def drops_last_executable(
    tmp_path_factory: pytest.TempPathFactory, write_executable: Callable[[Path, str], Path]
) -> Path:
    """A sorter that loses its largest element when the input has more than five elements."""
    return write_executable(
        tmp_path_factory.mktemp("broken") / "drops_last.py",
        """\
        #!/usr/bin/env python3
        import struct, sys
        with open(sys.argv[1], "rb") as stream:
            raw = stream.read()
        count = struct.unpack_from("<Q", raw)[0]
        values = sorted(struct.unpack_from(f"<{count}i", raw, 8))
        if count > 5:
            values = values[:-1]
        with open(sys.argv[2], "wb") as stream:
            stream.write(struct.pack(f"<Q{len(values)}i", len(values), *values))
        """,
    )


@pytest.fixture(scope="session")
def crashing_executable(
    tmp_path_factory: pytest.TempPathFactory, write_executable: Callable[[Path, str], Path]
) -> Path:
    """An executable that always exits with a non-zero status."""
    return write_executable(
        tmp_path_factory.mktemp("broken") / "crashing.py",
        """\
        #!/usr/bin/env python3
        import sys
        print("kaboom", file=sys.stderr)
        sys.exit(3)
        """,
    )


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


@pytest.fixture(scope="session")
def write_sorter(
    write_executable: Callable[[Path, str], Path],
) -> Callable[..., Path]:
    """Write a correct sorter with optional logging, delay, and a failure threshold.

    ``log_path`` receives ``label`` on a line of its own for every run,
    ``sleep_seconds`` delays every run, and the sorter exits with an error for
    inputs with more than ``fail_above`` elements.
    """

    def write(
        path: Path,
        *,
        log_path: Path | None = None,
        label: str = "sorter",
        sleep_seconds: float = 0.0,
        fail_above: int | None = None,
    ) -> Path:
        body = (
            SORTER_TEMPLATE.replace("LOG_PATH", repr(str(log_path)) if log_path else "None")
            .replace("LABEL", repr(label))
            .replace("SLEEP_SECONDS", repr(sleep_seconds))
            .replace("FAIL_ABOVE", repr(fail_above) if fail_above is not None else "10**18")
        )
        return write_executable(path, body)

    return write
