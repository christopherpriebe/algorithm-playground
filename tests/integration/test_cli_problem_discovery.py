"""End-to-end CLI tests for problems that live outside this package."""

import importlib.metadata
import json
import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from helpers.support import Configure, assert_exits_with, invoke_cli, parse_table_rows
from typer.testing import Result

from algorithm_playground import __version__
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

ForgetModules = Callable[..., None]
WriteProblemModule = Callable[[str, str], None]

MODULE_TEXT = """\
from algorithm_playground.core import register_problem
from algorithm_playground.problems.sorting import SortingProblem


@register_problem
class Variant(SortingProblem):
    name = "{problem_name}"
    description = "A sorting variant defined outside the package."
"""


def read_help_text(command: str) -> str:
    """Return the help of a command with the box-drawing characters and line breaks removed."""
    output = invoke_cli(command, "--help").stdout
    return " ".join(re.sub(r"[│╭╮╰╯─]", " ", output).split())


@pytest.fixture
def problem_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forget_modules: ForgetModules
) -> WriteProblemModule:
    """Write an importable module that registers a problem, in a directory on ``sys.path``."""
    directory = tmp_path / "modules"
    directory.mkdir()
    monkeypatch.syspath_prepend(str(directory))

    def write(module_name: str, problem_name: str) -> None:
        forget_modules(module_name)
        (directory / f"{module_name}.py").write_text(MODULE_TEXT.format(problem_name=problem_name))

    return write


class TestProblemModuleOption:
    @pytest.mark.usefixtures("wide_terminal")
    def test_list_shows_the_problem_and_where_it_came_from(
        self, problem_module: WriteProblemModule
    ) -> None:
        """Test list shows a problem from a module with the module as its source."""
        problem_module("discovery_option_module", "option-variant")

        result = invoke_cli("list", "--problem-module", "discovery_option_module")

        assert result.exit_code == 0, result.stderr
        assert "option-variant" in result.stdout
        assert "option: discovery_option_module" in result.stdout
        assert "built-in" in result.stdout

    def test_a_loaded_problem_can_be_tested(
        self,
        problem_module: WriteProblemModule,
        python_sort_executable: Path,
    ) -> None:
        """Test an implementation can be tested against a problem loaded from a module."""
        problem_module("discovery_tested_module", "tested-variant")

        result = invoke_cli(
            "test",
            "tested-variant",
            str(python_sort_executable),
            "--problem-module",
            "discovery_tested_module",
            "--fixture",
            "single",
        )

        assert result.exit_code == 0, result.stderr
        assert "tested-variant" in result.stdout

    def test_the_reproduce_command_repeats_the_module_option(
        self,
        problem_module: WriteProblemModule,
        unsorted_output_executable: Path,
    ) -> None:
        """Test the printed reproduce command loads the problem module again."""
        problem_module("discovery_reproduce_module", "reproduced-variant")

        result = invoke_cli(
            "test",
            "reproduced-variant",
            str(unsorted_output_executable),
            "--problem-module",
            "discovery_reproduce_module",
            "--fixture",
            "two_unsorted",
        )

        assert result.exit_code == 1
        assert "--problem-module discovery_reproduce_module --case fixture:two_unsorted" in (
            result.stdout
        )

    def test_a_module_that_cannot_be_imported_is_a_usage_error(self) -> None:
        """Test a module that cannot be imported is a usage error naming the module."""
        result = invoke_cli("list", "--problem-module", "no_such_discovery_module")

        assert result.exit_code == 2
        assert "Could not load problem module 'no_such_discovery_module'" in result.stderr
        assert result.stdout == ""

    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    def test_every_command_accepts_the_option(
        self, python_sort_executable: Path, command: str
    ) -> None:
        """Test the test, benchmark, and debug commands all load the module of the option."""
        result = invoke_cli(
            command, "sorting", str(python_sort_executable), "--problem-module", "no_such_module"
        )

        assert result.exit_code == 2
        assert "Could not load problem module 'no_such_module'" in result.stderr


class TestConfiguredProblemModules:
    @pytest.mark.usefixtures("wide_terminal")
    def test_python_paths_and_problem_modules_make_the_problem_available(
        self,
        configure: Configure,
        tmp_path: Path,
        forget_modules: ForgetModules,
        python_sort_executable: Path,
    ) -> None:
        """Test a configuration can add Python paths and modules that register problems."""
        forget_modules("discovery_configured_module")
        (tmp_path / "libs").mkdir()
        (tmp_path / "libs" / "discovery_configured_module.py").write_text(
            MODULE_TEXT.format(problem_name="configured-variant")
        )
        configure(
            textwrap.dedent(
                f"""\
                python_paths = ["libs"]
                problem_modules = ["discovery_configured_module"]

                [[implementations]]
                name = "sorter"
                problem = "configured-variant"
                command = {json.dumps([sys.executable, str(python_sort_executable)])}
                """
            )
        )

        listing = invoke_cli("list")
        result = invoke_cli("test", "configured-variant", "--fixture", "single")

        assert listing.exit_code == 0, listing.stderr
        assert "configuration: discovery_configured_module" in listing.stdout
        assert result.exit_code == 0, result.stderr
        assert "sorter: 1/1 cases passed" in result.stdout

    def test_an_unknown_problem_name_in_the_configuration_is_a_configuration_error(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test a configured implementation of an unknown problem is a configuration error."""
        configure(
            "[[implementations]]\n"
            'name = "sorter"\n'
            'problem = "graphs"\n'
            f"command = {json.dumps([str(python_sort_executable)])}\n"
        )

        result = invoke_cli("test", "sorting", str(python_sort_executable))

        assert result.exit_code == 2
        assert "Configuration error:" in result.stderr
        assert "implementation 'sorter' names unknown problem 'graphs'" in result.stderr
        assert "problem_modules" in result.stderr

    def test_the_problem_may_come_from_the_command_line_option_instead(
        self,
        configure: Configure,
        problem_module: WriteProblemModule,
        python_sort_executable: Path,
    ) -> None:
        """Test a configured problem is found when its module is given with the option."""
        problem_module("discovery_late_module", "late-variant")
        configure(
            "[[implementations]]\n"
            'name = "sorter"\n'
            'problem = "late-variant"\n'
            f"command = {json.dumps([sys.executable, str(python_sort_executable)])}\n"
        )

        result = invoke_cli("list", "--problem-module", "discovery_late_module")

        assert result.exit_code == 0, result.stderr

    def test_a_missing_configured_module_is_a_configuration_error(
        self, configure: Configure
    ) -> None:
        """Test a configured problem module that cannot be imported is a configuration error."""
        configure('problem_modules = ["no_such_configured_module"]\n')

        result = invoke_cli("list")

        assert result.exit_code == 2
        assert "Configuration error:" in result.stderr
        assert "no_such_configured_module" in result.stderr


class TestEntryPoints:
    def test_a_broken_entry_point_is_a_warning_and_the_command_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test an entry point that cannot be loaded is a warning and does not stop list."""
        broken = importlib.metadata.EntryPoint(
            name="broken-plugin",
            value="no_such_entry_point_module",
            group="algorithm_playground.problems",
        )
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [broken])

        result = invoke_cli("list")

        assert result.exit_code == 0, result.stderr
        assert "Warning: Could not load problem entry point 'broken-plugin'" in result.stderr
        assert "sorting" in result.stdout

    @pytest.mark.usefixtures("wide_terminal")
    def test_a_working_entry_point_adds_a_problem_labeled_with_its_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
        problem_module: WriteProblemModule,
    ) -> None:
        """Test an entry point registers its problem and list shows the name of the entry point."""
        problem_module("discovery_entry_module", "entry-variant")
        working = importlib.metadata.EntryPoint(
            name="my-plugin", value="discovery_entry_module", group="algorithm_playground.problems"
        )
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [working])

        result = invoke_cli("list")

        assert result.exit_code == 0, result.stderr
        assert "entry-variant" in result.stdout
        assert "entry point: my-plugin" in result.stdout
        assert result.stderr == ""


class TestDistinctCountExample:
    """The third-party example in ``examples/distinct_count`` works end to end."""

    @pytest.fixture
    def example_directory(
        self,
        repository_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        forget_modules: ForgetModules,
    ) -> Path:
        """The directory of the example, which is made the current directory."""
        forget_modules("distinct_count_problem")
        directory = repository_root / "examples" / "distinct_count"
        monkeypatch.chdir(directory)
        return directory

    @pytest.mark.usefixtures("example_directory")
    def test_the_configuration_loads_the_problem_and_the_tests_pass(self) -> None:
        """Test the example configuration loads its problem and its implementation passes."""
        result = invoke_cli("test", "distinct-count", "--random-cases", "2")

        assert result.exit_code == 0, result.stderr
        assert "python-set: 7/7 cases passed (5/5 fixtures, 2/2 generated)" in result.stdout

    @pytest.mark.usefixtures("example_directory")
    def test_a_wrong_implementation_is_shrunk_to_the_smallest_input(self, tmp_path: Path) -> None:
        """Test a wrong implementation of the example problem fails with a shrunk input."""
        wrong = tmp_path / "counts_length.py"
        wrong.write_text(
            "import struct, sys\n"
            "raw = open(sys.argv[1], 'rb').read()\n"
            "open(sys.argv[2], 'wb').write(struct.pack('<Q', struct.unpack_from('<Q', raw)[0]))\n"
        )

        result = invoke_cli(
            "test",
            "distinct-count",
            "--command",
            f"{sys.executable} {wrong}",
            "--case",
            "generated:few_values:size=12:seed=3",
        )

        assert result.exit_code == 1
        assert "shrunk input: [0, 0]" in result.stdout


class TestListOneProblem:
    @pytest.fixture
    def sorting_listing(self, wide_terminal: None) -> Result:
        """The result of listing the details of the sorting problem."""
        return invoke_cli("list", "sorting")

    def test_it_shows_the_description_and_where_the_problem_is_from(
        self, sorting_listing: Result
    ) -> None:
        """Test the listing of a problem shows its description and that it is built in."""
        output = sorting_listing.stdout

        assert sorting_listing.exit_code == 0, sorting_listing.stderr
        assert "sorting: Sort an array of 32-bit signed integers in ascending order." in output
        assert "(built-in)" in output

    def test_it_shows_the_fixtures(self, sorting_listing: Result) -> None:
        """Test the listing of a problem shows its fixtures with their descriptions."""
        output = sorting_listing.stdout

        assert "Fixtures (" in output
        assert "reverse_sorted" in output and "descending input" in output
        assert "length_16" in output and "next to a power of two" in output

    def test_it_shows_the_distributions(self, sorting_listing: Result) -> None:
        """Test the listing of a problem shows its distributions with their descriptions."""
        output = sorting_listing.stdout

        assert "Distributions (10)" in output
        assert "median_of_three_killer" in output and "Musser's sequence" in output

    def test_it_shows_the_trace_support(self, sorting_listing: Result) -> None:
        """Test the listing of a problem says it has a trace format and what it counts."""
        output = sorting_listing.stdout

        assert "Trace format: yes" in output
        assert "compares, swaps, writes" in output

    def test_the_default_and_the_debug_distribution_are_marked(
        self, sorting_listing: Result
    ) -> None:
        """Test the listing marks the default distribution and the one used by debug."""
        roles = {
            row[0]: row[2] for row in parse_table_rows(sorting_listing.stdout) if len(row) == 3
        }

        assert roles["uniform"] == "default"
        assert roles["small_range"] == "debug"
        assert roles["sorted"] == ""

    def test_the_minimum_size_is_mentioned_when_it_is_not_zero(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test the listing of a problem mentions the smallest size when it is above zero."""
        forget_modules("details_minimum_problem")
        module = tmp_path / "details_minimum_problem.py"
        module.write_text(
            MODULE_TEXT.format(problem_name="needs-two")
            + "    minimum_size = 2\n    operation_names = ()\n"
        )

        result = invoke_cli("list", "needs-two", "--problem-module", str(module))

        assert result.exit_code == 0, result.stderr
        assert "Sizes start at 2." in result.stdout

    @pytest.mark.usefixtures("wide_terminal")
    def test_a_problem_without_a_trace_format_says_so(
        self,
        repository_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        forget_modules: ForgetModules,
    ) -> None:
        """Test the listing of a problem without a trace format says there is none."""
        forget_modules("distinct_count_problem")
        monkeypatch.chdir(repository_root / "examples" / "distinct_count")

        result = invoke_cli("list", "distinct-count", "--problem-module", "distinct_count_problem")

        assert result.exit_code == 0, result.stderr
        assert "Trace format: none" in result.stdout
        assert "all_distinct" in result.stdout and "few_values" in result.stdout

    def test_a_trace_format_without_declared_operations_says_what_happens(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test the listing says what is shown when the problem does not name its operations."""
        forget_modules("details_traced_problem")
        module = tmp_path / "details_traced_problem.py"
        module.write_text(MODULE_TEXT.format(problem_name="traced") + "    operation_names = ()\n")

        result = invoke_cli("list", "traced", "--problem-module", str(module))

        assert "Trace format: yes. The problem does not say which operations" in result.stdout

    def test_names_that_look_like_markup_are_shown_as_they_are(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test descriptions and fixture names that look like markup are printed as typed."""
        forget_modules("details_markup_problem")
        module = tmp_path / "details_markup_problem.py"
        module.write_text(
            "from algorithm_playground.authoring import Fixture, register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "@register_problem\n"
            "class Markup(SortingProblem):\n"
            "    name = 'markup'\n"
            "    description = '[bold]loud[/bold] [red'\n"
            "    def fixtures(self):\n"
            "        yield Fixture('[red]boom', [1], '[/oops] text')\n"
        )

        result = invoke_cli("list", "markup", "--problem-module", str(module))

        assert result.exit_code == 0, result.stderr
        assert "[red]boom" in result.stdout and "[/oops] text" in result.stdout
        assert "[bold]loud[/bold] [red" in result.stdout

    def test_an_unknown_problem_is_a_usage_error_listing_the_known_ones(self) -> None:
        """Test listing a problem that is not registered is a usage error naming the known ones."""
        result = invoke_cli("list", "nope")

        assert result.exit_code == 2
        assert "Unknown problem 'nope'. Registered problems: " in result.stderr

    def test_the_configured_implementations_shown_are_those_of_the_problem(
        self, configure: Configure
    ) -> None:
        """Test the listing of a problem shows the implementations configured for it."""
        configure(
            "[[implementations]]\nname = 'one'\nproblem = 'sorting'\ncommand = './one'\n",
            "[[implementations]]\nname = 'two'\nproblem = 'sorting'\ncommand = './two'\n",
        )

        result = invoke_cli("list", "sorting")

        assert result.exit_code == 0, result.stderr
        assert "Configured implementations" in result.stdout
        assert "one" in result.stdout and "two" in result.stdout

    def test_a_hook_that_raises_ends_in_a_message_not_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a fixtures hook that raises is reported by name and ends list with exit code 1."""

        def explode(self: SortingProblem) -> list[object]:
            raise RuntimeError("no fixtures today")

        monkeypatch.setattr(SortingProblem, "fixtures", explode)

        result = invoke_cli("list", "sorting")

        assert_exits_with(result, 1)
        assert "The problem's fixtures hook raised RuntimeError: no fixtures today." in (
            result.stderr
        )


class TestProblemLoadingGuidance:
    @pytest.mark.usefixtures("wide_terminal")
    def test_a_python_file_is_loaded_by_its_path(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test a problem module given as a file path is loaded and its directory is importable."""
        forget_modules("guidance_file_problem")
        path = tmp_path / "guidance_file_problem.py"
        path.write_text(MODULE_TEXT.format(problem_name="file-variant"))

        result = invoke_cli("list", "--problem-module", str(path))

        assert result.exit_code == 0, result.stderr
        assert "file-variant" in result.stdout
        assert "option: " in result.stdout
        assert str(tmp_path) in sys.path

    @pytest.mark.usefixtures("wide_terminal")
    def test_a_module_in_the_current_directory_is_found_by_name(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        forget_modules: ForgetModules,
    ) -> None:
        """Test a problem module is found by name in the current directory."""
        forget_modules("guidance_cwd_problem")
        (tmp_path / "guidance_cwd_problem.py").write_text(
            MODULE_TEXT.format(problem_name="cwd-variant")
        )
        monkeypatch.chdir(tmp_path)

        result = invoke_cli("list", "--problem-module", "guidance_cwd_problem")

        assert result.exit_code == 0, result.stderr
        assert "cwd-variant" in result.stdout
        assert str(tmp_path) in sys.path

    def test_a_module_that_registers_nothing_gets_a_warning(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test a problem module that registers no problem is a warning that hints at the cause."""
        forget_modules("guidance_forgetful")
        path = tmp_path / "guidance_forgetful.py"
        path.write_text(
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "class Forgetful(SortingProblem):\n"
            "    name = 'forgetful'\n"
        )

        result = invoke_cli("list", "--problem-module", str(path))

        assert result.exit_code == 0, result.stderr
        assert "Warning: Problem module" in result.stderr
        assert "registered no problems. Did you forget @register_problem" in result.stderr
        assert "forgetful" not in result.stdout

    def test_an_incomplete_problem_is_refused_with_the_missing_methods(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test a problem that lacks required methods is refused and the methods are listed."""
        forget_modules("guidance_incomplete")
        path = tmp_path / "guidance_incomplete.py"
        path.write_text(
            "from algorithm_playground.authoring import Problem, register_problem\n\n\n"
            "@register_problem\n"
            "class Incomplete(Problem):\n"
            "    name = 'incomplete'\n"
            "    description = 'forgot most things'\n"
        )

        result = invoke_cli("list", "--problem-module", str(path))

        assert result.exit_code == 2
        assert "Incomplete cannot be registered because it does not implement: " in result.stderr
        assert "deserialize_output, fixtures, generators, serialize_input, verify" in result.stderr
        assert result.stdout == ""

    def test_a_missing_module_error_says_what_to_try(self) -> None:
        """Test the error for a module that is not found suggests giving the path of the file."""
        result = invoke_cli("list", "--problem-module", "guidance_no_such_module")

        assert result.exit_code == 2
        assert "--problem-module path/to/guidance_no_such_module.py" in result.stderr

    def test_a_missing_file_error_says_where_paths_start(self) -> None:
        """Test the error for a file that is not found says paths start at the current directory."""
        result = invoke_cli("list", "--problem-module", "missing/guidance.py")

        assert result.exit_code == 2
        assert "file not found" in result.stderr
        assert "relative to the current directory" in result.stderr

    @pytest.mark.usefixtures("wide_terminal")
    def test_a_hook_can_import_a_neighbor_of_the_file_while_the_command_runs(
        self, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        """Test a hook can import a module that sits next to the file of the problem."""
        forget_modules("guidance_lazy_problem", "guidance_lazy_neighbor")
        (tmp_path / "guidance_lazy_neighbor.py").write_text("DESCRIPTION = 'from the neighbor'\n")
        path = tmp_path / "guidance_lazy_problem.py"
        path.write_text(
            "from algorithm_playground.core import Fixture, register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "@register_problem\n"
            "class Lazy(SortingProblem):\n"
            "    name = 'lazy-variant'\n"
            "    description = 'imports a neighbor from a hook'\n\n"
            "    def fixtures(self):\n"
            "        from guidance_lazy_neighbor import DESCRIPTION\n"
            "        return [Fixture('neighbor', [1], DESCRIPTION)]\n"
        )

        result = invoke_cli("list", "lazy-variant", "--problem-module", str(path))

        assert result.exit_code == 0, result.stderr
        assert "from the neighbor" in result.stdout


class TestOptionHelp:
    @pytest.mark.usefixtures("wide_terminal")
    @pytest.mark.parametrize("command", ["list", "test", "benchmark", "debug"])
    def test_the_configuration_option_says_the_parents_are_searched(self, command: str) -> None:
        """Test the help of the configuration option says parent directories are searched."""
        text = read_help_text(command)

        assert "nearest parent directory that has one" in text
        assert "up to a directory that contains .git" in text

    @pytest.mark.usefixtures("wide_terminal")
    @pytest.mark.parametrize("command", ["list", "test", "benchmark", "debug"])
    def test_the_problem_module_option_accepts_a_module_name_or_a_file_path(
        self, command: str
    ) -> None:
        """Test the help of the problem module option says it takes a module name or a path."""
        text = read_help_text(command)

        assert "a module name" in text
        assert "looked up in the current directory too" in text
        assert "the path of a .py file" in text


class TestConfigurationInMessages:
    @pytest.fixture
    def repository_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """An empty repository root that is made the current directory."""
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        return tmp_path

    @pytest.mark.parametrize(
        "arguments", [["list"], ["list", "sorting"]], ids=["all problems", "one problem"]
    )
    def test_a_configuration_path_with_markup_in_it_is_shown_as_typed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
    ) -> None:
        """Test a configuration path that looks like markup is printed as typed."""
        directory = tmp_path / "[red]solutions"
        directory.mkdir()
        (directory / "algorithm-playground.toml").write_text(
            '[[implementations]]\nname = "a"\nproblem = "sorting"\ncommand = "python3 a.py"\n'
        )
        monkeypatch.chdir(tmp_path)
        shown = "[red]solutions/algorithm-playground.toml"

        result = invoke_cli(*arguments, "--configuration", shown)

        assert result.exit_code == 0, result.stderr
        assert "Configured implementations" in result.stdout
        assert "([red]solutions/" in result.stdout

    @pytest.mark.usefixtures("repository_directory")
    def test_the_missing_configuration_message_says_parent_directories_are_searched(self) -> None:
        """Test the message for a missing configuration says parent directories are searched."""
        result = invoke_cli("test", "sorting")

        assert result.exit_code == 2
        assert "in the current directory or a parent directory" in result.stderr

    @pytest.mark.usefixtures("repository_directory")
    def test_the_unknown_implementation_message_says_where_the_configuration_is_searched(
        self,
    ) -> None:
        """Test the message for an unknown implementation says how far the search goes."""
        result = invoke_cli("test", "sorting", "no-such-implementation")

        assert result.exit_code == 2
        assert "in the current directory and its parents, up to a directory that" in (
            " ".join(result.stderr.split())
        )


class TestVersionOption:
    def test_it_prints_the_version_and_exits(self) -> None:
        """Test the version option prints the name and version of the program and nothing else."""
        result = invoke_cli("--version")

        assert result.exit_code == 0
        assert result.stdout == f"algorithm-playground {__version__}\n"

    def test_it_is_in_the_help(self) -> None:
        """Test the help of the program lists the version option."""
        assert "--version" in invoke_cli("--help").stdout
