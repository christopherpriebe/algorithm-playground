"""End-to-end CLI tests for problems that live outside this package."""

from __future__ import annotations

import importlib.metadata
import json
import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from support import Configure, Invoke

pytestmark = pytest.mark.integration

ForgetModules = Callable[..., None]

MODULE_TEXT = """\
from algorithm_playground.core import register_problem
from algorithm_playground.problems.sorting import SortingProblem


@register_problem
class Variant(SortingProblem):
    name = "{problem_name}"
    description = "A sorting variant defined outside the package."
"""


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def problem_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forget_modules: ForgetModules
) -> Callable[[str, str], None]:
    """Write an importable module that registers a problem, in a directory on ``sys.path``."""
    directory = tmp_path / "modules"
    directory.mkdir()
    monkeypatch.syspath_prepend(str(directory))

    def write(module_name: str, problem_name: str) -> None:
        forget_modules(module_name)
        (directory / f"{module_name}.py").write_text(MODULE_TEXT.format(problem_name=problem_name))

    return write


class TestProblemModuleOption:
    def test_list_shows_the_problem_and_where_it_came_from(
        self, invoke: Invoke, problem_module: Callable[[str, str], None]
    ) -> None:
        problem_module("discovery_option_module", "option-variant")
        result = invoke("list", "--problem-module", "discovery_option_module")
        assert result.exit_code == 0, result.stderr
        assert "option-variant" in result.stdout
        assert "option: discovery_option_module" in result.stdout
        assert "built-in" in result.stdout

    def test_a_loaded_problem_can_be_tested(
        self,
        invoke: Invoke,
        problem_module: Callable[[str, str], None],
        python_sort_executable: Path,
    ) -> None:
        problem_module("discovery_tested_module", "tested-variant")
        result = invoke(
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
        invoke: Invoke,
        problem_module: Callable[[str, str], None],
        unsorted_output_executable: Path,
    ) -> None:
        problem_module("discovery_reproduce_module", "reproduced-variant")
        result = invoke(
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

    def test_a_module_that_cannot_be_imported_is_a_usage_error(self, invoke: Invoke) -> None:
        result = invoke("list", "--problem-module", "no_such_discovery_module")
        assert result.exit_code == 2
        assert "Could not load problem module 'no_such_discovery_module'" in result.stderr
        assert result.stdout == ""

    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    def test_every_command_accepts_the_option(
        self, invoke: Invoke, python_sort_executable: Path, command: str
    ) -> None:
        result = invoke(
            command, "sorting", str(python_sort_executable), "--problem-module", "no_such_module"
        )
        assert result.exit_code == 2
        assert "Could not load problem module 'no_such_module'" in result.stderr


class TestConfiguredProblemModules:
    def test_python_paths_and_problem_modules_make_the_problem_available(
        self,
        invoke: Invoke,
        configure: Configure,
        tmp_path: Path,
        forget_modules: ForgetModules,
        python_sort_executable: Path,
    ) -> None:
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
        listing = invoke("list")
        assert listing.exit_code == 0, listing.stderr
        assert "configuration: discovery_configured_module" in listing.stdout

        result = invoke("test", "configured-variant", "--fixture", "single")
        assert result.exit_code == 0, result.stderr
        assert "sorter: 1/1 cases passed" in result.stdout

    def test_an_unknown_problem_name_in_the_configuration_is_a_configuration_error(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(
            "[[implementations]]\n"
            'name = "sorter"\n'
            'problem = "graphs"\n'
            f"command = {json.dumps([str(python_sort_executable)])}\n"
        )
        result = invoke("test", "sorting", str(python_sort_executable))
        assert result.exit_code == 2
        assert "Configuration error:" in result.stderr
        assert "implementation 'sorter' names unknown problem 'graphs'" in result.stderr
        assert "problem_modules" in result.stderr

    def test_the_problem_may_come_from_the_command_line_option_instead(
        self,
        invoke: Invoke,
        configure: Configure,
        problem_module: Callable[[str, str], None],
        python_sort_executable: Path,
    ) -> None:
        problem_module("discovery_late_module", "late-variant")
        configure(
            "[[implementations]]\n"
            'name = "sorter"\n'
            'problem = "late-variant"\n'
            f"command = {json.dumps([sys.executable, str(python_sort_executable)])}\n"
        )
        result = invoke("list", "--problem-module", "discovery_late_module")
        assert result.exit_code == 0, result.stderr

    def test_a_missing_configured_module_is_a_configuration_error(
        self, invoke: Invoke, configure: Configure
    ) -> None:
        configure('problem_modules = ["no_such_configured_module"]\n')
        result = invoke("list")
        assert result.exit_code == 2
        assert "Configuration error:" in result.stderr
        assert "no_such_configured_module" in result.stderr


class TestEntryPoints:
    def test_a_broken_entry_point_is_a_warning_and_the_command_still_works(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = importlib.metadata.EntryPoint(
            name="broken-plugin",
            value="no_such_entry_point_module",
            group="algorithm_playground.problems",
        )
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [broken])
        result = invoke("list")
        assert result.exit_code == 0, result.stderr
        assert "Warning: Could not load problem entry point 'broken-plugin'" in result.stderr
        assert "sorting" in result.stdout

    def test_a_working_entry_point_adds_a_problem_labeled_with_its_name(
        self,
        invoke: Invoke,
        monkeypatch: pytest.MonkeyPatch,
        problem_module: Callable[[str, str], None],
    ) -> None:
        problem_module("discovery_entry_module", "entry-variant")
        working = importlib.metadata.EntryPoint(
            name="my-plugin", value="discovery_entry_module", group="algorithm_playground.problems"
        )
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [working])
        result = invoke("list")
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
        forget_modules("distinct_count_problem")
        directory = repository_root / "examples" / "distinct_count"
        monkeypatch.chdir(directory)
        return directory

    def test_the_configuration_loads_the_problem_and_the_tests_pass(
        self, invoke: Invoke, example_directory: Path
    ) -> None:
        result = invoke("test", "distinct-count", "--random-cases", "2")
        assert result.exit_code == 0, result.stderr
        assert "python-set: 7/7 cases passed (5/5 fixtures, 2/2 generated)" in result.stdout

    def test_a_wrong_implementation_is_shrunk_to_the_smallest_input(
        self, invoke: Invoke, example_directory: Path, tmp_path: Path
    ) -> None:
        wrong = tmp_path / "counts_length.py"
        wrong.write_text(
            "import struct, sys\n"
            "raw = open(sys.argv[1], 'rb').read()\n"
            "open(sys.argv[2], 'wb').write(struct.pack('<Q', struct.unpack_from('<Q', raw)[0]))\n"
        )
        result = invoke(
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
    def test_it_shows_the_fixtures_the_distributions_and_the_trace_support(
        self, invoke: Invoke
    ) -> None:
        result = invoke("list", "sorting")
        assert result.exit_code == 0, result.stderr
        output = result.stdout
        assert "sorting: Sort an array of 32-bit signed integers in ascending order." in output
        assert "(built-in)" in output
        assert "Fixtures (" in output
        assert "reverse_sorted" in output and "descending input" in output
        assert "length_16" in output and "next to a power of two" in output
        assert "Distributions (10)" in output
        assert "median_of_three_killer" in output and "Musser's sequence" in output
        assert "Trace format: yes" in output
        assert "compares, swaps, writes" in output

    def test_the_default_and_the_debug_distribution_are_marked(
        self, invoke: Invoke, table_rows: Callable[[str], list[list[str]]]
    ) -> None:
        result = invoke("list", "sorting")
        roles = {row[0]: row[2] for row in table_rows(result.stdout) if len(row) == 3}
        assert roles["uniform"] == "default"
        assert roles["small_range"] == "debug"
        assert roles["sorted"] == ""

    def test_the_minimum_size_is_mentioned_when_it_is_not_zero(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        forget_modules("details_minimum_problem")
        module = tmp_path / "details_minimum_problem.py"
        module.write_text(
            MODULE_TEXT.format(problem_name="needs-two")
            + "    minimum_size = 2\n    operation_names = ()\n"
        )
        result = invoke("list", "needs-two", "--problem-module", str(module))
        assert result.exit_code == 0, result.stderr
        assert "Sizes start at 2." in result.stdout

    def test_a_problem_without_a_trace_format_says_so(
        self, invoke: Invoke, repository_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = repository_root / "examples" / "distinct_count"
        monkeypatch.chdir(directory)
        result = invoke("list", "distinct-count", "--problem-module", "distinct_count_problem")
        assert result.exit_code == 0, result.stderr
        assert "Trace format: none" in result.stdout
        assert "all_distinct" in result.stdout and "few_values" in result.stdout
        sys.modules.pop("distinct_count_problem", None)

    def test_a_trace_format_without_declared_operations_says_what_happens(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        forget_modules("details_traced_problem")
        module = tmp_path / "details_traced_problem.py"
        module.write_text(MODULE_TEXT.format(problem_name="traced") + "    operation_names = ()\n")
        result = invoke("list", "traced", "--problem-module", str(module))
        assert "Trace format: yes. The problem does not say which operations" in result.stdout

    def test_names_that_look_like_markup_are_shown_as_they_are(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
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
        result = invoke("list", "markup", "--problem-module", str(module))
        assert result.exit_code == 0, result.stderr
        assert "[red]boom" in result.stdout and "[/oops] text" in result.stdout
        assert "[bold]loud[/bold] [red" in result.stdout

    def test_an_unknown_problem_is_a_usage_error_listing_the_known_ones(
        self, invoke: Invoke
    ) -> None:
        result = invoke("list", "nope")
        assert result.exit_code == 2
        assert "Unknown problem 'nope'. Registered problems: " in result.stderr

    def test_the_configured_implementations_shown_are_those_of_the_problem(
        self, invoke: Invoke, configure: Configure
    ) -> None:
        configure(
            "[[implementations]]\nname = 'one'\nproblem = 'sorting'\ncommand = './one'\n",
            "[[implementations]]\nname = 'two'\nproblem = 'sorting'\ncommand = './two'\n",
        )
        result = invoke("list", "sorting")
        assert result.exit_code == 0, result.stderr
        assert "Configured implementations" in result.stdout
        assert "one" in result.stdout and "two" in result.stdout

    def test_a_hook_that_raises_ends_in_a_message_not_a_traceback(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from support import assert_exits_with

        from algorithm_playground.problems.sorting import SortingProblem

        def explode(self: SortingProblem) -> list[object]:
            raise RuntimeError("no fixtures today")

        monkeypatch.setattr(SortingProblem, "fixtures", explode)
        result = invoke("list", "sorting")
        assert_exits_with(result, 1)
        assert "The problem's fixtures hook raised RuntimeError: no fixtures today." in (
            result.stderr
        )


class TestProblemLoadingGuidance:
    def test_a_python_file_is_loaded_by_its_path(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        forget_modules("guidance_file_problem")
        path = tmp_path / "guidance_file_problem.py"
        path.write_text(MODULE_TEXT.format(problem_name="file-variant"))
        result = invoke("list", "--problem-module", str(path))
        assert result.exit_code == 0, result.stderr
        assert "file-variant" in result.stdout
        assert "option: " in result.stdout
        assert str(tmp_path) in sys.path

    def test_a_module_in_the_current_directory_is_found_by_name(
        self,
        invoke: Invoke,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        forget_modules: ForgetModules,
    ) -> None:
        forget_modules("guidance_cwd_problem")
        (tmp_path / "guidance_cwd_problem.py").write_text(
            MODULE_TEXT.format(problem_name="cwd-variant")
        )
        monkeypatch.chdir(tmp_path)
        result = invoke("list", "--problem-module", "guidance_cwd_problem")
        assert result.exit_code == 0, result.stderr
        assert "cwd-variant" in result.stdout
        assert str(tmp_path) in sys.path

    def test_a_module_that_registers_nothing_gets_a_warning(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        forget_modules("guidance_forgetful")
        path = tmp_path / "guidance_forgetful.py"
        path.write_text(
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "class Forgetful(SortingProblem):\n"
            "    name = 'forgetful'\n"
        )
        result = invoke("list", "--problem-module", str(path))
        assert result.exit_code == 0, result.stderr
        assert "Warning: Problem module" in result.stderr
        assert "registered no problems. Did you forget @register_problem" in result.stderr
        assert "forgetful" not in result.stdout

    def test_an_incomplete_problem_is_refused_with_the_missing_methods(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
        forget_modules("guidance_incomplete")
        path = tmp_path / "guidance_incomplete.py"
        path.write_text(
            "from algorithm_playground.authoring import Problem, register_problem\n\n\n"
            "@register_problem\n"
            "class Incomplete(Problem):\n"
            "    name = 'incomplete'\n"
            "    description = 'forgot most things'\n"
        )
        result = invoke("list", "--problem-module", str(path))
        assert result.exit_code == 2
        assert "Incomplete cannot be registered because it does not implement: " in result.stderr
        assert "deserialize_output, fixtures, generators, serialize_input, verify" in result.stderr
        assert result.stdout == ""

    def test_a_missing_module_error_says_what_to_try(self, invoke: Invoke) -> None:
        result = invoke("list", "--problem-module", "guidance_no_such_module")
        assert result.exit_code == 2
        assert "--problem-module path/to/guidance_no_such_module.py" in result.stderr

    def test_a_missing_file_error_says_where_paths_start(self, invoke: Invoke) -> None:
        result = invoke("list", "--problem-module", "missing/guidance.py")
        assert result.exit_code == 2
        assert "file not found" in result.stderr
        assert "relative to the current directory" in result.stderr

    def test_a_hook_can_import_a_neighbor_of_the_file_while_the_command_runs(
        self, invoke: Invoke, tmp_path: Path, forget_modules: ForgetModules
    ) -> None:
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
        result = invoke("list", "lazy-variant", "--problem-module", str(path))
        assert result.exit_code == 0, result.stderr
        assert "from the neighbor" in result.stdout


class TestOptionHelp:
    @staticmethod
    def help_text(invoke: Invoke, command: str) -> str:
        output = invoke(command, "--help").stdout
        return " ".join(re.sub(r"[│╭╮╰╯─]", " ", output).split())

    @pytest.mark.parametrize("command", ["list", "test", "benchmark", "debug"])
    def test_the_configuration_option_says_the_parents_are_searched(
        self, invoke: Invoke, command: str
    ) -> None:
        text = self.help_text(invoke, command)
        assert "nearest parent directory that has one" in text
        assert "up to a directory that contains .git" in text

    @pytest.mark.parametrize("command", ["list", "test", "benchmark", "debug"])
    def test_the_problem_module_option_accepts_a_module_name_or_a_file_path(
        self, invoke: Invoke, command: str
    ) -> None:
        text = self.help_text(invoke, command)
        assert "a module name" in text
        assert "looked up in the current directory too" in text
        assert "the path of a .py file" in text


class TestConfigurationInMessages:
    def test_a_configuration_path_with_markup_in_it_is_shown_as_typed(
        self, invoke: Invoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "[red]solutions"
        directory.mkdir()
        (directory / "algorithm-playground.toml").write_text(
            '[[implementations]]\nname = "a"\nproblem = "sorting"\ncommand = "python3 a.py"\n'
        )
        monkeypatch.chdir(tmp_path)
        shown = "[red]solutions/algorithm-playground.toml"
        for arguments in (["list"], ["list", "sorting"]):
            result = invoke(*arguments, "--configuration", shown)
            assert result.exit_code == 0, result.stderr
            assert "Configured implementations" in result.stdout
            assert "([red]solutions/" in result.stdout

    def test_the_messages_say_the_default_file_is_searched_in_the_parent_directories(
        self, invoke: Invoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        missing = invoke("test", "sorting")
        assert missing.exit_code == 2
        assert "in the current directory or a parent directory" in missing.stderr
        unknown = invoke("test", "sorting", "no-such-implementation")
        assert unknown.exit_code == 2
        assert "in the current directory and its parents, up to a directory that" in (
            " ".join(unknown.stderr.split())
        )


class TestVersionOption:
    def test_it_prints_the_version_and_exits(self, invoke: Invoke) -> None:
        from algorithm_playground import __version__

        result = invoke("--version")
        assert result.exit_code == 0
        assert result.stdout == f"algorithm-playground {__version__}\n"

    def test_it_is_in_the_help(self, invoke: Invoke) -> None:
        assert "--version" in invoke("--help").stdout
