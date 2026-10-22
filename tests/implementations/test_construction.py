"""Tests for building implementations from executables and command text."""

import copy
import dataclasses
import pickle
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest

from algorithm_playground.core import (
    BenchmarkSettings,
    Implementation,
    resolve_case,
    run_benchmark,
    run_tests,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import FakeRunners, build_named_implementations, sort_correctly


@pytest.fixture
def implementation() -> Implementation:
    """An implementation with the required fields only."""
    return Implementation(name="sorter", command=("./sorter",))


Engine = Callable[[Sequence[Implementation]], list[str]]


def run_tests_on(implementations: Sequence[Implementation]) -> list[str]:
    """Run the empty fixture on fake runners and return the names of the implementations tested."""
    problem = SortingProblem()
    report = run_tests(
        problem,
        implementations,
        [resolve_case(problem, "fixture:empty")],
        runner_factory=FakeRunners(
            {item.name: sort_correctly for item in implementations}
        ),
    )
    return list(report.implementation_names)


def run_benchmark_on(implementations: Sequence[Implementation]) -> list[str]:
    """Benchmark on fake runners and return the names of the implementations measured."""
    settings = BenchmarkSettings(
        seed=1,
        sizes=(3,),
        repetitions=1,
        warmup=0,
        timeout_seconds=30.0,
        verify_outputs=True,
        subtract_startup_time=False,
    )
    report = run_benchmark(
        SortingProblem(),
        implementations,
        settings,
        runner_factory=FakeRunners(
            {item.name: sort_correctly for item in implementations}
        ),
    )
    return [benchmark.implementation.name for benchmark in report.implementations]


@pytest.fixture(
    params=[run_tests_on, run_benchmark_on], ids=["run_tests", "run_benchmark"]
)
def engine(request: pytest.FixtureRequest) -> Engine:
    """An engine that takes implementations and returns the names it ran."""
    return cast("Engine", request.param)


def test_optional_fields_default_to_unset(implementation: Implementation) -> None:
    """Test an implementation built from a name and command leaves the other fields unset."""
    assert implementation.working_directory is None
    assert implementation.build_command is None
    assert implementation.inherit_environment is False
    assert implementation.environment == {}
    assert implementation.timeout_seconds is None


def test_fields_cannot_be_reassigned(implementation: Implementation) -> None:
    """Test an implementation is immutable."""
    with pytest.raises(
        dataclasses.FrozenInstanceError, match="cannot assign to field 'name'"
    ):
        implementation.__setattr__("name", "other")


def test_rejects_an_empty_name() -> None:
    """Test an implementation needs a non-empty name."""
    with pytest.raises(ValueError, match="non-empty name"):
        Implementation(name="", command=("./sorter",))


def test_rejects_an_empty_command() -> None:
    """Test an implementation needs a non-empty command."""
    with pytest.raises(ValueError, match="non-empty command"):
        Implementation(name="sorter", command=())


def test_rejects_an_empty_build_command() -> None:
    """Test a build command, when given, must not be empty."""
    with pytest.raises(ValueError, match="empty build command"):
        Implementation(name="sorter", command=("./sorter",), build_command=())


@pytest.mark.parametrize(
    "variable",
    ["", "A=B", "BAD\0NAME"],
    ids=["empty", "equals-sign", "null-character"],
)
def test_rejects_an_invalid_environment_variable_name(variable: str) -> None:
    """Test an environment variable name must be non-empty and free of '=' and NUL."""
    with pytest.raises(ValueError, match="invalid environment variable"):
        Implementation(
            name="sorter", command=("./sorter",), environment={variable: "x"}
        )


@pytest.mark.parametrize(
    "timeout",
    [0.0, -2.0, float("nan"), float("inf")],
    ids=["zero", "negative", "not-a-number", "infinite"],
)
def test_rejects_a_timeout_that_is_not_finite_and_positive(timeout: float) -> None:
    """Test a timeout must be a finite positive number of seconds."""
    with pytest.raises(ValueError, match="finite positive timeout"):
        Implementation(name="sorter", command=("./sorter",), timeout_seconds=timeout)


def test_keeps_the_environment_and_timeout_it_is_given() -> None:
    """Test the environment and timeout passed to the constructor are kept."""
    implementation = Implementation(
        name="sorter",
        command=("./sorter",),
        environment={"A": "1"},
        timeout_seconds=2.5,
    )

    assert implementation.environment == {"A": "1"}
    assert implementation.timeout_seconds == 2.5


def test_equal_implementations_hash_alike() -> None:
    """Test implementations with the same fields are one member of a set."""
    first = Implementation(name="sorter", command=("./sorter",), environment={"A": "1"})
    second = Implementation(
        name="sorter", command=("./sorter",), environment={"A": "1"}
    )

    assert hash(first) == hash(second)
    assert {first, second} == {first}


def test_implementations_that_differ_only_in_environment_are_unequal() -> None:
    """Test the environment takes part in equality even though it is not hashed."""
    first = Implementation(name="sorter", command=("./sorter",), environment={"A": "1"})
    second = Implementation(
        name="sorter", command=("./sorter",), environment={"A": "2"}
    )

    assert first != second


def test_the_environment_cannot_be_changed_after_construction() -> None:
    """Test the environment is read-only, so it cannot slip past validation."""
    implementation = Implementation(
        name="sorter", command=("./sorter",), environment={"A": "1"}
    )

    with pytest.raises(TypeError, match="does not support item assignment"):
        implementation.environment["B"] = "\0"  # ty: ignore[invalid-assignment]  the point is that a Mapping has no item assignment


def test_changing_the_given_mapping_does_not_change_the_implementation() -> None:
    """Test the implementation keeps its own copy of the environment."""
    environment = {"A": "1"}
    implementation = Implementation(
        name="sorter", command=("./sorter",), environment=environment
    )

    environment["B"] = "2"

    assert implementation.environment == {"A": "1"}


def test_an_implementation_survives_pickling_and_deep_copies() -> None:
    """Test the read-only environment does not stop implementations from being copied or pickled."""
    implementation = Implementation(
        name="sorter", command=("./sorter",), environment={"A": "1"}
    )

    assert pickle.loads(pickle.dumps(implementation)) == implementation  # noqa: S301  the test unpickles only what it just pickled
    assert copy.deepcopy(implementation) == implementation
    assert dataclasses.asdict(implementation)["environment"] == {"A": "1"}


def test_resolves_the_path_and_names_after_the_file(tmp_path: Path) -> None:
    """Test the command is the resolved path and the name is the file name."""
    executable = tmp_path / "sub" / ".." / "sorter"

    implementation = Implementation.from_executable(executable)

    assert implementation.name == "sorter"
    assert implementation.command == (str((tmp_path / "sorter").resolve()),)
    assert implementation.working_directory is None


def test_an_explicit_name_overrides_the_file_name(tmp_path: Path) -> None:
    """Test a name passed explicitly replaces the file name."""
    implementation = Implementation.from_executable(tmp_path / "sorter", name="fast")

    assert implementation.name == "fast"


def test_splits_like_a_shell() -> None:
    """Test the command text is split into arguments with shell quoting rules."""
    implementation = Implementation.from_command_text("java -jar 'My Sort.jar'")

    assert implementation.command == ("java", "-jar", "My Sort.jar")


def test_name_defaults_to_the_text_when_no_argument_is_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test the whole command text names an implementation that references no file."""
    monkeypatch.chdir(tmp_path)
    text = "node sort.js"

    implementation = Implementation.from_command_text(text)

    assert implementation.name == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("python3 sort.py", "sort"),
        ("{python} sort.py", "sort"),
        ("java -jar build/Sort.jar", "Sort"),
        ("./build/merge_sort", "merge_sort"),
        ("python3 sort.py insertion", "sort insertion"),
        ("python3 --flag sort.py --other", "sort --other"),
        ("python3 sort.py helper.py", "helper"),
    ],
    ids=[
        "script",
        "interpreter-path",
        "jar-in-directory",
        "executable-in-directory",
        "argument-after-script",
        "flags-around-script",
        "last-of-two-files",
    ],
)
def test_name_is_the_last_existing_file_without_extension_and_the_arguments_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, expected: str
) -> None:
    """Test the name is the last existing file without its extension plus later arguments."""
    (tmp_path / "build").mkdir()
    for relative in ("sort.py", "helper.py", "build/Sort.jar", "build/merge_sort"):
        (tmp_path / relative).write_text("")
    monkeypatch.chdir(tmp_path)

    implementation = Implementation.from_command_text(
        text.replace("{python}", sys.executable)
    )

    assert implementation.name == expected


def test_a_file_named_by_a_path_gives_its_file_name(tmp_path: Path) -> None:
    """Test a script given by its full path names the implementation after the file."""
    script = tmp_path / "nested" / "sort.js"
    script.parent.mkdir()
    script.write_text("")

    implementation = Implementation.from_command_text(f"node {script}")

    assert implementation.name == "sort"


def test_two_commands_running_one_script_with_other_arguments_stay_apart(
    tmp_path: Path,
) -> None:
    """Test commands that run one script with different arguments get different names."""
    script = tmp_path / "instrumented_sort.py"
    script.write_text("")

    names = [
        Implementation.from_command_text(f"python3 {script} {algorithm}").name
        for algorithm in ("insertion", "merge")
    ]

    assert names == ["instrumented_sort insertion", "instrumented_sort merge"]


def test_a_directory_argument_does_not_name_the_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test an argument that is a directory is not used as the implementation name."""
    (tmp_path / "build").mkdir()
    monkeypatch.chdir(tmp_path)

    implementation = Implementation.from_command_text("make build")

    assert implementation.name == "make build"


def test_an_explicit_name_overrides_the_name_derived_from_the_command() -> None:
    """Test a name passed explicitly replaces the derived one."""
    implementation = Implementation.from_command_text("node sort.js", name="node-sort")

    assert implementation.name == "node-sort"


@pytest.mark.parametrize("text", ["", "   "], ids=["empty", "blank"])
def test_empty_text_is_rejected(text: str) -> None:
    """Test command text without any argument is an error."""
    with pytest.raises(ValueError, match="must not be empty"):
        Implementation.from_command_text(text)


def test_unbalanced_quote_is_rejected() -> None:
    """Test command text with an unclosed quote is an error that quotes the text."""
    with pytest.raises(
        ValueError,
        match=r"Could not parse command .*sort\.js.*No closing quotation",
    ):
        Implementation.from_command_text("node 'sort.js")


def test_returns_existing_files_resolved_against_the_working_directory(
    tmp_path: Path,
) -> None:
    """Test the command arguments that name files are resolved against the working directory."""
    script = tmp_path / "sort.py"
    script.write_text("")
    implementation = Implementation(
        name="sorter",
        command=("python3", "sort.py", "--flag", "missing.py"),
        working_directory=tmp_path,
    )

    assert implementation.referenced_files() == (script.resolve(),)


def test_includes_absolute_paths_and_ignores_directories(tmp_path: Path) -> None:
    """Test absolute file paths are listed once and directories are left out."""
    script = tmp_path / "sort.py"
    script.write_text("")
    implementation = Implementation(
        name="sorter", command=(str(script), str(tmp_path), str(script))
    )

    assert implementation.referenced_files() == (script.resolve(),)


def test_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test relative arguments resolve against the current directory without a working one."""
    script = tmp_path / "sort.py"
    script.write_text("")
    monkeypatch.chdir(tmp_path)
    implementation = Implementation(name="sorter", command=("python3", "sort.py"))

    assert implementation.referenced_files() == (script.resolve(),)


def test_engine_accepts_implementations_with_unique_names(engine: Engine) -> None:
    """Test an engine runs every implementation when their names are unique."""
    implementations = build_named_implementations("first", "second")

    names = engine(implementations)

    assert names == ["first", "second"]


def test_engine_rejects_an_empty_sequence_of_implementations(engine: Engine) -> None:
    """Test an engine refuses to run without implementations."""
    with pytest.raises(ValueError, match="At least one implementation"):
        engine([])


def test_engine_rejects_duplicate_implementation_names(engine: Engine) -> None:
    """Test an engine names the implementation that appears twice."""
    implementations = build_named_implementations("a", "a")

    with pytest.raises(ValueError, match="Duplicate implementation name: 'a'"):
        engine(implementations)
