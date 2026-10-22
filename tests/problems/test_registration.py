"""Tests for registering, listing, and loading problems."""

import importlib.metadata
import sys
import textwrap
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    ENTRY_POINT_GROUP,
    Fixture,
    InputGenerator,
    Problem,
    ProblemLoadError,
    ProblemRegistrationError,
    ProblemSource,
    ProblemSourceKind,
    RegistrySnapshot,
    UnknownProblemError,
    VerificationResult,
    get_problem,
    list_problem_descriptions,
    list_problem_sources,
    list_problems,
    load_entry_point_problems,
    load_problem_modules,
    register_problem,
    restore_registry,
    snapshot_registry,
)
from algorithm_playground.problems.sorting import SortingProblem

# A problem module whose fixtures hook imports a module that sits next to the file.
LAZY_PROBLEM_SOURCE = (
    "from algorithm_playground.core import register_problem\n"
    "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
    "@register_problem\n"
    "class Lazy(SortingProblem):\n"
    "    name = 'lazy-variant'\n\n"
    "    def fixtures(self):\n"
    "        import registry_test_lazy_neighbor\n"
    "        return super().fixtures()\n"
)


class StubProblem(Problem[list[int], list[int], None]):
    """A complete problem that does nothing, for registering."""

    name = "stub-for-tests"
    description = "Stub problem used by unit tests."

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        path.write_bytes(b"")

    @override
    def deserialize_output(self, path: Path) -> list[int]:
        return []

    @override
    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield from ()

    @override
    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return ()

    @override
    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return VerificationResult(True)


class AnonymousProblem(StubProblem):
    """A problem without a name."""

    name = ""


class ConflictingProblem(StubProblem):
    """A different problem that claims the name of the stub problem."""

    name = "stub-for-tests"


class IncompleteProblem(Problem[list[int], list[int], None]):
    """A problem that defines only one of the abstract methods."""

    name = "incomplete"
    description = "Forgot most of the interface."

    @override
    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield from ()


@pytest.fixture
def write_problem_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forget_modules: Callable[..., None]
) -> Callable[[str, str], str]:
    """A function that writes an importable module registering a sorting variant.

    The function takes the module name and the name of the problem and returns the module name.
    """
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(module_name: str, problem_name: str) -> str:
        forget_modules(module_name)
        (tmp_path / f"{module_name}.py").write_text(
            textwrap.dedent(
                f"""\
                from algorithm_playground.core import register_problem
                from algorithm_playground.problems.sorting import SortingProblem


                @register_problem
                class Variant(SortingProblem):
                    name = "{problem_name}"
                    description = "Variant defined in {module_name}."
                """
            )
        )
        return module_name

    return write


def build_snapshot_without(name: str) -> RegistrySnapshot:
    """Build a snapshot of the registry as it is, minus the problem called ``name``."""
    snapshot = snapshot_registry()
    return RegistrySnapshot(
        {key: value for key, value in snapshot.problems.items() if key != name},
        {key: value for key, value in snapshot.sources.items() if key != name},
    )


def write_problem_file(directory: Path, name: str, problem_name: str) -> Path:
    """Write a Python file that registers a sorting variant called ``problem_name``."""
    path = directory / name
    path.write_text(
        "from algorithm_playground.core import register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
        "@register_problem\n"
        "class FromFile(SortingProblem):\n"
        f"    name = {problem_name!r}\n"
    )
    return path


def build_entry_point(name: str, value: str) -> importlib.metadata.EntryPoint:
    """Build an entry point of the problem group."""
    return importlib.metadata.EntryPoint(
        name=name, value=value, group=ENTRY_POINT_GROUP
    )


def test_register_problem_adds_to_registry() -> None:
    """Test a registered problem is listed and can be instantiated by name."""
    register_problem(StubProblem)

    assert "stub-for-tests" in list_problems()
    assert type(get_problem("stub-for-tests")) is StubProblem


def test_restoring_a_snapshot_forgets_what_was_registered_since() -> None:
    """Test restoring a snapshot removes the problems registered after it was taken."""
    snapshot = snapshot_registry()
    register_problem(StubProblem)
    assert "stub-for-tests" in list_problems()

    restore_registry(snapshot)

    assert "stub-for-tests" not in list_problems()
    assert "stub-for-tests" not in list_problem_sources()


def test_restoring_a_snapshot_brings_back_what_was_removed() -> None:
    """Test restoring a snapshot brings back a problem removed since it was taken."""
    register_problem(StubProblem)
    snapshot = snapshot_registry()
    restore_registry(build_snapshot_without("stub-for-tests"))
    assert "stub-for-tests" not in list_problems()

    restore_registry(snapshot)

    assert type(get_problem("stub-for-tests")) is StubProblem
    assert list_problem_sources()["stub-for-tests"].kind is ProblemSourceKind.DIRECT


def test_a_snapshot_is_not_changed_by_later_registrations() -> None:
    """Test registering a problem after taking a snapshot does not alter the snapshot."""
    snapshot = snapshot_registry()

    register_problem(StubProblem)

    assert "stub-for-tests" not in snapshot.problems
    assert "stub-for-tests" not in snapshot.sources


def test_register_problem_returns_class_unchanged() -> None:
    """Test the decorator returns the class it was given."""
    returned = register_problem(StubProblem)

    assert returned is StubProblem


def test_register_problem_rejects_missing_name() -> None:
    """Test a problem without a name cannot be registered."""
    with pytest.raises(
        ProblemRegistrationError, match="must define a non-empty 'name'"
    ):
        register_problem(AnonymousProblem)


def test_register_problem_rejects_an_incomplete_subclass_listing_what_is_missing() -> (
    None
):
    """Test a problem that leaves abstract methods undefined is rejected with the missing names."""
    with pytest.raises(
        ProblemRegistrationError, match="IncompleteProblem cannot be registered"
    ) as raised:
        register_problem(IncompleteProblem)

    message = str(raised.value)
    assert "deserialize_output, generators, serialize_input, verify" in message
    assert (
        "fixtures"
        not in message.split("does not implement:")[1].split(".", maxsplit=1)[0]
    )
    assert "incomplete" not in list_problems()


def test_register_problem_rejects_duplicate_name() -> None:
    """Test a different problem cannot take the name of a registered one."""
    register_problem(StubProblem)

    with pytest.raises(
        ProblemRegistrationError, match="'stub-for-tests' is already registered"
    ):
        register_problem(ConflictingProblem)


def test_a_duplicate_name_is_reported_with_the_public_path_of_the_registered_class() -> (
    None
):
    """Test the message names the registered class as users import it, not its private module."""
    impostor = type("ImpostorSorting", (SortingProblem,), {"name": "sorting"})

    with pytest.raises(
        ProblemRegistrationError,
        match=(
            r"'sorting' is already registered by "
            r"algorithm_playground\.problems\.sorting\.SortingProblem$"
        ),
    ):
        register_problem(impostor)


def test_get_problem_instantiates_registered_class() -> None:
    """Test getting a problem by name gives an instance of the registered class."""
    register_problem(StubProblem)

    instance = get_problem("stub-for-tests")

    assert isinstance(instance, StubProblem)


def test_get_problem_raises_for_unknown_name() -> None:
    """Test an unknown problem name is a lookup error that lists the registered problems."""
    with pytest.raises(
        UnknownProblemError,
        match=r"^Unknown problem 'not-a-problem'\. Registered problems: ",
    ) as raised:
        get_problem("not-a-problem")

    assert isinstance(raised.value, LookupError)


def test_list_problems_returns_sorted_names() -> None:
    """Test the registered problem names are listed in sorted order."""
    register_problem(StubProblem)

    names = list_problems()

    assert names == sorted(names)
    assert "stub-for-tests" in names


def test_re_registering_same_class_is_idempotent() -> None:
    """Test registering the same class twice keeps a single registration."""
    register_problem(StubProblem)

    register_problem(StubProblem)

    assert list_problems().count("stub-for-tests") == 1


def test_problem_descriptions_maps_sorted_names_to_descriptions() -> None:
    """Test descriptions are keyed by problem name, in sorted order."""
    register_problem(StubProblem)

    descriptions = list_problem_descriptions()

    assert list(descriptions) == sorted(descriptions)
    assert descriptions["stub-for-tests"] == "Stub problem used by unit tests."


def test_built_in_problems_are_labeled_built_in() -> None:
    """Test the sorting problem is recorded as built in."""
    assert list_problem_sources()["sorting"] == ProblemSource(
        ProblemSourceKind.BUILT_IN
    )


def test_a_problem_registered_in_code_is_labeled_direct() -> None:
    """Test a problem registered by calling the decorator is recorded as registered in code."""
    register_problem(StubProblem)

    assert list_problem_sources()["stub-for-tests"].kind is ProblemSourceKind.DIRECT


def test_sources_are_keyed_by_sorted_name() -> None:
    """Test the sources are listed in the same sorted order as the problems."""
    register_problem(StubProblem)

    assert list(list_problem_sources()) == list_problems()


@pytest.mark.parametrize(
    ("source", "text"),
    [
        (ProblemSource(ProblemSourceKind.BUILT_IN), "built-in"),
        (ProblemSource(ProblemSourceKind.DIRECT), "registered in code"),
        (
            ProblemSource(ProblemSourceKind.ENTRY_POINT, "graphs"),
            "entry point: graphs",
        ),
        (
            ProblemSource(ProblemSourceKind.CONFIGURATION, "pkg.mod"),
            "configuration: pkg.mod",
        ),
        (ProblemSource(ProblemSourceKind.OPTION, "pkg.mod"), "option: pkg.mod"),
    ],
    ids=["built-in", "direct", "entry-point", "configuration", "option"],
)
def test_sources_describe_themselves(source: ProblemSource, text: str) -> None:
    """Test each kind of source is described in words, with its detail when it has one."""
    assert source.describe() == text


def test_importing_a_module_registers_its_problems_with_the_given_source(
    write_problem_module: Callable[[str, str], str],
) -> None:
    """Test the problems a module registers are recorded with the source kind it was loaded as."""
    module = write_problem_module("registry_test_module_one", "variant-one")

    load_problem_modules([module], ProblemSourceKind.CONFIGURATION)

    assert "variant-one" in list_problems()
    assert list_problem_sources()["variant-one"] == ProblemSource(
        ProblemSourceKind.CONFIGURATION, module
    )


def test_a_missing_module_is_a_load_error_naming_it() -> None:
    """Test a module that does not exist is a load error that names the module."""
    with pytest.raises(
        ProblemLoadError, match=r"'no_such_problem_module'.*ModuleNotFoundError"
    ):
        load_problem_modules(["no_such_problem_module"], ProblemSourceKind.OPTION)


def test_a_module_that_raises_while_importing_is_a_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: Callable[..., None],
) -> None:
    """Test an exception while importing a module is a load error that shows the exception."""
    forget_modules("registry_test_broken")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "registry_test_broken.py").write_text("raise RuntimeError('boom')\n")

    with pytest.raises(ProblemLoadError, match="RuntimeError: boom"):
        load_problem_modules(["registry_test_broken"], ProblemSourceKind.OPTION)


def test_a_duplicate_problem_name_is_a_load_error(
    write_problem_module: Callable[[str, str], str],
) -> None:
    """Test a module that registers a name already taken is a load error."""
    module = write_problem_module("registry_test_module_duplicate", "sorting")

    with pytest.raises(ProblemLoadError, match="already registered"):
        load_problem_modules([module], ProblemSourceKind.OPTION)


def test_a_missing_module_error_says_what_to_try() -> None:
    """Test the error for a missing module suggests passing a file or setting python_paths."""
    with pytest.raises(
        ProblemLoadError,
        match=r"--problem-module path/to/no_such_problem_module\.py",
    ) as raised:
        load_problem_modules(["no_such_problem_module"], ProblemSourceKind.OPTION)

    assert "python_paths" in str(raised.value)


def test_a_module_that_registers_nothing_is_a_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: Callable[..., None],
) -> None:
    """Test a module that registers no problem gives a warning about the missing decorator."""
    forget_modules("registry_test_forgetful")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "registry_test_forgetful.py").write_text("VALUE = 1\n")

    warnings = load_problem_modules(
        ["registry_test_forgetful"], ProblemSourceKind.OPTION
    )

    assert warnings == (
        (
            "Problem module 'registry_test_forgetful' registered no problems. "
            "Did you forget @register_problem on your Problem subclass?"
        ),
    )


def test_a_module_that_was_loaded_before_is_not_warned_about_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: Callable[..., None],
) -> None:
    """Test loading a module that registers nothing a second time gives no warning."""
    forget_modules("registry_test_loaded_twice")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "registry_test_loaded_twice.py").write_text("VALUE = 1\n")

    first = load_problem_modules(
        ["registry_test_loaded_twice"], ProblemSourceKind.OPTION
    )
    second = load_problem_modules(
        ["registry_test_loaded_twice"], ProblemSourceKind.OPTION
    )

    assert len(first) == 1
    assert second == ()


def test_a_module_that_registers_something_gives_no_warning(
    write_problem_module: Callable[[str, str], str],
) -> None:
    """Test a module that registers a problem gives no warning."""
    module = write_problem_module("registry_test_module_fine", "fine-variant")

    assert load_problem_modules([module], ProblemSourceKind.OPTION) == ()


def test_a_module_that_fails_after_registering_leaves_nothing_behind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: Callable[..., None],
) -> None:
    """Test a problem registered by a module that then fails to import is unregistered."""
    forget_modules("registry_test_half_loaded")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "registry_test_half_loaded.py").write_text(
        "from algorithm_playground.core import register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
        "@register_problem\n"
        "class Half(SortingProblem):\n"
        "    name = 'half-loaded'\n\n\n"
        "raise RuntimeError('boom after registering')\n"
    )

    with pytest.raises(ProblemLoadError, match="boom after registering"):
        load_problem_modules(["registry_test_half_loaded"], ProblemSourceKind.OPTION)

    assert "half-loaded" not in list_problems()
    assert "half-loaded" not in list_problem_sources()


def test_a_python_file_is_loaded_by_its_path(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a path to a Python file is loaded and recorded with that path as the source."""
    forget_modules("registry_test_file_problem")
    path = write_problem_file(tmp_path, "registry_test_file_problem.py", "file-variant")

    load_problem_modules([str(path)], ProblemSourceKind.OPTION)

    assert list_problem_sources()["file-variant"] == ProblemSource(
        ProblemSourceKind.OPTION, str(path)
    )


def test_a_relative_path_is_relative_to_the_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: Callable[..., None],
) -> None:
    """Test a relative path to a Python file is resolved against the current directory."""
    forget_modules("registry_test_relative_problem")
    write_problem_file(
        tmp_path, "registry_test_relative_problem.py", "relative-variant"
    )
    monkeypatch.chdir(tmp_path)

    load_problem_modules(
        ["registry_test_relative_problem.py"], ProblemSourceKind.OPTION
    )

    assert "relative-variant" in list_problems()


def test_a_module_in_a_search_directory_is_found_by_name(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a module name is found in the search directories, which join the import path."""
    forget_modules("registry_test_searched_problem")
    write_problem_file(
        tmp_path, "registry_test_searched_problem.py", "searched-variant"
    )

    load_problem_modules(
        ["registry_test_searched_problem"],
        ProblemSourceKind.OPTION,
        search_directories=[tmp_path],
    )

    assert "searched-variant" in list_problems()
    assert str(tmp_path) in sys.path


def test_a_file_can_import_the_modules_next_to_it(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a loaded file can import its neighbors because its directory joins the path."""
    forget_modules("registry_test_with_neighbor", "registry_test_neighbor")
    (tmp_path / "registry_test_neighbor.py").write_text("NAME = 'neighbor-variant'\n")
    path = tmp_path / "registry_test_with_neighbor.py"
    path.write_text(
        "from algorithm_playground.core import register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n"
        "from registry_test_neighbor import NAME\n\n\n"
        "@register_problem\n"
        "class WithNeighbor(SortingProblem):\n"
        "    name = NAME\n"
    )

    load_problem_modules([str(path)], ProblemSourceKind.OPTION)

    assert "neighbor-variant" in list_problems()
    assert str(tmp_path) in sys.path


def test_a_hook_can_import_a_neighbor_of_its_file_long_after_the_file_loaded(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a hook that imports a neighbor of its file works when it is called later."""
    forget_modules("registry_test_lazy_neighbor", "registry_test_lazy_problem")
    (tmp_path / "registry_test_lazy_neighbor.py").write_text("")
    path = tmp_path / "registry_test_lazy_problem.py"
    path.write_text(LAZY_PROBLEM_SOURCE)
    load_problem_modules([str(path)], ProblemSourceKind.OPTION)
    assert "registry_test_lazy_neighbor" not in sys.modules

    fixtures = list(get_problem("lazy-variant").fixtures())

    assert fixtures
    assert "registry_test_lazy_neighbor" in sys.modules


def test_a_hook_can_import_a_neighbor_of_a_module_found_in_a_search_directory(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a hook of a module found in a search directory can import its neighbors later."""
    forget_modules("registry_test_lazy_neighbor", "registry_test_lazy_problem")
    (tmp_path / "registry_test_lazy_neighbor.py").write_text("")
    (tmp_path / "registry_test_lazy_problem.py").write_text(LAZY_PROBLEM_SOURCE)
    load_problem_modules(
        ["registry_test_lazy_problem"],
        ProblemSourceKind.OPTION,
        search_directories=[tmp_path],
    )

    assert list(get_problem("lazy-variant").fixtures())


def test_a_file_that_fails_to_load_leaves_its_directory_off_the_import_path(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test the directory of a file that fails to load is not left on the import path."""
    forget_modules("registry_test_failing_problem")
    path = tmp_path / "registry_test_failing_problem.py"
    path.write_text("raise RuntimeError('does not load')\n")

    with pytest.raises(ProblemLoadError, match="does not load"):
        load_problem_modules([str(path)], ProblemSourceKind.OPTION)

    assert str(tmp_path) not in sys.path


def test_a_module_found_in_a_search_directory_that_fails_leaves_it_off_the_import_path(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a search directory is not left on the import path when its module fails to load."""
    forget_modules("registry_test_failing_search")
    (tmp_path / "registry_test_failing_search.py").write_text(
        "raise RuntimeError('no')\n"
    )

    with pytest.raises(ProblemLoadError, match="RuntimeError: no"):
        load_problem_modules(
            ["registry_test_failing_search"],
            ProblemSourceKind.OPTION,
            search_directories=[tmp_path],
        )

    assert str(tmp_path) not in sys.path


def test_a_file_loaded_twice_is_not_run_or_warned_about_again(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test loading the same file twice gives no warning either time."""
    forget_modules("registry_test_twice_problem")
    path = write_problem_file(
        tmp_path, "registry_test_twice_problem.py", "twice-variant"
    )

    first = load_problem_modules([str(path)], ProblemSourceKind.OPTION)
    second = load_problem_modules([str(path)], ProblemSourceKind.OPTION)

    assert first == ()
    assert second == ()


def test_a_file_that_does_not_exist_is_a_load_error_that_says_so(
    tmp_path: Path,
) -> None:
    """Test a path to a file that does not exist is a load error that explains how paths work."""
    with pytest.raises(ProblemLoadError, match="file not found") as raised:
        load_problem_modules([str(tmp_path / "missing.py")], ProblemSourceKind.OPTION)

    assert "relative to the current directory" in str(raised.value)


def test_a_file_that_raises_is_a_load_error_and_is_forgotten(
    tmp_path: Path, forget_modules: Callable[..., None]
) -> None:
    """Test a file that raises while loading is a load error and leaves no module behind."""
    forget_modules("registry_test_file_broken")
    path = tmp_path / "registry_test_file_broken.py"
    path.write_text("raise RuntimeError('file boom')\n")

    with pytest.raises(ProblemLoadError, match="RuntimeError: file boom"):
        load_problem_modules([str(path)], ProblemSourceKind.OPTION)

    assert "registry_test_file_broken" not in sys.modules


def test_a_different_module_with_the_same_name_is_refused(tmp_path: Path) -> None:
    """Test a file named like an already imported module is refused with advice to rename it."""
    path = tmp_path / "json.py"
    path.write_text("VALUE = 1\n")

    with pytest.raises(ProblemLoadError, match="rename the file"):
        load_problem_modules([str(path)], ProblemSourceKind.OPTION)


def test_a_module_entry_point_is_imported_and_labeled(
    write_problem_module: Callable[[str, str], str],
) -> None:
    """Test an entry point naming a module imports it and records the entry point as source."""
    module = write_problem_module("registry_test_entry_module", "entry-variant")

    warnings = load_entry_point_problems([build_entry_point("my-entry", module)])

    assert warnings == ()
    assert list_problem_sources()["entry-variant"] == ProblemSource(
        ProblemSourceKind.ENTRY_POINT, "my-entry"
    )


def test_a_class_entry_point_is_registered(
    write_problem_module: Callable[[str, str], str],
) -> None:
    """Test an entry point naming a problem class registers that class."""
    module = write_problem_module("registry_test_entry_class", "class-variant")
    # Importing the module registers the class already; naming the class registers it again.

    warnings = load_entry_point_problems(
        [build_entry_point("class-entry", f"{module}:Variant")]
    )

    assert warnings == ()
    assert get_problem("class-variant").description.startswith("Variant defined in")


def test_a_broken_entry_point_is_a_warning_and_the_others_still_load(
    write_problem_module: Callable[[str, str], str],
) -> None:
    """Test an entry point that fails gives a warning without stopping the other entry points."""
    module = write_problem_module("registry_test_entry_good", "good-variant")

    warnings = load_entry_point_problems(
        [
            build_entry_point("broken", "no_such_entry_point_module"),
            build_entry_point("good", module),
        ]
    )

    assert len(warnings) == 1
    assert "'broken'" in warnings[0]
    assert "no_such_entry_point_module" in warnings[0]
    assert "good-variant" in list_problems()


def test_an_entry_point_that_fails_after_registering_leaves_nothing_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: Callable[..., None],
) -> None:
    """Test a problem registered by an entry point that then fails is unregistered."""
    forget_modules("registry_test_entry_half")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "registry_test_entry_half.py").write_text(
        "from algorithm_playground.core import register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
        "@register_problem\n"
        "class Half(SortingProblem):\n"
        "    name = 'half-entry'\n\n\n"
        "raise RuntimeError('entry boom')\n"
    )

    warnings = load_entry_point_problems(
        [build_entry_point("half", "registry_test_entry_half")]
    )

    assert len(warnings) == 1
    assert "entry boom" in warnings[0]
    assert "half-entry" not in list_problems()
    assert "half-entry" not in list_problem_sources()


def test_an_entry_point_that_is_not_a_module_or_problem_is_a_warning() -> None:
    """Test an entry point that names neither a module nor a problem class gives a warning."""
    warnings = load_entry_point_problems([build_entry_point("odd", "os.path:join")])

    assert len(warnings) == 1
    assert "must name a module or a Problem subclass" in warnings[0]


def test_installed_entry_points_of_the_group_are_read_when_none_are_given(
    write_problem_module: Callable[[str, str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the installed entry points of the problem group are loaded when none are passed."""
    module = write_problem_module("registry_test_installed_entry", "installed-variant")
    groups: list[str] = []

    def find_entry_points_of_group(
        *, group: str
    ) -> list[importlib.metadata.EntryPoint]:
        groups.append(group)
        return [build_entry_point("installed", module)]

    monkeypatch.setattr(importlib.metadata, "entry_points", find_entry_points_of_group)

    warnings = load_entry_point_problems()

    assert warnings == ()
    assert groups == ["algorithm_playground.problems"]
    assert "installed-variant" in list_problems()
