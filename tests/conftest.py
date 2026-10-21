"""Shared pytest fixtures for the algorithm-playground test suite."""

import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from itertools import islice
from pathlib import Path

import pytest
from helpers.executables import write_executable

from algorithm_playground.cli import test_command
from algorithm_playground.core import registry
from algorithm_playground.core.problem import Fixture, VerificationResult
from algorithm_playground.problems.sorting import SortingProblem

REPO_ROOT = Path(__file__).resolve().parent.parent


class ExplodingVerificationProblem(SortingProblem):
    """The sorting problem with a verifier that raises, to test how the engines cope."""

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        raise RuntimeError("verifier exploded")


@pytest.fixture
def exploding_problem() -> SortingProblem:
    """The sorting problem with a verifier that raises."""
    return ExplodingVerificationProblem()


@pytest.fixture(autouse=True)
def _isolate_problem_loading(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Restore the problem registry and ``sys.path`` after every test.

    Both are process-wide state that loading a problem changes: the registry gains the
    problems a test registers, and ``sys.path`` gains the directories a test adds so
    that problem modules can be imported. Restoring them keeps tests independent.
    """
    snapshot = registry.snapshot_registry()
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    registry.restore_registry(snapshot)


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
    """The root directory of the repository."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def sorting_fixture_count() -> int:
    """The number of fixtures the sorting problem defines."""
    return len(list(SortingProblem().fixtures()))


@pytest.fixture(scope="session")
def examples_sorting_directory(repository_root: Path) -> Path:
    """The directory of the reference sorting implementations."""
    return repository_root / "examples" / "sorting"


@pytest.fixture(scope="session")
def python_sort_executable(examples_sorting_directory: Path) -> Path:
    """The reference sorter written in Python; skip the test when it is missing."""
    path = examples_sorting_directory / "python_sort.py"
    if not path.exists():
        pytest.skip(f"Reference executable not found: {path}")
    return path


@pytest.fixture(scope="session")
def c_qsort_executable(examples_sorting_directory: Path) -> Path:
    """The reference sorter written in C; skip the test when it is not built."""
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

    def first_fixture(self: SortingProblem) -> Iterator[Fixture[list[int]]]:
        return islice(original(self), 1)

    monkeypatch.setattr(SortingProblem, "fixtures", first_fixture)
    monkeypatch.setattr(test_command, "DEFAULT_RANDOM_CASE_COUNT", 0)


@pytest.fixture(scope="session")
def truncated_output_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
def malformed_trace_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
def unsorted_output_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
def drops_last_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
def crashing_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
