"""Tests for the environment, timeouts, and configuration files of implementations."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from helpers.executables import (
    write_executable,
    write_sorter,
)
from helpers.support import (
    Configure,
    assert_exits_with,
    invoke_cli,
)

pytestmark = pytest.mark.integration


def format_toml_list(*items: str) -> str:
    """Format the items as a TOML array of strings."""
    return json.dumps(list(items))


def build_configured_entry(
    name: str,
    script: Path,
    *,
    build_command: tuple[str, ...] | None = None,
    problem: str = "sorting",
    extra_lines: tuple[str, ...] = (),
) -> str:
    """Build the text of one ``[[implementations]]`` entry that runs a Python script.

    Args:
        name: The name of the implementation.
        script: The Python script the implementation runs.
        build_command: The build command, if the implementation has one.
        problem: The name of the problem the implementation solves.
        extra_lines: Further lines to add to the entry.

    Returns:
        The entry, ending in a newline.
    """
    lines = [
        "[[implementations]]",
        f"name = {json.dumps(name)}",
        f'problem = "{problem}"',
        f"command = {format_toml_list(sys.executable, str(script))}",
    ]
    if build_command is not None:
        lines.append(f"build_command = {format_toml_list(*build_command)}")
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


@pytest.fixture
def recorder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., str]:
    """Run a script that records a marker variable through ``test``; return what it saw."""
    monkeypatch.setenv("PLAYGROUND_MARKER", "visible")
    seen = tmp_path / "seen"
    script = write_executable(
        tmp_path / "recorder.py",
        f"""\
            #!/usr/bin/env python3
            import os, shutil, sys
            with open({str(seen)!r}, "w") as log:
                log.write(os.environ.get("PLAYGROUND_MARKER", "absent"))
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """,
    )

    def run(*options: str) -> str:
        result = invoke_cli("test", "sorting", str(script), *options)
        assert result.exit_code == 0, result.stderr
        return seen.read_text()

    return run


@pytest.mark.usefixtures("only_first_fixture")
def test_the_environment_is_minimal_by_default(recorder: Callable[..., str]) -> None:
    """Test the variables of the caller are hidden from the implementation by default."""
    assert recorder() == "absent"


@pytest.mark.usefixtures("only_first_fixture")
def test_the_flag_passes_the_caller_environment_through(
    recorder: Callable[..., str],
) -> None:
    """Test the inherit flag makes the variables of the caller visible."""
    assert recorder("--inherit-environment") == "visible"


@pytest.fixture
def seen(tmp_path: Path) -> Path:
    """A script that logs two variables of its environment and then sorts correctly."""
    log = tmp_path / "seen"
    write_executable(
        tmp_path / "recorder.py",
        f"""\
            #!/usr/bin/env python3
            import os, shutil, sys
            with open({str(log)!r}, "w") as stream:
                stream.write(os.environ.get("PYTHONPATH", "none") + "|")
                stream.write(os.environ.get("PLAYGROUND_MARKER", "absent"))
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """,
    )
    return log


@pytest.fixture
def sleeper(tmp_path: Path) -> Path:
    """A correct sorter that waits half a second on every run."""
    return write_sorter(tmp_path / "sleeper.py", sleep_seconds=0.5)


@pytest.mark.usefixtures("only_first_fixture")
def test_the_environment_table_reaches_the_run_with_the_configuration_directory_filled_in(
    configure: Configure, seen: Path, tmp_path: Path
) -> None:
    """Test the configured environment is set for the run, with its directory placeholder."""
    configure(
        build_configured_entry(
            "helper",
            tmp_path / "recorder.py",
            extra_lines=(
                'environment = { PYTHONPATH = "{configuration_directory}/helpers" }',
            ),
        )
    )

    result = invoke_cli("test", "sorting")

    assert result.exit_code == 0, result.stderr
    assert seen.read_text() == f"{tmp_path.resolve()}/helpers|absent"


@pytest.mark.usefixtures("only_first_fixture")
def test_the_configured_environment_is_applied_on_top_of_the_inherited_environment(
    configure: Configure,
    seen: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test configured variables override inherited ones and the others stay visible."""
    monkeypatch.setenv("PLAYGROUND_MARKER", "inherited")
    monkeypatch.setenv("PYTHONPATH", "from-the-host")
    configure(
        build_configured_entry(
            "helper",
            tmp_path / "recorder.py",
            extra_lines=(
                "inherit_environment = true",
                'environment = { PYTHONPATH = "from-the-configuration" }',
            ),
        )
    )

    result = invoke_cli("test", "sorting")

    assert result.exit_code == 0, result.stderr
    assert seen.read_text() == "from-the-configuration|inherited"


def test_the_configured_environment_reaches_the_build_command(
    configure: Configure, python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test the build command sees the environment configured for its implementation."""
    marker = tmp_path / "build-saw"
    build = (
        sys.executable,
        "-c",
        f"import os; open({str(marker)!r}, 'w').write(os.environ['BUILD_VARIABLE'])",
    )
    configure(
        build_configured_entry(
            "built",
            python_sort_executable,
            build_command=build,
            extra_lines=('environment = { BUILD_VARIABLE = "visible" }',),
        )
    )

    result = invoke_cli("debug", "sorting", "--size", "3")

    assert result.exit_code == 0, result.stderr
    assert marker.read_text() == "visible"


@pytest.mark.usefixtures("only_first_fixture")
def test_a_timeout_of_the_implementation_ends_its_runs_early(
    configure: Configure, sleeper: Path
) -> None:
    """Test the timeout configured for an implementation stops a run that takes longer."""
    configure(
        build_configured_entry(
            "sleeper", sleeper, extra_lines=("timeout_seconds = 0.2",)
        )
    )

    result = invoke_cli("test", "sorting")

    assert_exits_with(result, 1)
    assert "timed out after 0.200s" in result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_a_configured_timeout_replaces_the_timeout_option_for_that_implementation_only(
    configure: Configure,
    sleeper: Path,
    tmp_path: Path,
) -> None:
    """Test the timeout option applies only to implementations without their own timeout."""
    quick = write_sorter(tmp_path / "quick.py")
    configure(
        build_configured_entry(
            "patient", sleeper, extra_lines=("timeout_seconds = 30",)
        )
        + build_configured_entry("impatient", quick),
    )

    result = invoke_cli("test", "sorting", "--timeout", "0.2")

    assert result.exit_code == 0, result.stdout
    assert "patient: 1/1 cases passed" in result.stdout
    assert "impatient: 1/1 cases passed" in result.stdout


@pytest.fixture
def nested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory below the temporary directory that is the current directory."""
    directory = tmp_path / "solutions" / "sorting" / "c"
    directory.mkdir(parents=True)
    monkeypatch.chdir(directory)
    return directory


@pytest.fixture
def parent_configuration(
    tmp_path: Path,
    nested: Path,  # noqa: ARG001  requested for its side effect of changing directory
    python_sort_executable: Path,
) -> Path:
    """A configuration file in the temporary directory, above the current directory."""
    path = tmp_path / "algorithm-playground.toml"
    path.write_text(build_configured_entry("up-above", python_sort_executable))
    return path


@pytest.mark.usefixtures("only_first_fixture", "parent_configuration")
def test_a_configuration_above_the_current_directory_is_found() -> None:
    """Test a configuration file in a parent directory supplies the implementations."""
    result = invoke_cli("test", "sorting")

    assert result.exit_code == 0, result.stderr
    assert "up-above: 1/1 cases passed" in result.stdout


@pytest.mark.usefixtures("parent_configuration")
def test_list_shows_where_it_found_the_configuration() -> None:
    """Test list shows the implementations of a configuration found in a parent directory."""
    result = invoke_cli("list")

    assert result.exit_code == 0, result.stderr
    assert "up-above" in result.stdout
    assert "Configured implementations" in result.stdout


@pytest.mark.usefixtures("parent_configuration")
def test_the_search_stops_at_the_root_of_a_repository(tmp_path: Path) -> None:
    """Test a configuration above the root of a repository is not used."""
    (tmp_path / "solutions" / ".git").mkdir()

    result = invoke_cli("test", "sorting")

    assert_exits_with(result, 2)
    assert "No implementation was given for problem 'sorting'" in result.stderr


@pytest.mark.usefixtures("only_first_fixture", "nested")
def test_an_implementation_runs_in_the_directory_of_its_configuration_file(
    tmp_path: Path,
) -> None:
    """Test the working directory of a run is the directory of the configuration file."""
    log = tmp_path / "where"
    write_executable(
        tmp_path / "where.py",
        f"""\
            #!/usr/bin/env python3
            import os, shutil, sys
            open({str(log)!r}, "w").write(os.getcwd())
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """,
    )
    (tmp_path / "algorithm-playground.toml").write_text(
        build_configured_entry("where", tmp_path / "where.py")
    )

    result = invoke_cli("test", "sorting")

    assert result.exit_code == 0, result.stderr
    assert log.read_text() == str(tmp_path.resolve())
