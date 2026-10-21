"""Tests for loading implementations from a TOML configuration file."""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from algorithm_playground.core.configuration import (
    DEFAULT_CONFIGURATION_FILE_NAME,
    ConfigurationError,
    check_configured_problems,
    find_configuration,
    load_configuration,
    load_configured_problems,
)
from algorithm_playground.core.registry import ProblemSource, ProblemSourceKind, problem_sources


def write_configuration(directory: Path, text: str, name: str = "configuration.toml") -> Path:
    path = directory / name
    path.write_text(textwrap.dedent(text))
    return path


def entry_text(**fields: str | None) -> str:
    """Write one ``[[implementations]]`` entry; values are TOML literals, ``None`` drops a key."""
    values: dict[str, str | None] = {"name": '"x"', "problem": '"sorting"', "command": '"./x"'}
    values.update(fields)
    body = "\n".join(f"{key} = {value}" for key, value in values.items() if value is not None)
    return f"[[implementations]]\n{body}\n"


class TestLoadConfiguration:
    def test_loads_a_full_entry(self, tmp_path: Path) -> None:
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

    def test_command_and_build_command_accept_lists(self, tmp_path: Path) -> None:
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
        implementation = load_configuration(path).find("sorting", "java")
        assert implementation is not None
        assert implementation.command == ("java", "-jar", "My Sort.jar")
        assert implementation.build_command == ("javac", "Sort.java")

    def test_defaults(self, tmp_path: Path) -> None:
        path = write_configuration(
            tmp_path,
            """\
            [[implementations]]
            name = "plain"
            problem = "sorting"
            command = "./plain"
            """,
        )
        implementation = load_configuration(path).find("sorting", "plain")
        assert implementation is not None
        assert implementation.build_command is None
        assert implementation.inherit_environment is False
        assert implementation.environment == {}
        assert implementation.timeout_seconds is None
        assert implementation.working_directory == tmp_path.resolve()

    def test_environment_values_may_name_the_configuration_directory(self, tmp_path: Path) -> None:
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
        implementation = load_configuration(path).find("sorting", "helper")
        assert implementation is not None
        assert implementation.environment == {
            "PYTHONPATH": f"{tmp_path.resolve()}/lib",
            "LEVEL": "{debug}",
        }

    def test_the_environment_is_independent_of_the_working_directory(self, tmp_path: Path) -> None:
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
        implementation = load_configuration(path).find("sorting", "helper")
        assert implementation is not None
        assert implementation.environment == {"HERE": str(tmp_path.resolve())}

    @pytest.mark.parametrize(("literal", "expected"), [("30", 30.0), ("0.5", 0.5), ("2.5e1", 25.0)])
    def test_timeout_seconds_is_a_positive_number(
        self, tmp_path: Path, literal: str, expected: float
    ) -> None:
        implementation = load_configuration(
            write_configuration(tmp_path, entry_text(timeout_seconds=literal))
        ).find("sorting", "x")
        assert implementation is not None
        assert implementation.timeout_seconds == expected

    def test_working_directory_is_relative_to_the_file_not_the_caller(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        implementation = load_configuration(path).find("sorting", "plain")
        assert implementation is not None
        assert implementation.working_directory == (tmp_path / "elsewhere").resolve()

    def test_a_byte_order_mark_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "configuration.toml"
        path.write_bytes(
            b"\xef\xbb\xbf"
            + b'[[implementations]]\nname = "x"\nproblem = "sorting"\ncommand = "./x"\n'
        )
        assert load_configuration(path).find("sorting", "x") is not None

    def test_display_path_is_relative_inside_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_configuration(tmp_path, "", name="settings.toml")
        configuration = load_configuration(path)
        assert configuration.display_path == str(path)
        monkeypatch.chdir(tmp_path)
        assert configuration.display_path == "settings.toml"

    def test_empty_file_has_no_implementations(self, tmp_path: Path) -> None:
        configuration = load_configuration(write_configuration(tmp_path, ""))
        assert configuration.configured_implementations == ()
        assert configuration.implementations_for("sorting") == ()

    def test_implementations_for_filters_by_problem_in_file_order(self, tmp_path: Path) -> None:
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
        assert [item.name for item in configuration.implementations_for("searching")] == ["other"]
        assert configuration.implementations_for("unknown") == ()

    def test_same_name_is_allowed_for_different_problems(self, tmp_path: Path) -> None:
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
        configuration = load_configuration(path)
        sorting = configuration.find("sorting", "fast")
        searching = configuration.find("searching", "fast")
        assert sorting is not None and searching is not None
        assert sorting.command == ("./sort",)
        assert searching.command == ("./search",)

    def test_find_returns_none_for_unknown_names(self, tmp_path: Path) -> None:
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


class TestConfigurationErrors:
    def _error(self, tmp_path: Path, text: str) -> str:
        path = write_configuration(tmp_path, text)
        with pytest.raises(ConfigurationError) as raised:
            load_configuration(path)
        message = str(raised.value)
        assert str(path) in message
        return message

    def test_a_file_inside_the_current_directory_is_named_relative_to_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_configuration(tmp_path, "[[implementations\n", name="settings.toml")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigurationError) as raised:
            load_configuration(path)
        message = str(raised.value)
        assert message.startswith("settings.toml: invalid TOML")
        assert str(tmp_path) not in message

    def test_a_file_outside_the_current_directory_is_named_in_full(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        path = write_configuration(tmp_path, "[[implementations\n")
        monkeypatch.chdir(elsewhere)
        with pytest.raises(ConfigurationError) as raised:
            load_configuration(path)
        assert str(raised.value).startswith(str(path))

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="configuration file not found"):
            load_configuration(tmp_path / "missing.toml")

    def test_unreadable_path(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="could not read configuration file"):
            load_configuration(tmp_path)

    def test_invalid_toml(self, tmp_path: Path) -> None:
        assert "invalid TOML" in self._error(tmp_path, "[[implementations\n")

    def test_unknown_top_level_key(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, 'surprise = 1\n[[implementations]]\nname = "x"\n')
        assert "unknown top-level key(s): surprise" in message
        assert "Allowed keys: implementations" in message
        assert "newer algorithm-playground" in message

    def test_implementations_must_be_an_array_of_tables(self, tmp_path: Path) -> None:
        assert "array of tables" in self._error(tmp_path, "implementations = 3\n")

    def test_unknown_entry_key_names_index_and_name(self, tmp_path: Path) -> None:
        message = self._error(
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

    def test_the_former_build_key_is_unknown(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, entry_text(build='"make"'))
        assert "unknown key(s): build." in message
        assert "build_command" in message

    @pytest.mark.parametrize("key", ["name", "problem", "command"])
    def test_missing_required_key(self, tmp_path: Path, key: str) -> None:
        message = self._error(tmp_path, entry_text(**{key: None}))
        assert f"missing required key '{key}'" in message
        assert "implementations[0]" in message

    @pytest.mark.parametrize("key", ["name", "problem"])
    @pytest.mark.parametrize("value", ['""', "3"])
    def test_name_and_problem_must_be_non_empty_strings(
        self, tmp_path: Path, key: str, value: str
    ) -> None:
        message = self._error(tmp_path, entry_text(**{key: value}))
        assert f"'{key}' must be a non-empty string" in message

    @pytest.mark.parametrize("value", ['""', "[]", "[1, 2]", '["a", ""]', "3"])
    def test_invalid_command_values(self, tmp_path: Path, value: str) -> None:
        message = self._error(tmp_path, entry_text(command=value))
        assert "'command'" in message
        assert "implementations[0] ('x')" in message

    def test_invalid_build_value(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, entry_text(build_command="3"))
        assert "'build_command' must be a command string" in message

    def test_unbalanced_quote_in_command_text(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, entry_text(command='"node \'sort.js"'))
        assert "Could not parse command" in message

    def test_working_directory_must_be_a_non_empty_string(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, entry_text(working_directory="3"))
        assert "'working_directory' must be a non-empty string" in message

    def test_inherit_environment_must_be_boolean(self, tmp_path: Path) -> None:
        message = self._error(tmp_path, entry_text(inherit_environment='"yes"'))
        assert "'inherit_environment' must be true or false" in message

    @pytest.mark.parametrize(
        "value", ["3", '"x"', "[]", "{ A = 1 }", '{ "A=B" = "x" }', '{ "" = "x" }']
    )
    def test_invalid_environment_values(self, tmp_path: Path, value: str) -> None:
        message = self._error(tmp_path, entry_text(environment=value))
        assert "implementations[0] ('x')" in message
        assert "environment" in message

    @pytest.mark.parametrize("value", ["0", "-1", "true", '"soon"', "inf", "nan", "[3]"])
    def test_invalid_timeout_values(self, tmp_path: Path, value: str) -> None:
        message = self._error(tmp_path, entry_text(timeout_seconds=value))
        assert "'timeout_seconds' must be a positive number of seconds" in message

    def test_duplicate_name_for_the_same_problem(self, tmp_path: Path) -> None:
        message = self._error(
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


class TestFindConfiguration:
    def test_finds_the_default_file_in_the_given_directory(self, tmp_path: Path) -> None:
        path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
        path.write_text("")
        assert find_configuration(tmp_path) == path.resolve()

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert find_configuration(tmp_path) is None

    def test_searches_the_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
        path.write_text("")
        deep = tmp_path / "solutions" / "sorting" / "c"
        deep.mkdir(parents=True)
        assert find_configuration(deep) == path.resolve()

    def test_the_nearest_file_wins(self, tmp_path: Path) -> None:
        (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")
        inner = tmp_path / "inner"
        inner.mkdir()
        nearest = inner / DEFAULT_CONFIGURATION_FILE_NAME
        nearest.write_text("")
        assert find_configuration(inner) == nearest.resolve()

    def test_the_search_stops_at_the_root_of_a_repository(self, tmp_path: Path) -> None:
        (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")
        repository = tmp_path / "repository"
        (repository / ".git").mkdir(parents=True)
        child = repository / "child"
        child.mkdir()
        assert find_configuration(child) is None

    def test_the_repository_root_itself_is_searched(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        path = tmp_path / DEFAULT_CONFIGURATION_FILE_NAME
        path.write_text("")
        child = tmp_path / "child"
        child.mkdir()
        assert find_configuration(child) == path.resolve()

    def test_a_git_file_marks_the_root_of_a_worktree(self, tmp_path: Path) -> None:
        (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: elsewhere")
        assert find_configuration(worktree) is None

    def test_ignores_a_directory_with_the_default_name(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).mkdir()
        assert find_configuration(tmp_path) is None


class TestProblemModules:
    def test_modules_and_paths_are_read_with_paths_relative_to_the_file(
        self, tmp_path: Path
    ) -> None:
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
        assert configuration.python_paths == (tmp_path.resolve(), (tmp_path / "libs").resolve())

    def test_both_keys_default_to_empty(self, tmp_path: Path) -> None:
        configuration = load_configuration(write_configuration(tmp_path, entry_text()))
        assert configuration.problem_modules == ()
        assert configuration.python_paths == ()

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ('problem_modules = "graphs"', "'problem_modules' must be a list of module names"),
            ('problem_modules = ["not a module"]', "'problem_modules' must be a list"),
            ('problem_modules = [""]', "'problem_modules' must be a list"),
            ("problem_modules = [1]", "'problem_modules' must be a list"),
            ('python_paths = "."', "'python_paths' must be a list"),
            ('python_paths = [""]', "'python_paths' must be a list"),
            ('python_paths = ["missing"]', r"'python_paths' entry 'missing' is not a directory"),
        ],
    )
    def test_invalid_values_are_configuration_errors(
        self, tmp_path: Path, text: str, message: str
    ) -> None:
        path = write_configuration(tmp_path, text)
        with pytest.raises(ConfigurationError, match=message):
            load_configuration(path)

    def test_loading_adds_the_paths_and_registers_the_modules_as_configuration(
        self, tmp_path: Path, forget_modules: Callable[..., None]
    ) -> None:
        forget_modules("configuration_test_problems")
        (tmp_path / "libs").mkdir()
        (tmp_path / "libs" / "configuration_test_problems.py").write_text(
            "from algorithm_playground.core.registry import register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "@register_problem\n"
            "class Variant(SortingProblem):\n"
            "    name = 'configured-variant'\n"
        )
        path = write_configuration(
            tmp_path,
            """\
            python_paths = ["libs"]
            problem_modules = ["configuration_test_problems"]
            """,
        )
        load_configured_problems(load_configuration(path))
        assert sys.path[0] == str((tmp_path / "libs").resolve())
        assert problem_sources()["configured-variant"] == ProblemSource(
            ProblemSourceKind.CONFIGURATION, "configuration_test_problems"
        )

    def test_a_module_that_cannot_be_imported_is_a_configuration_error_naming_the_file(
        self, tmp_path: Path
    ) -> None:
        path = write_configuration(tmp_path, 'problem_modules = ["no_such_configured_module"]')
        with pytest.raises(
            ConfigurationError, match=r"configuration\.toml.*no_such_configured_module"
        ):
            load_configured_problems(load_configuration(path))

    def test_an_unknown_problem_name_is_a_configuration_error(self, tmp_path: Path) -> None:
        path = write_configuration(tmp_path, entry_text(problem='"graphs"'))
        with pytest.raises(ConfigurationError) as raised:
            check_configured_problems(load_configuration(path))
        message = str(raised.value)
        assert "implementation 'x' names unknown problem 'graphs'" in message
        assert "Registered problems: sorting" in message
        assert "problem_modules" in message

    def test_known_problem_names_pass_the_check(self, tmp_path: Path) -> None:
        check_configured_problems(load_configuration(write_configuration(tmp_path, entry_text())))
