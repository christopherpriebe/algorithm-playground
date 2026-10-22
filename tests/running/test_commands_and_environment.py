"""Tests for the command, working directory, and environment a run gets."""

import shlex
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from algorithm_playground.core import (
    Implementation,
    Runner,
    RunnerError,
    build_implementation,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import write_executable

# Copies the input to the output (valid sorting output only for sorted input)
# and reports facts about its process on stderr.
INSPECTING_CODE = textwrap.dedent(
    """\
    import os, shutil, sys
    shutil.copyfile(sys.argv[1], sys.argv[2])
    print(os.getcwd(), file=sys.stderr)
    print(",".join(sorted(os.environ)), file=sys.stderr)
    """
)


def build_python_code_implementation(
    code: str,
    *,
    name: str = "inline",
    **options: Any,  # noqa: ANN401  forwarded unchanged to Implementation
) -> Implementation:
    """Build an implementation that runs ``code`` with ``python -c``.

    The harness appends the input, output and trace paths, which the code reads
    from ``sys.argv[1:]`` just as a script file would. Unlike a script, it needs
    no file, and the operating system does not scan a new file on its first run.
    """
    return Implementation(
        name=name, command=(sys.executable, "-c", textwrap.dedent(code)), **options
    )


def collect_environment_keys(implementation: Implementation) -> set[str]:
    """Run the inspecting implementation and collect the names of the variables it saw."""
    result = Runner(SortingProblem(), implementation).run([1, 2])
    return set(result.standard_error.splitlines()[1].split(","))


def test_runs_a_script_without_the_executable_bit_through_an_interpreter(
    plain_sort_script: Path,
) -> None:
    """Test a script that is not executable runs when an interpreter precedes it."""
    implementation = Implementation.from_command_text(
        shlex.join([sys.executable, str(plain_sort_script)])
    )

    result = Runner(SortingProblem(), implementation).run([3, 1, 2])

    assert result.output == [1, 2, 3]


def test_missing_command_names_the_implementation() -> None:
    """Test the error for a missing command names the implementation and the command."""
    implementation = Implementation(
        name="ghost", command=("algorithm-playground-no-such-command",)
    )

    with pytest.raises(RunnerError, match=r"'ghost'.*not found.*no-such-command"):
        Runner(SortingProblem(), implementation).run([1])


def test_non_executable_file_reports_permission_denied(tmp_path: Path) -> None:
    """Test running a file without the executable bit raises a permission error."""
    script = tmp_path / "plain.py"
    script.write_text("print('hello')\n")
    implementation = Implementation(name="plain", command=(str(script),))

    with pytest.raises(RunnerError, match="permission denied"):
        Runner(SortingProblem(), implementation).run([1])


def test_command_runs_in_the_working_directory(tmp_path: Path) -> None:
    """Test the command starts with the working directory of the implementation."""
    directory = tmp_path / "work"
    directory.mkdir()
    implementation = build_python_code_implementation(
        INSPECTING_CODE, working_directory=directory
    )

    result = Runner(SortingProblem(), implementation).run([1, 2])

    assert Path(result.standard_error.splitlines()[0]).resolve() == directory.resolve()


def test_relative_command_resolves_against_the_working_directory(
    tmp_path: Path,
) -> None:
    """Test a command given as a relative path is found in the working directory."""
    directory = tmp_path / "work"
    directory.mkdir()
    write_executable(
        directory / "local.py", "#!/usr/bin/env python3\n" + INSPECTING_CODE
    )
    implementation = Implementation(
        name="local", command=("./local.py",), working_directory=directory
    )

    result = Runner(SortingProblem(), implementation).run([1, 2])

    assert result.output == [1, 2]


def test_missing_working_directory_raises_runner_error(tmp_path: Path) -> None:
    """Test a working directory that does not exist raises a RunnerError."""
    implementation = Implementation(
        name="lost", command=("true",), working_directory=tmp_path / "missing"
    )

    with pytest.raises(RunnerError, match="working directory not found"):
        Runner(SortingProblem(), implementation).run([1])


def test_minimal_environment_does_not_include_random_host_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a variable of the host is not passed to a run with the minimal environment."""
    monkeypatch.setenv("ALGORITHM_PLAYGROUND_TEST_SECRET", "must-not-leak")

    keys = collect_environment_keys(build_python_code_implementation(INSPECTING_CODE))

    assert "ALGORITHM_PLAYGROUND_TEST_SECRET" not in keys


def test_minimal_environment_keeps_the_path() -> None:
    """Test the minimal environment still holds PATH."""
    keys = collect_environment_keys(build_python_code_implementation(INSPECTING_CODE))

    assert "PATH" in keys


def test_inherit_environment_passes_the_full_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test an implementation that inherits the environment sees the host variables."""
    monkeypatch.setenv("ALGORITHM_PLAYGROUND_TEST_VARIABLE", "visible")
    inheriting = build_python_code_implementation(
        INSPECTING_CODE, inherit_environment=True
    )

    keys = collect_environment_keys(inheriting)

    assert "ALGORITHM_PLAYGROUND_TEST_VARIABLE" in keys


ECHO_CODE = """\
        import os, shutil, sys
        shutil.copyfile(sys.argv[1], sys.argv[2])
        print(os.environ.get("EXTRA_VARIABLE", "unset"), file=sys.stderr)
        print(os.environ.get("PATH", "no path"), file=sys.stderr)
        """


def test_the_variables_of_an_implementation_are_set_on_top_of_the_minimal_environment() -> (
    None
):
    """Test the variables of an implementation are visible to its run."""
    implementation = build_python_code_implementation(
        ECHO_CODE, environment={"EXTRA_VARIABLE": "from-config"}
    )

    result = Runner(SortingProblem(), implementation).run([1, 2])

    assert result.standard_error.splitlines()[0] == "from-config"


def test_they_override_the_inherited_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a variable of the implementation replaces the same variable of the host."""
    monkeypatch.setenv("EXTRA_VARIABLE", "from-host")
    implementation = build_python_code_implementation(
        ECHO_CODE,
        inherit_environment=True,
        environment={"EXTRA_VARIABLE": "from-config"},
    )

    result = Runner(SortingProblem(), implementation).run([1, 2])

    assert result.standard_error.splitlines()[0] == "from-config"


def test_they_can_replace_the_path() -> None:
    """Test an implementation can set its own PATH."""
    implementation = build_python_code_implementation(
        ECHO_CODE, environment={"PATH": "/custom/bin"}
    )

    result = Runner(SortingProblem(), implementation).run([1, 2])

    assert result.standard_error.splitlines()[1] == "/custom/bin"


def test_a_build_sees_them_too(tmp_path: Path) -> None:
    """Test the build command sees the variables of the implementation."""
    marker = tmp_path / "marker"
    implementation = Implementation(
        name="built",
        command=("true",),
        build_command=(
            "sh",
            "-c",
            f'printf %s "$EXTRA_VARIABLE" > {shlex.quote(str(marker))}',
        ),
        environment={"EXTRA_VARIABLE": "visible to the build"},
    )

    build_implementation(implementation)

    assert marker.read_text() == "visible to the build"
