"""Tests for reading, finding, and checking the configuration file."""

import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from algorithm_playground.core import (
    DEFAULT_CONFIGURATION_FILE_NAME,
    ConfigurationError,
    Implementation,
    ProblemSource,
    ProblemSourceKind,
    check_configured_problems,
    find_configuration,
    list_problem_sources,
    load_configuration,
    load_configured_problems,
)


def write_configuration(
    directory: Path, text: str, name: str = "configuration.toml"
) -> Path:
    """Write dedented configuration text to a file in ``directory`` and return its path."""
    path = directory / name
    path.write_text(textwrap.dedent(text))
    return path


def build_entry_text(**fields: str | None) -> str:
    """Build one ``[[implementations]]`` entry; values are TOML literals, ``None`` drops a key."""
    values: dict[str, str | None] = {
        "name": '"x"',
        "problem": '"sorting"',
        "command": '"./x"',
    }
    values.update(fields)
    body = "\n".join(
        f"{key} = {value}" for key, value in values.items() if value is not None
    )
    return f"[[implementations]]\n{body}\n"


def load_implementation(path: Path, problem_name: str, name: str) -> Implementation:
    """Load a configuration file and return the implementation it configures, which must exist."""
    implementation = load_configuration(path).find(problem_name, name)
    assert implementation is not None
    return implementation


def load_invalid_configuration(directory: Path, text: str) -> str:
    """Load configuration text that must be rejected and return the message naming the file."""
    path = write_configuration(directory, text)
    with pytest.raises(ConfigurationError, match=re.escape(str(path))) as raised:
        load_configuration(path)
    return str(raised.value)


@pytest.fixture
def configured_problem_module(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> Path:
    """A configuration file that adds a ``libs`` path and names a module registering a problem."""
    forget_modules("configuration_test_problems")
    (tmp_path / "libs").mkdir()
    (tmp_path / "libs" / "configuration_test_problems.py").write_text(
        "from algorithm_playground.core import register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
        "@register_problem\n"
        "class Variant(SortingProblem):\n"
        "    name = 'configured-variant'\n"
    )
    return write_configuration(
        tmp_path,
        """\
        python_paths = ["libs"]
        problem_modules = ["configuration_test_problems"]
        """,
    )


def test_loads_a_full_entry(tmp_path: Path) -> None:
    """Test an entry that sets every key is loaded with all of its values."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "merge-sort-c"
            problem = "sorting"
            command = "./build/merge_sort --fast"
            build_command = "make build/merge_sort"
            working_directory = "solutions"
            inherit_environment = true
            """,
    )

    configuration = load_configuration(path)

    implementation = configuration.find("sorting", "merge-sort-c")
    assert implementation is not None
    assert implementation.command == ("./build/merge_sort", "--fast")
    assert implementation.build_command == ("make", "build/merge_sort")
    assert implementation.working_directory == (tmp_path / "solutions").resolve()
    assert implementation.inherit_environment is True
    assert configuration.path == path


def test_command_and_build_command_accept_lists(tmp_path: Path) -> None:
    """Test the command and the build command may be given as lists of arguments."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "java"
            problem = "sorting"
            command = ["java", "-jar", "My Sort.jar"]
            build_command = ["javac", "Sort.java"]
            """,
    )

    implementation = load_implementation(path, "sorting", "java")

    assert implementation.command == ("java", "-jar", "My Sort.jar")
    assert implementation.build_command == ("javac", "Sort.java")


def test_optional_keys_take_their_defaults(tmp_path: Path) -> None:
    """Test an entry with only the required keys leaves the optional settings at defaults."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "plain"
            problem = "sorting"
            command = "./plain"
            """,
    )

    implementation = load_implementation(path, "sorting", "plain")

    assert implementation.build_command is None
    assert implementation.inherit_environment is False
    assert implementation.environment == {}
    assert implementation.timeout_seconds is None
    assert implementation.working_directory == tmp_path.resolve()


def test_environment_values_may_name_the_configuration_directory(
    tmp_path: Path,
) -> None:
    """Test the placeholder for the configuration directory is replaced in the environment."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "helper"
            problem = "sorting"
            command = "python3 sort.py"
            environment = { PYTHONPATH = "{configuration_directory}/lib", LEVEL = "{debug}" }
            """,
    )

    implementation = load_implementation(path, "sorting", "helper")

    assert implementation.environment == {
        "PYTHONPATH": f"{tmp_path.resolve()}/lib",
        "LEVEL": "{debug}",
    }


def test_the_environment_is_independent_of_the_working_directory(
    tmp_path: Path,
) -> None:
    """Test the configuration directory placeholder ignores the working directory setting."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "helper"
            problem = "sorting"
            command = "./x"
            working_directory = "solutions"
            environment = { HERE = "{configuration_directory}" }
            """,
    )

    implementation = load_implementation(path, "sorting", "helper")

    assert implementation.environment == {"HERE": str(tmp_path.resolve())}


@pytest.mark.parametrize(
    ("literal", "expected"), [("30", 30.0), ("0.5", 0.5), ("2.5e1", 25.0)]
)
def test_timeout_seconds_is_a_positive_number(
    tmp_path: Path, literal: str, expected: float
) -> None:
    """Test the timeout may be an integer or a float of seconds."""
    path = write_configuration(tmp_path, build_entry_text(timeout_seconds=literal))

    implementation = load_implementation(path, "sorting", "x")

    assert implementation.timeout_seconds == expected


def test_working_directory_is_relative_to_the_file_not_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test a relative working directory is resolved against the configuration file."""
    configuration_directory = tmp_path / "solutions"
    configuration_directory.mkdir()
    path = write_configuration(
        configuration_directory,
        """\
            [[implementations]]
            name = "plain"
            problem = "sorting"
            command = "./plain"
            working_directory = "../elsewhere"
            """,
    )
    monkeypatch.chdir(tmp_path)

    implementation = load_implementation(path, "sorting", "plain")

    assert implementation.working_directory == (tmp_path / "elsewhere").resolve()


def test_a_byte_order_mark_is_ignored(tmp_path: Path) -> None:
    """Test a file that starts with a UTF-8 byte order mark loads normally."""
    path = tmp_path / "configuration.toml"
    path.write_bytes(
        b"\xef\xbb\xbf"
        b'[[implementations]]\nname = "x"\nproblem = "sorting"\ncommand = "./x"\n'
    )

    assert load_configuration(path).find("sorting", "x") is not None


def test_display_path_is_the_full_path_outside_the_current_directory(
    tmp_path: Path,
) -> None:
    """Test the display path of a file outside the current directory is its full path."""
    path = write_configuration(tmp_path, "", name="settings.toml")

    configuration = load_configuration(path)

    assert configuration.display_path == str(path)


def test_display_path_is_relative_inside_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test the display path of a file inside the current directory is relative to it."""
    path = write_configuration(tmp_path, "", name="settings.toml")
    configuration = load_configuration(path)
    monkeypatch.chdir(tmp_path)

    assert configuration.display_path == "settings.toml"


def test_empty_file_has_no_implementations(tmp_path: Path) -> None:
    """Test an empty file configures no implementations."""
    configuration = load_configuration(write_configuration(tmp_path, ""))

    assert configuration.configured_implementations == ()
    assert configuration.implementations_for("sorting") == ()


def test_implementations_for_filters_by_problem_in_file_order(tmp_path: Path) -> None:
    """Test the implementations of one problem are listed in the order of the file."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "first"
            problem = "sorting"
            command = "./first"

            [[implementations]]
            name = "other"
            problem = "searching"
            command = "./other"

            [[implementations]]
            name = "second"
            problem = "sorting"
            command = "./second"
            """,
    )
    configuration = load_configuration(path)

    names = [item.name for item in configuration.implementations_for("sorting")]

    assert names == ["first", "second"]
    assert [item.name for item in configuration.implementations_for("searching")] == [
        "other"
    ]
    assert configuration.implementations_for("unknown") == ()


def test_same_name_is_allowed_for_different_problems(tmp_path: Path) -> None:
    """Test two problems may each have an implementation with the same name."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "fast"
            problem = "sorting"
            command = "./sort"

            [[implementations]]
            name = "fast"
            problem = "searching"
            command = "./search"
            """,
    )

    sorting = load_implementation(path, "sorting", "fast")
    searching = load_implementation(path, "searching", "fast")

    assert sorting.command == ("./sort",)
    assert searching.command == ("./search",)


def test_find_returns_none_for_unknown_names(tmp_path: Path) -> None:
    """Test looking up a name or a problem that is not configured finds nothing."""
    path = write_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "known"
            problem = "sorting"
            command = "./known"
            """,
    )
    configuration = load_configuration(path)

    assert configuration.find("sorting", "unknown") is None
    assert configuration.find("searching", "known") is None


def test_a_file_inside_the_current_directory_is_named_relative_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test an error about a file inside the current directory names it by relative path."""
    path = write_configuration(tmp_path, "[[implementations\n", name="settings.toml")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(
        ConfigurationError, match=r"^settings\.toml: invalid TOML"
    ) as raised:
        load_configuration(path)

    assert str(tmp_path) not in str(raised.value)


def test_a_file_outside_the_current_directory_is_named_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test an error about a file outside the current directory names it by full path."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = write_configuration(tmp_path, "[[implementations\n")
    monkeypatch.chdir(elsewhere)

    with pytest.raises(ConfigurationError, match=f"^{re.escape(str(path))}"):
        load_configuration(path)


def test_missing_file(tmp_path: Path) -> None:
    """Test a path that does not exist is a configuration error."""
    with pytest.raises(ConfigurationError, match="configuration file not found"):
        load_configuration(tmp_path / "missing.toml")


def test_unreadable_path(tmp_path: Path) -> None:
    """Test a path that cannot be read as a file is a configuration error."""
    with pytest.raises(ConfigurationError, match="could not read configuration file"):
        load_configuration(tmp_path)


def test_invalid_toml(tmp_path: Path) -> None:
    """Test text that is not valid TOML is a configuration error."""
    message = load_invalid_configuration(tmp_path, "[[implementations\n")

    assert "invalid TOML" in message


def test_unknown_top_level_key(tmp_path: Path) -> None:
    """Test an unknown top-level key is named, with the allowed keys and a version hint."""
    message = load_invalid_configuration(
        tmp_path, 'surprise = 1\n[[implementations]]\nname = "x"\n'
    )

    assert "unknown top-level key(s): surprise" in message
    assert "Allowed keys: implementations" in message
    assert "newer algorithm-playground" in message


def test_implementations_must_be_an_array_of_tables(tmp_path: Path) -> None:
    """Test the implementations key must hold an array of tables."""
    message = load_invalid_configuration(tmp_path, "implementations = 3\n")

    assert "array of tables" in message


def test_unknown_entry_key_names_index_and_name(tmp_path: Path) -> None:
    """Test an unknown key in an entry is reported with the index and name of the entry."""
    message = load_invalid_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "ok"
            problem = "sorting"
            command = "./ok"

            [[implementations]]
            name = "bad"
            problem = "sorting"
            command = "./bad"
            colour = "red"
            """,
    )

    assert "implementations[1] ('bad')" in message
    assert "unknown key(s): colour" in message
    assert "newer algorithm-playground" in message


def test_the_former_build_key_is_unknown(tmp_path: Path) -> None:
    """Test the old 'build' key is rejected with a pointer to 'build_command'."""
    message = load_invalid_configuration(tmp_path, build_entry_text(build='"make"'))

    assert "unknown key(s): build." in message
    assert "build_command" in message


@pytest.mark.parametrize("key", ["name", "problem", "command"])
def test_missing_required_key(tmp_path: Path, key: str) -> None:
    """Test an entry without a required key is reported with the key and the entry index."""
    message = load_invalid_configuration(tmp_path, build_entry_text(**{key: None}))

    assert f"missing required key '{key}'" in message
    assert "implementations[0]" in message


@pytest.mark.parametrize("key", ["name", "problem"])
@pytest.mark.parametrize("value", ['""', "3"], ids=["empty-text", "number"])
def test_name_and_problem_must_be_non_empty_strings(
    tmp_path: Path, key: str, value: str
) -> None:
    """Test the name and problem must be non-empty text."""
    message = load_invalid_configuration(tmp_path, build_entry_text(**{key: value}))

    assert f"'{key}' must be a non-empty string" in message


@pytest.mark.parametrize(
    "value",
    ['""', "[]", "[1, 2]", '["a", ""]', "3"],
    ids=["empty-text", "empty-list", "numbers", "empty-argument", "number"],
)
def test_invalid_command_values(tmp_path: Path, value: str) -> None:
    """Test a command that is not a non-empty text or list of text is reported."""
    message = load_invalid_configuration(tmp_path, build_entry_text(command=value))

    assert "'command'" in message
    assert "implementations[0] ('x')" in message


def test_invalid_build_value(tmp_path: Path) -> None:
    """Test a build command that is not a command is reported."""
    message = load_invalid_configuration(tmp_path, build_entry_text(build_command="3"))

    assert "'build_command' must be a command string" in message


def test_unbalanced_quote_in_command_text(tmp_path: Path) -> None:
    """Test command text with an unclosed quote is reported as unparseable."""
    message = load_invalid_configuration(
        tmp_path, build_entry_text(command='"node \'sort.js"')
    )

    assert "Could not parse command" in message


def test_working_directory_must_be_a_non_empty_string(tmp_path: Path) -> None:
    """Test the working directory must be non-empty text."""
    message = load_invalid_configuration(
        tmp_path, build_entry_text(working_directory="3")
    )

    assert "'working_directory' must be a non-empty string" in message


def test_inherit_environment_must_be_boolean(tmp_path: Path) -> None:
    """Test the inherit_environment setting must be true or false."""
    message = load_invalid_configuration(
        tmp_path, build_entry_text(inherit_environment='"yes"')
    )

    assert "'inherit_environment' must be true or false" in message


@pytest.mark.parametrize(
    "value",
    ["3", '"x"', "[]", "{ A = 1 }", '{ "A=B" = "x" }', '{ "" = "x" }'],
    ids=[
        "number",
        "text",
        "list",
        "number-value",
        "equals-sign-in-name",
        "empty-name",
    ],
)
def test_invalid_environment_values(tmp_path: Path, value: str) -> None:
    """Test an environment that is not a table of valid names to text is reported."""
    message = load_invalid_configuration(tmp_path, build_entry_text(environment=value))

    assert "implementations[0] ('x')" in message
    assert "environment" in message


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "true", '"soon"', "inf", "nan", "[3]"],
    ids=["zero", "negative", "boolean", "text", "infinite", "not-a-number", "list"],
)
def test_invalid_timeout_values(tmp_path: Path, value: str) -> None:
    """Test a timeout that is not a positive finite number is reported."""
    message = load_invalid_configuration(
        tmp_path, build_entry_text(timeout_seconds=value)
    )

    assert "'timeout_seconds' must be a positive number of seconds" in message


def test_duplicate_name_for_the_same_problem(tmp_path: Path) -> None:
    """Test two entries with the same name for one problem are reported."""
    message = load_invalid_configuration(
        tmp_path,
        """\
            [[implementations]]
            name = "twin"
            problem = "sorting"
            command = "./one"

            [[implementations]]
            name = "twin"
            problem = "sorting"
            command = "./two"
            """,
    )

    assert "implementations[1] ('twin')" in message
    assert "duplicate implementation name 'twin' for problem 'sorting'" in message


def test_finds_the_default_file_in_the_given_directory(tmp_path: Path) -> None:
    """Test the default file in the directory searched is found."""
    path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
    path.write_text("")

    assert find_configuration(tmp_path) == path.resolve()


def test_returns_none_when_absent(tmp_path: Path) -> None:
    """Test a search that finds no file returns nothing."""
    (tmp_path / ".git").mkdir()

    assert find_configuration(tmp_path) is None


def test_searches_the_parent_directories(tmp_path: Path) -> None:
    """Test a file in an ancestor directory is found."""
    path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
    path.write_text("")
    deep = tmp_path / "solutions" / "sorting" / "c"
    deep.mkdir(parents=True)

    assert find_configuration(deep) == path.resolve()


def test_the_nearest_file_wins(tmp_path: Path) -> None:
    """Test the file closest to the starting directory is the one found."""
    (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")
    inner = tmp_path / "inner"
    inner.mkdir()
    nearest = inner / DEFAULT_CONFIGURATION_FILE_NAME
    nearest.write_text("")

    assert find_configuration(inner) == nearest.resolve()


def test_the_search_stops_at_the_root_of_a_repository(tmp_path: Path) -> None:
    """Test the search does not leave the repository that contains the starting directory."""
    (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")
    repository = tmp_path / "repository"
    (repository / ".git").mkdir(parents=True)
    child = repository / "child"
    child.mkdir()

    assert find_configuration(child) is None


def test_the_repository_root_itself_is_searched(tmp_path: Path) -> None:
    """Test a file in the root directory of the repository is found."""
    (tmp_path / ".git").mkdir()
    path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
    path.write_text("")
    child = tmp_path / "child"
    child.mkdir()

    assert find_configuration(child) == path.resolve()


def test_a_git_file_marks_the_root_of_a_worktree(tmp_path: Path) -> None:
    """Test a '.git' file, as in a worktree, also ends the search."""
    (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere")

    assert find_configuration(worktree) is None


def test_ignores_a_directory_with_the_default_name(tmp_path: Path) -> None:
    """Test a directory that has the name of the configuration file is not a match."""
    (tmp_path / ".git").mkdir()
    (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).mkdir()

    assert find_configuration(tmp_path) is None


def test_modules_and_paths_are_read_with_paths_relative_to_the_file(
    tmp_path: Path,
) -> None:
    """Test problem modules are listed and python paths are resolved against the file."""
    (tmp_path / "libs").mkdir()
    path = write_configuration(
        tmp_path,
        """\
            problem_modules = ["solutions_problems.graphs", "extra"]
            python_paths = [".", "libs"]
            """,
    )

    configuration = load_configuration(path)

    assert configuration.problem_modules == ("solutions_problems.graphs", "extra")
    assert configuration.python_paths == (
        tmp_path.resolve(),
        (tmp_path / "libs").resolve(),
    )


def test_both_keys_default_to_empty(tmp_path: Path) -> None:
    """Test a file without problem modules and python paths lists none."""
    configuration = load_configuration(
        write_configuration(tmp_path, build_entry_text())
    )

    assert configuration.problem_modules == ()
    assert configuration.python_paths == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            'problem_modules = "graphs"',
            "'problem_modules' must be a list of module names",
        ),
        ('problem_modules = ["not a module"]', "'problem_modules' must be a list"),
        ('problem_modules = [""]', "'problem_modules' must be a list"),
        ("problem_modules = [1]", "'problem_modules' must be a list"),
        ('python_paths = "."', "'python_paths' must be a list"),
        ('python_paths = [""]', "'python_paths' must be a list"),
        (
            'python_paths = ["missing"]',
            r"'python_paths' entry 'missing' is not a directory",
        ),
    ],
    ids=[
        "modules-not-a-list",
        "module-not-a-name",
        "module-empty",
        "module-number",
        "paths-not-a-list",
        "path-empty",
        "path-missing",
    ],
)
def test_invalid_values_are_configuration_errors(
    tmp_path: Path, text: str, message: str
) -> None:
    """Test problem modules or python paths of the wrong shape are configuration errors."""
    path = write_configuration(tmp_path, text)

    with pytest.raises(ConfigurationError, match=message):
        load_configuration(path)


def test_loading_adds_the_paths_to_the_import_path(
    configured_problem_module: Path, tmp_path: Path
) -> None:
    """Test loading the configured problems puts the python paths first on sys.path."""
    load_configured_problems(load_configuration(configured_problem_module))

    assert sys.path[0] == str((tmp_path / "libs").resolve())


def test_loading_registers_the_modules_as_configuration(
    configured_problem_module: Path,
) -> None:
    """Test a problem registered by a configured module is recorded as coming from the file."""
    load_configured_problems(load_configuration(configured_problem_module))

    assert list_problem_sources()["configured-variant"] == ProblemSource(
        kind=ProblemSourceKind.CONFIGURATION, detail="configuration_test_problems"
    )


def test_a_module_that_cannot_be_imported_is_a_configuration_error_naming_the_file(
    tmp_path: Path,
) -> None:
    """Test a problem module that cannot be imported is an error naming file and module."""
    path = write_configuration(
        tmp_path, 'problem_modules = ["no_such_configured_module"]'
    )
    configuration = load_configuration(path)

    with pytest.raises(
        ConfigurationError, match=r"configuration\.toml.*no_such_configured_module"
    ):
        load_configured_problems(configuration)


def test_an_unknown_problem_name_is_a_configuration_error(tmp_path: Path) -> None:
    """Test an entry for a problem that is not registered is an error that lists the problems."""
    path = write_configuration(tmp_path, build_entry_text(problem='"graphs"'))
    configuration = load_configuration(path)

    with pytest.raises(
        ConfigurationError,
        match="implementation 'x' names unknown problem 'graphs'",
    ) as raised:
        check_configured_problems(configuration)

    message = str(raised.value)
    assert "Registered problems: sorting" in message
    assert "problem_modules" in message


def test_known_problem_names_pass_the_check(tmp_path: Path) -> None:
    """Test entries for registered problems pass the check."""
    configuration = load_configuration(
        write_configuration(tmp_path, build_entry_text())
    )

    check_configured_problems(configuration)
