"""Tests for resolving the implementations named on the command line."""

from pathlib import Path

import pytest

from algorithm_playground.cli.implementation_selection import (
    EnvironmentPolicy,
    SelectionError,
    discover_configuration,
    require_single,
    select_implementations,
    selection_arguments,
)
from algorithm_playground.core.configuration import (
    DEFAULT_CONFIGURATION_FILE_NAME,
    Configuration,
    ConfigurationError,
    ConfiguredImplementation,
)
from algorithm_playground.core.implementation import Implementation


def build_configuration(tmp_path: Path, *entries: tuple[str, Implementation]) -> Configuration:
    """Build a configuration whose entries are (problem name, implementation) pairs."""
    return Configuration(
        path=tmp_path / DEFAULT_CONFIGURATION_FILE_NAME,
        configured_implementations=tuple(
            ConfiguredImplementation(problem_name, implementation)
            for problem_name, implementation in entries
        ),
    )


@pytest.fixture
def configured_c(tmp_path: Path) -> Implementation:
    """A configured implementation that has a build command."""
    return Implementation(
        name="sort-c",
        command=("./build/sort",),
        working_directory=tmp_path,
        build_command=("make",),
    )


@pytest.fixture
def configured_python(tmp_path: Path) -> Implementation:
    """A configured implementation that inherits the environment."""
    return Implementation(
        name="sort-python",
        command=("python3", "sort.py"),
        working_directory=tmp_path,
        inherit_environment=True,
    )


@pytest.fixture
def configuration(
    tmp_path: Path, configured_c: Implementation, configured_python: Implementation
) -> Configuration:
    """A configuration with two implementations for sorting and one for another problem."""
    return build_configuration(
        tmp_path,
        ("sorting", configured_c),
        ("sorting", configured_python),
        ("searching", Implementation(name="search", command=("./search",))),
    )


@pytest.fixture
def script(tmp_path: Path) -> Path:
    """An empty file named sort.py in a subdirectory."""
    path = tmp_path / "scripts" / "sort.py"
    path.parent.mkdir()
    path.write_text("")
    return path


class TestConfiguredNames:
    def test_resolves_a_configured_name_to_the_configured_implementation(
        self, configuration: Configuration, configured_c: Implementation
    ) -> None:
        """Test a configured name resolves to the configured implementation."""
        selected = select_implementations("sorting", ["sort-c"], [], configuration=configuration)

        assert selected == (configured_c,)

    def test_names_are_looked_up_for_the_given_problem_only(
        self, configuration: Configuration
    ) -> None:
        """Test a name configured for another problem is not resolved."""
        with pytest.raises(SelectionError, match="'search' is neither"):
            select_implementations("sorting", ["search"], [], configuration=configuration)

    def test_unknown_name_lists_the_configured_names(self, configuration: Configuration) -> None:
        """Test an unknown name is reported with the configured names and file."""
        with pytest.raises(SelectionError, match="'nope'") as raised:
            select_implementations("sorting", ["nope"], [], configuration=configuration)

        message = str(raised.value)
        assert "'nope'" in message
        assert "'sort-c', 'sort-python'" in message
        assert configuration.display_path in message

    def test_unknown_name_shows_the_configuration_relative_to_the_current_directory(
        self, tmp_path: Path, configuration: Configuration, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test an unknown name shows the configuration file relative to the working directory."""
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SelectionError, match="'nope'") as raised:
            select_implementations("sorting", ["nope"], [], configuration=configuration)

        assert f"configured in {DEFAULT_CONFIGURATION_FILE_NAME} for" in str(raised.value)

    def test_unknown_name_without_a_configuration_says_so(self) -> None:
        """Test an unknown name without a configuration file says none was found."""
        with pytest.raises(SelectionError, match="no configuration file was found"):
            select_implementations("sorting", ["nope"], [], configuration=None)

    def test_a_configured_name_wins_over_a_file_of_the_same_name(
        self,
        tmp_path: Path,
        configuration: Configuration,
        configured_c: Implementation,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test a configured name takes precedence over a file with the same name."""
        (tmp_path / "sort-c").write_text("")
        monkeypatch.chdir(tmp_path)

        selected = select_implementations("sorting", ["sort-c"], [], configuration=configuration)

        assert selected == (configured_c,)


class TestPaths:
    def test_a_path_becomes_an_absolute_command_named_after_the_file(self, script: Path) -> None:
        """Test a path becomes an absolute command named after the file."""
        (implementation,) = select_implementations("sorting", [str(script)], [], configuration=None)

        assert implementation.name == "sort.py"
        assert implementation.command == (str(script.resolve()),)
        assert implementation.working_directory is None

    def test_a_missing_path_is_an_error(self, tmp_path: Path) -> None:
        """Test a path that does not exist is rejected."""
        with pytest.raises(SelectionError, match="neither a configured implementation name"):
            select_implementations(
                "sorting", [str(tmp_path / "missing.py")], [], configuration=None
            )

    def test_a_directory_is_not_an_implementation(self, tmp_path: Path) -> None:
        """Test a directory is rejected as an implementation."""
        with pytest.raises(SelectionError, match="neither a configured implementation name"):
            select_implementations("sorting", [str(tmp_path)], [], configuration=None)

    def test_equal_file_names_fall_back_to_the_text_as_typed(self, tmp_path: Path) -> None:
        """Test files with equal names are named after the text as typed."""
        first = tmp_path / "first" / "sort.py"
        second = tmp_path / "second" / "sort.py"
        for path in (first, second):
            path.parent.mkdir()
            path.write_text("")

        selected = select_implementations(
            "sorting", [str(first), str(second)], [], configuration=None
        )

        assert [implementation.name for implementation in selected] == [str(first), str(second)]

    def test_only_colliding_names_fall_back(self, tmp_path: Path) -> None:
        """Test only the files whose names collide are named after the text as typed."""
        first = tmp_path / "first" / "sort.py"
        second = tmp_path / "second" / "sort.py"
        other = tmp_path / "other.py"
        for path in (first, second, other):
            path.parent.mkdir(exist_ok=True)
            path.write_text("")

        selected = select_implementations(
            "sorting", [str(first), str(other), str(second)], [], configuration=None
        )

        assert [implementation.name for implementation in selected] == [
            str(first),
            "other.py",
            str(second),
        ]

    def test_the_same_path_twice_is_a_duplicate(self, script: Path) -> None:
        """Test naming the same path twice is rejected as a duplicate."""
        with pytest.raises(SelectionError, match="unique"):
            select_implementations("sorting", [str(script), str(script)], [], configuration=None)

    def test_a_file_name_that_collides_with_a_configured_name_falls_back(
        self, tmp_path: Path, configured_c: Implementation
    ) -> None:
        """Test a file named like a configured implementation is named after its text."""
        colliding = tmp_path / "sort-c"
        colliding.write_text("")
        configuration = build_configuration(tmp_path, ("sorting", configured_c))

        selected = select_implementations(
            "sorting", ["sort-c", str(colliding)], [], configuration=configuration
        )

        assert [implementation.name for implementation in selected] == ["sort-c", str(colliding)]


class TestCommandText:
    def test_command_text_is_split_and_named_after_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test command text is split into a command and named after itself."""
        monkeypatch.chdir(tmp_path)

        (implementation,) = select_implementations(
            "sorting", [], ["node 'my sort.js'"], configuration=None
        )

        assert implementation.name == "node 'my sort.js'"
        assert implementation.command == ("node", "my sort.js")

    def test_command_text_is_named_after_the_file_it_runs(self, script: Path) -> None:
        """Test command text that runs an existing file is named after that file."""
        (implementation,) = select_implementations(
            "sorting", [], [f"python3 {script}"], configuration=None
        )

        assert implementation.name == "sort"
        assert implementation.command == ("python3", str(script))

    def test_commands_running_equally_named_files_fall_back_to_their_text(
        self, tmp_path: Path
    ) -> None:
        """Test commands that run equally named files are named after their text."""
        first = tmp_path / "first" / "sort.py"
        second = tmp_path / "second" / "sort.py"
        for path in (first, second):
            path.parent.mkdir()
            path.write_text("")
        texts = [f"python3 {first}", f"python3 {second}"]

        selected = select_implementations("sorting", [], texts, configuration=None)

        assert [implementation.name for implementation in selected] == texts

    def test_a_command_and_a_path_naming_the_same_file_have_names_of_their_own(
        self, script: Path
    ) -> None:
        """Test a command and a path that name the same file keep their own names."""
        text = f"python3 {script}"

        selected = select_implementations("sorting", [str(script)], [text], configuration=None)

        assert [implementation.name for implementation in selected] == ["sort.py", "sort"]

    def test_commands_are_named_in_order_by_the_names_given(self) -> None:
        """Test names given for commands apply in order and the rest keep their text."""
        selected = select_implementations(
            "sorting", [], ["node a.js", "ruby b.rb"], configuration=None, command_names=["first"]
        )

        assert [implementation.name for implementation in selected] == ["first", "ruby b.rb"]

    def test_more_names_than_commands_are_an_error(self) -> None:
        """Test giving more names than commands is rejected."""
        with pytest.raises(SelectionError, match="--name was given 2 times, but there are only 1"):
            select_implementations(
                "sorting", [], ["node a.js"], configuration=None, command_names=["a", "b"]
            )

    def test_two_commands_given_the_same_name_are_an_error(self) -> None:
        """Test giving two commands the same name is rejected."""
        with pytest.raises(SelectionError, match="must be unique"):
            select_implementations(
                "sorting",
                [],
                ["node a.js", "node b.js"],
                configuration=None,
                command_names=["same", "same"],
            )

    def test_empty_command_text_is_an_error(self) -> None:
        """Test blank command text is rejected."""
        with pytest.raises(SelectionError, match="--command"):
            select_implementations("sorting", [], ["   "], configuration=None)

    def test_unbalanced_quotes_are_an_error(self) -> None:
        """Test command text with unbalanced quotes is rejected."""
        with pytest.raises(SelectionError, match="--command"):
            select_implementations("sorting", [], ["node 'sort.js"], configuration=None)

    def test_repeated_commands_are_kept_in_order(self) -> None:
        """Test several commands are kept in the order given."""
        selected = select_implementations(
            "sorting", [], ["node a.js", "ruby b.rb"], configuration=None
        )

        assert [implementation.command for implementation in selected] == [
            ("node", "a.js"),
            ("ruby", "b.rb"),
        ]

    def test_selectors_come_before_commands(
        self,
        configuration: Configuration,
        script: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test selected implementations are listed before commands."""
        monkeypatch.chdir(tmp_path)

        selected = select_implementations(
            "sorting",
            ["sort-c", str(script)],
            ["node a.js"],
            configuration=configuration,
        )

        assert [implementation.name for implementation in selected] == [
            "sort-c",
            "sort.py",
            "node a.js",
        ]

    def test_the_same_command_twice_is_a_duplicate(self) -> None:
        """Test giving the same command twice is rejected as a duplicate."""
        with pytest.raises(SelectionError, match="unique"):
            select_implementations("sorting", [], ["node a.js", "node a.js"], configuration=None)


class TestDefaults:
    def test_no_implementation_given_uses_every_configured_one_for_the_problem(
        self,
        configuration: Configuration,
        configured_c: Implementation,
        configured_python: Implementation,
    ) -> None:
        """Test naming nothing selects every implementation configured for the problem."""
        selected = select_implementations("sorting", [], [], configuration=configuration)

        assert selected == (configured_c, configured_python)

    def test_no_implementation_and_no_configuration_explains_both_ways(self) -> None:
        """Test naming nothing without a configuration explains how to name implementations."""
        with pytest.raises(SelectionError, match="No implementation was given") as raised:
            select_implementations("sorting", [], [], configuration=None)

        message = str(raised.value)
        assert "--command" in message
        assert DEFAULT_CONFIGURATION_FILE_NAME in message
        assert "--configuration" in message

    def test_a_configuration_without_entries_for_the_problem_is_an_error(
        self, configuration: Configuration
    ) -> None:
        """Test a configuration with no entries for the problem is rejected."""
        with pytest.raises(SelectionError, match="configures none for it"):
            select_implementations("graphs", [], [], configuration=configuration)

    def test_explicit_implementations_replace_the_configured_defaults(
        self, configuration: Configuration
    ) -> None:
        """Test naming an implementation replaces the configured defaults."""
        selected = select_implementations("sorting", [], ["node a.js"], configuration=configuration)

        assert [implementation.name for implementation in selected] == ["node a.js"]


class TestInheritEnvironment:
    @pytest.fixture
    def selected(self, configuration: Configuration, script: Path) -> tuple[Implementation, ...]:
        """Two configured implementations, a path and a command, selected with inheritance."""
        return select_implementations(
            "sorting",
            ["sort-c", "sort-python", str(script)],
            ["node a.js"],
            configuration=configuration,
            environment_policy=EnvironmentPolicy.INHERIT,
        )

    def test_configured_implementations_keep_their_own_setting(
        self,
        selected: tuple[Implementation, ...],
        configured_c: Implementation,
        configured_python: Implementation,
    ) -> None:
        """Test inheriting the environment leaves configured implementations unchanged."""
        assert selected[0] == configured_c
        assert selected[0].inherit_environment is False
        assert selected[1] == configured_python
        assert selected[1].inherit_environment is True

    def test_paths_and_commands_inherit_the_environment(
        self, selected: tuple[Implementation, ...]
    ) -> None:
        """Test inheriting the environment applies to paths and commands."""
        assert selected[2].inherit_environment is True
        assert selected[3].inherit_environment is True

    def test_is_off_by_default(self, script: Path) -> None:
        """Test implementations do not inherit the environment unless asked to."""
        (implementation,) = select_implementations("sorting", [str(script)], [], configuration=None)

        assert implementation.inherit_environment is False


class TestRequireSingle:
    def test_returns_the_only_implementation(self, configured_c: Implementation) -> None:
        """Test the only implementation is returned."""
        assert require_single([configured_c], command_name="debug") is configured_c

    def test_several_implementations_are_an_error_naming_them(
        self, configured_c: Implementation, configured_python: Implementation
    ) -> None:
        """Test several implementations are rejected with their names listed."""
        with pytest.raises(SelectionError, match="'sort-c', 'sort-python'"):
            require_single([configured_c, configured_python], command_name="debug")

    def test_no_implementation_is_an_error(self) -> None:
        """Test an empty selection is rejected."""
        with pytest.raises(SelectionError, match="exactly one"):
            require_single([], command_name="debug")


class TestDiscoverConfiguration:
    ENTRY = '[[implementations]]\nname = "a"\nproblem = "sorting"\ncommand = "./a"\n'

    def test_an_explicit_path_is_loaded(self, tmp_path: Path) -> None:
        """Test a configuration file named by path is loaded."""
        path = tmp_path / "custom.toml"
        path.write_text(self.ENTRY)

        configuration = discover_configuration(path, tmp_path / "elsewhere")

        assert configuration is not None
        assert configuration.find("sorting", "a") is not None

    def test_the_default_file_in_the_directory_is_used(self, tmp_path: Path) -> None:
        """Test the default configuration file in the directory is used when none is named."""
        (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("")

        configuration = discover_configuration(None, tmp_path)

        assert configuration is not None
        assert configuration.path == tmp_path / DEFAULT_CONFIGURATION_FILE_NAME

    def test_no_default_file_means_no_configuration(self, tmp_path: Path) -> None:
        """Test no configuration is found when the directory has no default file."""
        assert discover_configuration(None, tmp_path) is None

    def test_an_explicit_path_that_does_not_exist_is_an_error(self, tmp_path: Path) -> None:
        """Test a named configuration file that does not exist is rejected."""
        with pytest.raises(ConfigurationError, match="not found"):
            discover_configuration(tmp_path / "missing.toml", tmp_path)

    def test_an_invalid_default_file_is_an_error(self, tmp_path: Path) -> None:
        """Test an invalid default configuration file is rejected."""
        (tmp_path / DEFAULT_CONFIGURATION_FILE_NAME).write_text("not valid toml [")

        with pytest.raises(ConfigurationError, match="invalid TOML"):
            discover_configuration(None, tmp_path)


class TestSelectionArguments:
    def test_a_configured_implementation_is_named(
        self, configuration: Configuration, configured_c: Implementation
    ) -> None:
        """Test a configured implementation is selected again by its name."""
        arguments = selection_arguments("sorting", configured_c, configuration)

        assert arguments == ("sort-c",)

    def test_a_path_implementation_is_given_as_its_full_command(self, tmp_path: Path) -> None:
        """Test an implementation made from a path is selected again by its full command."""
        script = tmp_path / "my sort.py"
        implementation = Implementation.from_executable(script)

        arguments = selection_arguments("sorting", implementation, None)

        assert arguments == ("--command", f"'{script.resolve()}'")

    def test_an_inherited_environment_is_repeated(self) -> None:
        """Test an implementation that inherits the environment repeats the option."""
        implementation = Implementation(
            name="node sort.js", command=("node", "sort.js"), inherit_environment=True
        )

        arguments = selection_arguments("sorting", implementation, None)

        assert arguments == ("--command", "node sort.js", "--inherit-environment")

    def test_an_implementation_configured_for_another_problem_is_not_named(
        self, configuration: Configuration, configured_c: Implementation
    ) -> None:
        """Test an implementation configured for another problem is selected by command."""
        arguments = selection_arguments("searching", configured_c, configuration)

        assert arguments[0] == "--command"
