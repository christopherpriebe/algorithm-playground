"""Tests for the central problem registry, the @register_problem decorator, and problem loading."""

from __future__ import annotations

import importlib.metadata
import sys
import textwrap
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from algorithm_playground.core.cases import Fixture, InputGenerator
from algorithm_playground.core.problem import Problem, VerificationResult
from algorithm_playground.core.registry import (
    ENTRY_POINT_GROUP,
    ProblemLoadError,
    ProblemRegistrationError,
    ProblemSource,
    ProblemSourceKind,
    UnknownProblemError,
    get_problem,
    list_problems,
    load_entry_point_problems,
    load_problem_modules,
    problem_descriptions,
    problem_sources,
    register_problem,
)


class _StubProblem(Problem[list[int], list[int], None]):
    name = "stub-for-tests"
    description = "Stub problem used by unit tests."

    def serialize_input(self, data: list[int], path: Path) -> None:
        path.write_bytes(b"")

    def deserialize_output(self, path: Path) -> list[int]:
        return []

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        return iter([])

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return ()

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return VerificationResult(True)


@pytest.fixture
def write_problem_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[str, str], str]]:
    """Write an importable module that registers a sorting variant called ``problem_name``."""
    monkeypatch.syspath_prepend(str(tmp_path))
    created: list[str] = []

    def write(module_name: str, problem_name: str) -> str:
        (tmp_path / f"{module_name}.py").write_text(
            textwrap.dedent(
                f"""\
                from algorithm_playground.core.registry import register_problem
                from algorithm_playground.problems.sorting import SortingProblem


                @register_problem
                class Variant(SortingProblem):
                    name = "{problem_name}"
                    description = "Variant defined in {module_name}."
                """
            )
        )
        created.append(module_name)
        return module_name

    yield write
    for module_name in created:
        sys.modules.pop(module_name, None)


def test_register_problem_adds_to_registry() -> None:
    register_problem(_StubProblem)
    assert "stub-for-tests" in list_problems()
    assert type(get_problem("stub-for-tests")) is _StubProblem


def test_register_problem_returns_class_unchanged() -> None:
    returned = register_problem(_StubProblem)
    assert returned is _StubProblem


def test_register_problem_rejects_missing_name() -> None:
    class Anonymous(_StubProblem):
        name = ""

    with pytest.raises(ProblemRegistrationError):
        register_problem(Anonymous)


def test_register_problem_rejects_an_incomplete_subclass_listing_what_is_missing() -> None:
    class Incomplete(Problem[list[int], list[int], None]):
        name = "incomplete"
        description = "Forgot most of the interface."

        def fixtures(self) -> Iterator[Fixture[list[int]]]:
            return iter([])

    with pytest.raises(ProblemRegistrationError) as raised:
        register_problem(Incomplete)
    message = str(raised.value)
    assert "Incomplete cannot be registered" in message
    assert "deserialize_output, generators, serialize_input, verify" in message
    assert "fixtures" not in message.split("does not implement:")[1].split(".")[0]
    assert "incomplete" not in list_problems()


def test_register_problem_rejects_duplicate_name() -> None:
    register_problem(_StubProblem)

    class Conflicting(_StubProblem):
        name = "stub-for-tests"

    with pytest.raises(ProblemRegistrationError):
        register_problem(Conflicting)


def test_get_problem_instantiates_registered_class() -> None:
    register_problem(_StubProblem)
    instance = get_problem("stub-for-tests")
    assert isinstance(instance, _StubProblem)


def test_get_problem_raises_for_unknown_name() -> None:
    with pytest.raises(UnknownProblemError) as raised:
        get_problem("not-a-problem")
    assert str(raised.value).startswith("Unknown problem 'not-a-problem'. Registered problems: ")
    assert isinstance(raised.value, LookupError)


def test_list_problems_returns_sorted_names() -> None:
    register_problem(_StubProblem)
    names = list_problems()
    assert names == sorted(names)
    assert "stub-for-tests" in names


def test_re_registering_same_class_is_idempotent() -> None:
    register_problem(_StubProblem)
    register_problem(_StubProblem)  # must not raise


def test_problem_descriptions_maps_sorted_names_to_descriptions() -> None:
    register_problem(_StubProblem)
    descriptions = problem_descriptions()
    assert list(descriptions) == sorted(descriptions)
    assert descriptions["stub-for-tests"] == "Stub problem used by unit tests."


class TestProblemSources:
    def test_built_in_problems_are_labeled_built_in(self) -> None:
        assert problem_sources()["sorting"] == ProblemSource(ProblemSourceKind.BUILT_IN)

    def test_a_problem_registered_in_code_is_labeled_direct(self) -> None:
        register_problem(_StubProblem)
        assert problem_sources()["stub-for-tests"].kind is ProblemSourceKind.DIRECT

    def test_sources_are_keyed_by_sorted_name(self) -> None:
        register_problem(_StubProblem)
        assert list(problem_sources()) == list_problems()

    @pytest.mark.parametrize(
        ("source", "text"),
        [
            (ProblemSource(ProblemSourceKind.BUILT_IN), "built-in"),
            (ProblemSource(ProblemSourceKind.DIRECT), "registered in code"),
            (ProblemSource(ProblemSourceKind.ENTRY_POINT, "graphs"), "entry point: graphs"),
            (ProblemSource(ProblemSourceKind.CONFIGURATION, "pkg.mod"), "configuration: pkg.mod"),
            (ProblemSource(ProblemSourceKind.OPTION, "pkg.mod"), "option: pkg.mod"),
        ],
    )
    def test_sources_describe_themselves(self, source: ProblemSource, text: str) -> None:
        assert source.describe() == text


class TestLoadProblemModules:
    def test_importing_a_module_registers_its_problems_with_the_given_source(
        self, write_problem_module: Callable[[str, str], str]
    ) -> None:
        module = write_problem_module("registry_test_module_one", "variant-one")
        load_problem_modules([module], ProblemSourceKind.CONFIGURATION)
        assert "variant-one" in list_problems()
        assert problem_sources()["variant-one"] == ProblemSource(
            ProblemSourceKind.CONFIGURATION, module
        )

    def test_a_missing_module_is_a_load_error_naming_it(self) -> None:
        with pytest.raises(
            ProblemLoadError, match=r"'no_such_problem_module'.*ModuleNotFoundError"
        ):
            load_problem_modules(["no_such_problem_module"], ProblemSourceKind.OPTION)

    def test_a_module_that_raises_while_importing_is_a_load_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "registry_test_broken.py").write_text("raise RuntimeError('boom')\n")
        with pytest.raises(ProblemLoadError, match="RuntimeError: boom"):
            load_problem_modules(["registry_test_broken"], ProblemSourceKind.OPTION)

    def test_a_duplicate_problem_name_is_a_load_error(
        self, write_problem_module: Callable[[str, str], str]
    ) -> None:
        module = write_problem_module("registry_test_module_duplicate", "sorting")
        with pytest.raises(ProblemLoadError, match="already registered"):
            load_problem_modules([module], ProblemSourceKind.OPTION)

    def test_a_missing_module_error_says_what_to_try(self) -> None:
        with pytest.raises(ProblemLoadError) as raised:
            load_problem_modules(["no_such_problem_module"], ProblemSourceKind.OPTION)
        message = str(raised.value)
        assert "--problem-module path/to/no_such_problem_module.py" in message
        assert "python_paths" in message

    def test_a_module_that_registers_nothing_is_a_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "registry_test_forgetful.py").write_text("VALUE = 1\n")
        warnings = load_problem_modules(["registry_test_forgetful"], ProblemSourceKind.OPTION)
        assert warnings == (
            "Problem module 'registry_test_forgetful' registered no problems. "
            "Did you forget @register_problem on your Problem subclass?",
        )
        sys.modules.pop("registry_test_forgetful", None)

    def test_a_module_that_was_loaded_before_is_not_warned_about_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "registry_test_loaded_twice.py").write_text("VALUE = 1\n")
        first = load_problem_modules(["registry_test_loaded_twice"], ProblemSourceKind.OPTION)
        second = load_problem_modules(["registry_test_loaded_twice"], ProblemSourceKind.OPTION)
        assert len(first) == 1 and second == ()
        sys.modules.pop("registry_test_loaded_twice", None)

    def test_a_module_that_registers_something_gives_no_warning(
        self, write_problem_module: Callable[[str, str], str]
    ) -> None:
        module = write_problem_module("registry_test_module_fine", "fine-variant")
        assert load_problem_modules([module], ProblemSourceKind.OPTION) == ()

    def test_a_module_that_fails_after_registering_leaves_nothing_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "registry_test_half_loaded.py").write_text(
            "from algorithm_playground.core.registry import register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "@register_problem\n"
            "class Half(SortingProblem):\n"
            "    name = 'half-loaded'\n\n\n"
            "raise RuntimeError('boom after registering')\n"
        )
        with pytest.raises(ProblemLoadError, match="boom after registering"):
            load_problem_modules(["registry_test_half_loaded"], ProblemSourceKind.OPTION)
        assert "half-loaded" not in list_problems()
        assert "half-loaded" not in problem_sources()


class TestLoadProblemFiles:
    def write_file(self, directory: Path, name: str, problem_name: str) -> Path:
        path = directory / name
        path.write_text(
            "from algorithm_playground.core.registry import register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "@register_problem\n"
            "class FromFile(SortingProblem):\n"
            f"    name = {problem_name!r}\n"
        )
        return path

    def test_a_python_file_is_loaded_by_its_path(self, tmp_path: Path) -> None:
        path = self.write_file(tmp_path, "registry_test_file_problem.py", "file-variant")
        load_problem_modules([str(path)], ProblemSourceKind.OPTION)
        assert problem_sources()["file-variant"] == ProblemSource(
            ProblemSourceKind.OPTION, str(path)
        )
        sys.modules.pop("registry_test_file_problem", None)

    def test_a_relative_path_is_relative_to_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.write_file(tmp_path, "registry_test_relative_problem.py", "relative-variant")
        monkeypatch.chdir(tmp_path)
        load_problem_modules(["registry_test_relative_problem.py"], ProblemSourceKind.OPTION)
        assert "relative-variant" in list_problems()
        sys.modules.pop("registry_test_relative_problem", None)

    def test_a_module_in_a_search_directory_is_found_by_name(self, tmp_path: Path) -> None:
        self.write_file(tmp_path, "registry_test_searched_problem.py", "searched-variant")
        load_problem_modules(
            ["registry_test_searched_problem"],
            ProblemSourceKind.OPTION,
            search_directories=[tmp_path],
        )
        assert "searched-variant" in list_problems()
        assert str(tmp_path) in sys.path
        sys.modules.pop("registry_test_searched_problem", None)

    def test_a_file_can_import_the_modules_next_to_it(self, tmp_path: Path) -> None:
        (tmp_path / "registry_test_neighbor.py").write_text("NAME = 'neighbor-variant'\n")
        path = tmp_path / "registry_test_with_neighbor.py"
        path.write_text(
            "from algorithm_playground.core.registry import register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n"
            "from registry_test_neighbor import NAME\n\n\n"
            "@register_problem\n"
            "class WithNeighbor(SortingProblem):\n"
            "    name = NAME\n"
        )
        load_problem_modules([str(path)], ProblemSourceKind.OPTION)
        assert "neighbor-variant" in list_problems()
        assert str(tmp_path) in sys.path
        sys.modules.pop("registry_test_with_neighbor", None)
        sys.modules.pop("registry_test_neighbor", None)

    LAZY_PROBLEM = (
        "from algorithm_playground.core.registry import register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
        "@register_problem\n"
        "class Lazy(SortingProblem):\n"
        "    name = 'lazy-variant'\n\n"
        "    def fixtures(self):\n"
        "        import registry_test_lazy_neighbor\n"
        "        return super().fixtures()\n"
    )

    def test_a_hook_can_import_a_neighbor_of_its_file_long_after_the_file_loaded(
        self, tmp_path: Path, forget_modules: Callable[..., None]
    ) -> None:
        forget_modules("registry_test_lazy_neighbor", "registry_test_lazy_problem")
        (tmp_path / "registry_test_lazy_neighbor.py").write_text("")
        path = tmp_path / "registry_test_lazy_problem.py"
        path.write_text(self.LAZY_PROBLEM)
        load_problem_modules([str(path)], ProblemSourceKind.OPTION)
        assert "registry_test_lazy_neighbor" not in sys.modules
        assert list(get_problem("lazy-variant").fixtures())
        assert "registry_test_lazy_neighbor" in sys.modules

    def test_a_hook_can_import_a_neighbor_of_a_module_found_in_a_search_directory(
        self, tmp_path: Path, forget_modules: Callable[..., None]
    ) -> None:
        forget_modules("registry_test_lazy_neighbor", "registry_test_lazy_problem")
        (tmp_path / "registry_test_lazy_neighbor.py").write_text("")
        (tmp_path / "registry_test_lazy_problem.py").write_text(self.LAZY_PROBLEM)
        load_problem_modules(
            ["registry_test_lazy_problem"],
            ProblemSourceKind.OPTION,
            search_directories=[tmp_path],
        )
        assert list(get_problem("lazy-variant").fixtures())

    def test_a_module_that_fails_to_load_leaves_its_directory_off_the_import_path(
        self, tmp_path: Path, forget_modules: Callable[..., None]
    ) -> None:
        forget_modules("registry_test_failing_problem")
        path = tmp_path / "registry_test_failing_problem.py"
        path.write_text("raise RuntimeError('does not load')\n")
        with pytest.raises(ProblemLoadError):
            load_problem_modules([str(path)], ProblemSourceKind.OPTION)
        assert str(tmp_path) not in sys.path
        forget_modules("registry_test_failing_search")
        (tmp_path / "registry_test_failing_search.py").write_text("raise RuntimeError('no')\n")
        with pytest.raises(ProblemLoadError):
            load_problem_modules(
                ["registry_test_failing_search"],
                ProblemSourceKind.OPTION,
                search_directories=[tmp_path],
            )
        assert str(tmp_path) not in sys.path

    def test_a_file_loaded_twice_is_not_run_or_warned_about_again(self, tmp_path: Path) -> None:
        path = self.write_file(tmp_path, "registry_test_twice_problem.py", "twice-variant")
        assert load_problem_modules([str(path)], ProblemSourceKind.OPTION) == ()
        assert load_problem_modules([str(path)], ProblemSourceKind.OPTION) == ()
        sys.modules.pop("registry_test_twice_problem", None)

    def test_a_file_that_does_not_exist_is_a_load_error_that_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(ProblemLoadError) as raised:
            load_problem_modules([str(tmp_path / "missing.py")], ProblemSourceKind.OPTION)
        assert "file not found" in str(raised.value)
        assert "relative to the current directory" in str(raised.value)

    def test_a_file_that_raises_is_a_load_error_and_is_forgotten(self, tmp_path: Path) -> None:
        path = tmp_path / "registry_test_file_broken.py"
        path.write_text("raise RuntimeError('file boom')\n")
        with pytest.raises(ProblemLoadError, match="RuntimeError: file boom"):
            load_problem_modules([str(path)], ProblemSourceKind.OPTION)
        assert "registry_test_file_broken" not in sys.modules

    def test_a_different_module_with_the_same_name_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "json.py"
        path.write_text("VALUE = 1\n")
        with pytest.raises(ProblemLoadError, match="rename the file"):
            load_problem_modules([str(path)], ProblemSourceKind.OPTION)


class TestLoadEntryPointProblems:
    def _entry_point(self, name: str, value: str) -> importlib.metadata.EntryPoint:
        return importlib.metadata.EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)

    def test_a_module_entry_point_is_imported_and_labeled(
        self, write_problem_module: Callable[[str, str], str]
    ) -> None:
        module = write_problem_module("registry_test_entry_module", "entry-variant")
        warnings = load_entry_point_problems([self._entry_point("my-entry", module)])
        assert warnings == ()
        assert problem_sources()["entry-variant"] == ProblemSource(
            ProblemSourceKind.ENTRY_POINT, "my-entry"
        )

    def test_a_class_entry_point_is_registered(
        self, write_problem_module: Callable[[str, str], str]
    ) -> None:
        class_path = f"{write_problem_module('registry_test_entry_class', 'class-variant')}:Variant"
        # Importing the module registers the class already; naming the class registers it again.
        assert load_entry_point_problems([self._entry_point("class-entry", class_path)]) == ()
        assert get_problem("class-variant").description.startswith("Variant defined in")

    def test_a_broken_entry_point_is_a_warning_and_the_others_still_load(
        self, write_problem_module: Callable[[str, str], str]
    ) -> None:
        module = write_problem_module("registry_test_entry_good", "good-variant")
        warnings = load_entry_point_problems(
            [
                self._entry_point("broken", "no_such_entry_point_module"),
                self._entry_point("good", module),
            ]
        )
        assert len(warnings) == 1
        assert "'broken'" in warnings[0]
        assert "no_such_entry_point_module" in warnings[0]
        assert "good-variant" in list_problems()

    def test_an_entry_point_that_fails_after_registering_leaves_nothing_registered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "registry_test_entry_half.py").write_text(
            "from algorithm_playground.core.registry import register_problem\n"
            "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
            "@register_problem\n"
            "class Half(SortingProblem):\n"
            "    name = 'half-entry'\n\n\n"
            "raise RuntimeError('entry boom')\n"
        )
        warnings = load_entry_point_problems(
            [self._entry_point("half", "registry_test_entry_half")]
        )
        assert len(warnings) == 1 and "entry boom" in warnings[0]
        assert "half-entry" not in list_problems()
        assert "half-entry" not in problem_sources()

    def test_an_entry_point_that_is_not_a_module_or_problem_is_a_warning(self) -> None:
        warnings = load_entry_point_problems([self._entry_point("odd", "os.path:join")])
        assert len(warnings) == 1
        assert "must name a module or a Problem subclass" in warnings[0]

    def test_installed_entry_points_of_the_group_are_read_when_none_are_given(
        self, write_problem_module: Callable[[str, str], str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = write_problem_module("registry_test_installed_entry", "installed-variant")
        groups: list[str] = []

        def fake_entry_points(*, group: str) -> list[importlib.metadata.EntryPoint]:
            groups.append(group)
            return [self._entry_point("installed", module)]

        monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
        assert load_entry_point_problems() == ()
        assert groups == ["algorithm_playground.problems"]
        assert "installed-variant" in list_problems()
