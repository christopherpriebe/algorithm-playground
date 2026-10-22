"""Tests for help, usage errors, the version option, interrupts, and markup in user text."""

import json
import re
import sys
from pathlib import Path

import pytest

from algorithm_playground import __version__
from helpers.executables import (
    INSTRUMENTED_INSERTION,
)
from helpers.support import (
    Configure,
    assert_exits_with,
    find_table_header,
    invoke_cli,
    replace_command_dependencies,
)

pytestmark = pytest.mark.integration


FAILING_BUILD = (
    sys.executable,
    "-c",
    "import sys; print('compile exploded', file=sys.stderr); sys.exit(1)",
)


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


def read_help_text(command: str) -> str:
    """Return the help of a command with the box-drawing characters and line breaks removed."""
    output = invoke_cli(command, "--help").stdout
    return " ".join(re.sub(r"[│╭╮╰╯─]", " ", output).split())


def raise_keyboard_interrupt(*_arguments: object, **_keywords: object) -> None:
    """Raise the interrupt that Ctrl+C causes, whatever the arguments are."""
    raise KeyboardInterrupt


@pytest.fixture
def help_panel_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the terminal wide enough for the help panels to keep their lines."""
    monkeypatch.setenv("COLUMNS", "120")


@pytest.mark.usefixtures("help_panel_terminal")
@pytest.mark.parametrize("command", ["test", "benchmark", "debug", "list"])
def test_arguments_are_shown_by_their_user_facing_names(command: str) -> None:
    """Test the help of a command does not show the internal names of its arguments."""
    text = invoke_cli(command, "--help").stdout

    panel = text[text.index("Arguments") : text.index("Options")]
    assert "problem_name" not in panel
    assert "selectors" not in panel
    assert "implementation_selector" not in panel
    assert "problem_name" not in text


@pytest.mark.usefixtures("help_panel_terminal")
@pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
def test_the_problem_and_implementation_arguments_are_shown_by_their_metavars(
    command: str,
) -> None:
    """Test the help of a command shows its problem and implementation arguments."""
    text = invoke_cli(command, "--help").stdout

    panel = text[text.index("Arguments") : text.index("Options")]
    assert "PROBLEM" in panel
    assert "[IMPLEMENTATION]" in panel


def test_the_usage_line_is_unchanged() -> None:
    """Test the usage line of the test command shows its arguments as before."""
    # Typer 0.27 and later put the braces of a required argument around its metavar.
    usage = re.compile(r"test \[OPTIONS\] \{?PROBLEM\}? \[IMPLEMENTATION\]\.\.\.")

    assert usage.search(invoke_cli("test", "--help").stdout)


def test_an_arguments_default_name_still_binds_the_value(
    python_sort_executable: Path,
) -> None:
    """Test arguments given by position reach the command despite their display names."""
    result = invoke_cli(
        "test", "sorting", str(python_sort_executable), "--fixture", "empty"
    )

    assert result.exit_code == 0, result.stdout


def test_an_unknown_option_suggests_a_close_one_without_a_tuple() -> None:
    """Test an unknown option that is close to a known one suggests it as plain text."""
    result = invoke_cli("test", "sorting", "--verbos")

    assert result.exit_code == 2
    assert "No such option: --verbos. Did you mean --verbose?" in result.stderr
    assert "('" not in result.stderr
    assert "',)" not in result.stderr


def test_an_unknown_option_without_a_suggestion_is_plain() -> None:
    """Test an unknown option that is close to no known one gets no suggestion."""
    result = invoke_cli("benchmark", "sorting", "--zzzzzzzz")

    assert result.exit_code == 2
    assert "No such option: --zzzzzzzz." in result.stderr
    assert "Did you mean" not in result.stderr


def test_a_missing_argument_is_still_named_by_its_metavar() -> None:
    """Test a missing required argument is named by its metavar."""
    result = invoke_cli("test")

    assert result.exit_code == 2
    assert "Missing argument 'PROBLEM'" in result.stderr


def test_unknown_implementation_name_exits_with_code_2(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test an implementation name that is neither configured nor a file is a usage error."""
    configure(build_configured_entry("configured-sorter", python_sort_executable))

    result = invoke_cli("test", "sorting", "no-such-implementation")

    assert_exits_with(result, 2)
    assert "no-such-implementation" in result.stderr
    assert "'configured-sorter'" in result.stderr
    assert result.stdout == ""


def test_no_implementation_and_no_configuration_exits_with_code_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test running without any implementation or configuration says how to supply one."""
    monkeypatch.chdir(tmp_path)

    result = invoke_cli("test", "sorting")

    assert_exits_with(result, 2)
    assert "--command" in result.stderr
    assert "algorithm-playground.toml" in result.stderr


def test_invalid_configuration_exits_with_code_2(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a configuration entry without a command is a configuration error."""
    path = tmp_path / "invalid.toml"
    path.write_text(
        '[[implementations]]\nname = "missing-command"\nproblem = "sorting"\n'
    )

    result = invoke_cli(
        "test", "sorting", str(python_sort_executable), "--configuration", str(path)
    )

    assert_exits_with(result, 2)
    assert "Configuration error" in result.stderr
    assert "missing required key 'command'" in result.stderr


def test_the_former_build_key_is_rejected_with_a_hint(tmp_path: Path) -> None:
    """Test the retired ``build`` key is rejected with a hint to use ``build_command``."""
    path = tmp_path / "former.toml"
    path.write_text(
        '[[implementations]]\nname = "former"\nproblem = "sorting"\n'
        'command = "./former"\nbuild = "make"\n'
    )

    result = invoke_cli("test", "sorting", "--configuration", str(path))

    assert result.exit_code == 2
    assert "unknown key(s): build." in result.stderr
    assert "build_command" in result.stderr
    assert "newer algorithm-playground" in result.stderr


def test_missing_configuration_file_exits_with_code_2(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a configuration file that does not exist is a usage error."""
    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--configuration",
        str(tmp_path / "missing.toml"),
    )

    assert_exits_with(result, 2)
    assert "configuration file not found" in result.stderr


def test_a_configuration_path_inside_the_current_directory_is_shown_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test an error about a configuration below the current directory shows a short path."""
    (tmp_path / "broken.toml").write_text("[[implementations\n")
    monkeypatch.chdir(tmp_path)

    result = invoke_cli("list", "--configuration", str(tmp_path / "broken.toml"))

    assert result.exit_code == 2
    assert result.stderr.startswith("Configuration error: broken.toml: invalid TOML")


@pytest.fixture
def odd_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    python_sort_executable: Path,
) -> Path:
    """A configuration in a directory named like markup, for an implementation named so."""
    directory = tmp_path / "[b]odd"
    directory.mkdir()
    path = directory / "algorithm-playground.toml"
    path.write_text(build_configured_entry("[red]odd[/red]", python_sort_executable))
    monkeypatch.chdir(tmp_path)
    return path


@pytest.mark.usefixtures("wide_terminal")
def test_list_shows_the_configuration_path_and_name_literally(
    odd_configuration: Path,
) -> None:
    """Test list prints a configuration path and an implementation name as typed."""
    result = invoke_cli("list", "--configuration", str(odd_configuration))

    assert result.exit_code == 0, result.stderr
    assert (
        "Configured implementations ([b]odd/algorithm-playground.toml)" in result.stdout
    )
    assert "[red]odd[/red]" in result.stdout


@pytest.mark.usefixtures("only_first_fixture", "wide_terminal")
def test_test_shows_the_name_literally_in_the_matrix_and_the_summary(
    odd_configuration: Path,
) -> None:
    """Test the matrix header and the summary print an implementation name as typed."""
    result = invoke_cli("test", "sorting", "--configuration", str(odd_configuration))

    assert result.exit_code == 0, result.stderr
    assert "[red]odd[/red]" in find_table_header(result.stdout)
    assert "[red]odd[/red]: 1/1 cases passed" in result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_a_name_with_markup_is_shown_literally_when_its_build_fails(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test the build message prints an implementation name as typed."""
    configure(
        build_configured_entry(
            "[red]odd[/red]", python_sort_executable, build_command=FAILING_BUILD
        )
    )

    result = invoke_cli("test", "sorting")

    assert "Building [red]odd[/red]" in result.stderr


@pytest.mark.usefixtures("wide_terminal")
@pytest.mark.parametrize("command", ["list", "test", "benchmark", "debug"])
def test_the_configuration_option_says_the_parents_are_searched(command: str) -> None:
    """Test the help of the configuration option says parent directories are searched."""
    text = read_help_text(command)

    assert "nearest parent directory that has one" in text
    assert "up to a directory that contains .git" in text


@pytest.mark.usefixtures("wide_terminal")
@pytest.mark.parametrize("command", ["list", "test", "benchmark", "debug"])
def test_the_problem_module_option_accepts_a_module_name_or_a_file_path(
    command: str,
) -> None:
    """Test the help of the problem module option says it takes a module name or a path."""
    text = read_help_text(command)

    assert "a module name" in text
    assert "looked up in the current directory too" in text
    assert "the path of a .py file" in text


def test_it_prints_the_version_and_exits() -> None:
    """Test the version option prints the name and version of the program and nothing else."""
    result = invoke_cli("--version")

    assert result.exit_code == 0
    assert result.stdout == f"algorithm-playground {__version__}\n"


def test_it_is_in_the_help() -> None:
    """Test the help of the program lists the version option."""
    assert "--version" in invoke_cli("--help").stdout


def test_ctrl_c_in_the_stepper_exits_with_130(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test an interrupt while stepping ends debug with exit code 130."""
    replace_command_dependencies(monkeypatch, step_through=raise_keyboard_interrupt)

    result = invoke_cli(
        "debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5"
    )

    assert_exits_with(result, 130)
    assert "Interrupted." in result.stderr


@pytest.mark.parametrize("command", ["test", "benchmark"])
def test_ctrl_c_during_a_run_exits_with_130_like_everywhere_else(
    monkeypatch: pytest.MonkeyPatch,
    python_sort_executable: Path,
    command: str,
) -> None:
    """Test an interrupt during a test or benchmark run ends the command with exit code 130."""
    replace_command_dependencies(
        monkeypatch,
        run_tests=raise_keyboard_interrupt,
        run_benchmark=raise_keyboard_interrupt,
    )

    result = invoke_cli(command, "sorting", str(python_sort_executable))

    assert_exits_with(result, 130)
    assert "Interrupted." in result.stderr
