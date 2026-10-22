"""Shared pytest fixtures for the algorithm-playground test suite."""

import functools
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from itertools import islice
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    DEFAULT_CONFIGURATION_FILE_NAME,
    Fixture,
    VerificationResult,
    restore_registry,
    run_benchmark,
    run_tests,
    snapshot_registry,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import write_executable
from helpers.fakes import FakeRunners
from helpers.support import replace_command_dependencies

REPO_ROOT = Path(__file__).resolve().parent.parent


class ExplodingVerificationProblem(SortingProblem):
    """The sorting problem with a verifier that raises, to test how the engines cope."""

    @override
    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        message = "verifier exploded"
        raise RuntimeError(message)


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
    snapshot = snapshot_registry()
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    restore_registry(snapshot)


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
    replace_command_dependencies(monkeypatch, default_random_case_count=0)


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


@pytest.fixture
def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Write the default configuration file from entries and make its directory current."""

    def write(*entries: str) -> Path:
        path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
        path.write_text("\n".join(entries))
        monkeypatch.chdir(tmp_path)
        return path

    return write


@pytest.fixture
def use_fake_runners(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeRunners]:
    """Make ``benchmark`` run implementations through in-process fakes with set durations.

    Implementations are then named on the command line with ``--command NAME``;
    the commands are never run, nor checked for existing. Returns the factory so a test
    can inspect the calls.
    """

    def install(
        behaviors: Mapping[str, Callable[[Any], Any]],
        durations: Mapping[str, float | Callable[[Any], float]] | None = None,
        traces: Mapping[str, Callable[[Any], Any]] | None = None,
        traced_behaviors: Mapping[str, Callable[[Any], Any]] | None = None,
    ) -> FakeRunners:
        runners = FakeRunners(behaviors, durations, traces, traced_behaviors)
        replace_command_dependencies(
            monkeypatch,
            check_can_start=lambda _: None,
            run_benchmark=functools.partial(run_benchmark, runner_factory=runners),
        )
        return runners

    return install


@pytest.fixture
def use_fake_test_runners(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., FakeRunners]:
    """Make ``test`` run implementations through in-process fakes.

    Implementations are then named on the command line with ``--command NAME``;
    the commands are never run, nor checked for existing. Returns the factory so a test
    can inspect the calls.
    """

    def install(behaviors: Mapping[str, Callable[[Any], Any]]) -> FakeRunners:
        runners = FakeRunners(behaviors)
        replace_command_dependencies(
            monkeypatch,
            check_can_start=lambda _: None,
            run_tests=functools.partial(run_tests, runner_factory=runners),
        )
        return runners

    return install


@pytest.fixture
def recording_sorter(tmp_path: Path) -> tuple[Path, Path]:
    """A correct sorter that appends the bytes of every input it receives to a log file."""
    log = tmp_path / "inputs.log"
    script = write_executable(
        tmp_path / "recording_sorter.py",
        f"""\
        #!/usr/bin/env python3
        import struct, sys
        raw = open(sys.argv[1], "rb").read()
        with open({str(log)!r}, "a") as log:
            log.write(raw.hex() + "\\n")
        count = struct.unpack_from("<Q", raw)[0]
        values = sorted(struct.unpack_from(f"<{{count}}i", raw, 8))
        open(sys.argv[2], "wb").write(struct.pack(f"<Q{{count}}i", count, *values))
        """,
    )
    return script, log


@pytest.fixture
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the terminal wide, so long names and paths are not wrapped in the output."""
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def problem() -> SortingProblem:
    """A fresh sorting problem."""
    return SortingProblem()
