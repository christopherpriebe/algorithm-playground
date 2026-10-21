"""Central registry of available ``Problem`` implementations.

Concrete problems decorate their class with ``@register_problem`` at import
time, which adds them to a module-level table. Problems reach the table from
four places, and the registry remembers which (see :class:`ProblemSource`):

* the built-in problems, imported with :mod:`algorithm_playground.problems`;
* installed packages that declare an entry point in the group
  ``algorithm_playground.problems`` (see :func:`load_entry_point_problems`);
* modules named by the ``problem_modules`` key of a configuration file;
* modules or Python files named with the ``--problem-module`` option.

The last two are loaded with :func:`load_problem_modules`. Use
:func:`get_problem`, :func:`list_problems`, :func:`problem_descriptions`, and
:func:`problem_sources` to read the table. A test of a problem copies and puts
back the table with :func:`snapshot_registry` and :func:`restore_registry`.
"""

import importlib
import importlib.metadata
import importlib.util
import os
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import TypeVar

from algorithm_playground.core.description import describe_error
from algorithm_playground.core.problem import Problem

__all__ = [
    "ENTRY_POINT_GROUP",
    "ProblemLoadError",
    "ProblemRegistrationError",
    "ProblemSource",
    "ProblemSourceKind",
    "RegistrySnapshot",
    "UnknownProblemError",
    "get_problem",
    "list_problems",
    "load_entry_point_problems",
    "load_problem_modules",
    "problem_descriptions",
    "problem_sources",
    "register_problem",
    "restore_registry",
    "snapshot_registry",
]

ENTRY_POINT_GROUP = "algorithm_playground.problems"

_BUILT_IN_PREFIX = "algorithm_playground.problems."

ProblemSubclass = TypeVar("ProblemSubclass", bound=Problem)

_REGISTRY: dict[str, type[Problem]] = {}
_SOURCES: dict[str, "ProblemSource"] = {}


def _is_file_path(name: str) -> bool:
    separators = [os.sep, *([os.altsep] if os.altsep else [])]
    return name.endswith(".py") or any(separator in name for separator in separators)


def _is_problem_module_imported(name: str) -> bool:
    """Whether the module named by ``name`` (a module name or a file path) is already imported."""
    if not _is_file_path(name):
        return name in sys.modules
    path = Path(name).expanduser().resolve()
    existing_file = getattr(sys.modules.get(path.stem), "__file__", None)
    return existing_file is not None and Path(existing_file).resolve() == path


@contextmanager
def _import_path(directories: Sequence[Path]) -> Iterator[None]:
    """Put ``directories`` at the front of ``sys.path``; they stay unless the block raises.

    A problem may import its neighbors lazily, from inside a hook, long after
    its module was loaded, so the directories stay for the rest of the process.
    """
    added = [str(directory) for directory in directories if str(directory) not in sys.path]
    sys.path[:0] = added
    importlib.invalidate_caches()
    try:
        yield
    except BaseException:
        # Undo the change for any failure, including KeyboardInterrupt, then let it propagate.
        for entry in added:
            if entry in sys.path:
                sys.path.remove(entry)
        raise


def _import_problem_module(name: str, search_directories: Sequence[Path]) -> None:
    """Import a module by name or by file path; do nothing if the file is already imported."""
    if not _is_file_path(name):
        with _import_path(search_directories):
            importlib.import_module(name)
        return

    path = Path(name).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    existing = sys.modules.get(path.stem)
    if existing is not None:
        if _is_problem_module_imported(name):
            return
        raise ImportError(
            f"a different module named '{path.stem}' is already imported; rename the file"
        )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} is not a Python file that can be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    try:
        with _import_path([*search_directories, path.parent]):
            spec.loader.exec_module(module)
    except BaseException:
        # A half-executed module must not stay importable, whatever interrupted it.
        sys.modules.pop(path.stem, None)
        raise


def _load_failure_message(module_name: str, error: Exception) -> str:
    prefix = f"Could not load problem module '{module_name}': {describe_error(error)}"
    if isinstance(error, FileNotFoundError) and _is_file_path(module_name):
        return f"{prefix}. Paths are relative to the current directory."
    if isinstance(error, ModuleNotFoundError) and error.name is not None:
        if module_name == error.name or module_name.startswith(f"{error.name}."):
            return (
                f"{prefix}. To load it, pass the path of the file (--problem-module "
                f"path/to/{module_name.rpartition('.')[2]}.py), run the command from the directory "
                "that holds the module, or list that directory under python_paths in the "
                "configuration file."
            )
        return f"{prefix}. The module imports '{error.name}', which is not installed."
    return prefix


def _forget_new_problems(before: set[str]) -> None:
    """Remove the problems registered since ``before``, so a half-loaded plugin is not usable."""
    for name in set(_REGISTRY) - before:
        _REGISTRY.pop(name, None)
        _SOURCES.pop(name, None)


def _label_new_problems(before: set[str], source: "ProblemSource") -> None:
    for name in set(_REGISTRY) - before:
        _SOURCES[name] = source


class ProblemRegistrationError(ValueError):
    """Raised when a ``Problem`` subclass cannot be registered."""


class UnknownProblemError(LookupError):
    """Raised when no problem is registered under a requested name."""


class ProblemLoadError(RuntimeError):
    """Raised when a module that should provide problems cannot be loaded."""


class ProblemSourceKind(Enum):
    """Where a registered problem came from."""

    BUILT_IN = "built-in"
    ENTRY_POINT = "entry point"
    CONFIGURATION = "configuration"
    OPTION = "option"
    DIRECT = "direct"


@dataclass(frozen=True)
class ProblemSource:
    """Where a problem was registered from.

    Args:
        kind: The kind of source.
        detail: Names the entry point or the module.
    """

    kind: ProblemSourceKind
    detail: str = ""

    def describe(self) -> str:
        """Return the source as shown to users, for example ``entry point: my-graphs``."""
        if self.kind is ProblemSourceKind.BUILT_IN:
            return "built-in"
        elif self.kind is ProblemSourceKind.DIRECT:
            return "registered in code"
        else:
            return f"{self.kind.value}: {self.detail}"


@dataclass(frozen=True)
class RegistrySnapshot:
    """A copy of the registry taken by :func:`snapshot_registry`."""

    problems: Mapping[str, type[Problem]]
    sources: Mapping[str, ProblemSource]


def register_problem(cls: type[ProblemSubclass]) -> type[ProblemSubclass]:
    """Add a ``Problem`` subclass to the central registry; use it as a class decorator.

    Args:
        cls: The class. It must define a non-empty ``name`` class attribute and
            implement every abstract method of
            :class:`~algorithm_playground.core.problem.Problem`.

    Returns:
        ``cls`` unchanged, so that the function works as ``@register_problem``.

    Raises:
        ProblemRegistrationError: If ``name`` is missing or empty, abstract
            methods are missing (the message lists them), or another class is
            already registered under the same name.
    """
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise ProblemRegistrationError(
            f"{cls.__name__} must define a non-empty 'name' class attribute"
        )
    missing = sorted(getattr(cls, "__abstractmethods__", ()))
    if missing:
        raise ProblemRegistrationError(
            f"{cls.__name__} cannot be registered because it does not implement: "
            f"{', '.join(missing)}. Implement every abstract method of Problem "
            "(see the guide 'Writing a problem'), then register it."
        )
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ProblemRegistrationError(
            f"Problem name '{name}' is already registered by "
            f"{_REGISTRY[name].__module__}.{_REGISTRY[name].__name__}"
        )
    if name not in _REGISTRY:
        built_in = cls.__module__.startswith(_BUILT_IN_PREFIX)
        kind = ProblemSourceKind.BUILT_IN if built_in else ProblemSourceKind.DIRECT
        _SOURCES[name] = ProblemSource(kind)
    _REGISTRY[name] = cls
    return cls


def get_problem(name: str) -> Problem:
    """Instantiate a registered problem.

    Args:
        name: The name the problem is registered under.

    Returns:
        A new instance of the problem.

    Raises:
        UnknownProblemError: If no problem is registered under ``name``. The
            message lists the registered names.
    """
    try:
        problem_class = _REGISTRY[name]
    except KeyError as error:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise UnknownProblemError(
            f"Unknown problem '{name}'. Registered problems: {available}"
        ) from error
    return problem_class()


def list_problems() -> list[str]:
    """Return the sorted list of registered problem names."""
    return sorted(_REGISTRY)


def problem_descriptions() -> dict[str, str]:
    """Return each registered problem's one-line description, keyed by name in sorted order."""
    return {name: getattr(_REGISTRY[name], "description", "") for name in sorted(_REGISTRY)}


def problem_sources() -> dict[str, ProblemSource]:
    """Return where each registered problem came from, keyed by name in sorted order."""
    return {name: _SOURCES[name] for name in sorted(_REGISTRY)}


def snapshot_registry() -> RegistrySnapshot:
    """Copy the registry, so that a test of a problem can change it and put it back.

    A test that registers problems or loads problem modules takes a snapshot
    first and passes it to :func:`restore_registry` afterwards, so that the
    problems it registered do not leak into other tests.

    Returns:
        The copy.
    """
    return RegistrySnapshot(dict(_REGISTRY), dict(_SOURCES))


def restore_registry(snapshot: RegistrySnapshot) -> None:
    """Make the registry hold exactly the problems and sources of a snapshot.

    Args:
        snapshot: A snapshot taken by :func:`snapshot_registry`.
    """
    _REGISTRY.clear()
    _REGISTRY.update(snapshot.problems)
    _SOURCES.clear()
    _SOURCES.update(snapshot.sources)


def load_problem_modules(
    module_names: Iterable[str],
    kind: ProblemSourceKind,
    *,
    search_directories: Sequence[Path] = (),
) -> tuple[str, ...]:
    """Import modules so that their ``@register_problem`` decorators run.

    A name that ends in ``.py`` or contains a path separator is the path of a
    Python file, relative to the current directory, and is loaded from there;
    anything else is a module name. Modules that were imported before are not
    run again.

    Args:
        module_names: The modules to import.
        kind: Where the problems come from; use ``CONFIGURATION`` or
            ``OPTION``. The problems a module registers are recorded with this
            kind and the module's name as the detail.
        search_directories: Directories put at the front of the import path,
            together with the directory of a file, so that the module can
            import its neighbors. They stay there for the rest of the process,
            also for imports from inside a hook, and are removed again if the
            module fails to load.

    Returns:
        One warning for each module that was imported and registered no
        problem, which usually means a ``@register_problem`` is missing.

    Raises:
        ProblemLoadError: For the first module that cannot be imported. The
            message says what to try, and the problems the module registered
            before failing are removed again.
    """
    warnings: list[str] = []
    for module_name in module_names:
        before = set(_REGISTRY)
        try:
            freshly_imported = not _is_problem_module_imported(module_name)
            _import_problem_module(module_name, search_directories)
        except Exception as error:
            # Importing runs the code of a plugin, so any exception becomes a load error.
            _forget_new_problems(before)
            raise ProblemLoadError(_load_failure_message(module_name, error)) from error
        _label_new_problems(before, ProblemSource(kind, module_name))
        if freshly_imported and set(_REGISTRY) == before:
            warnings.append(
                f"Problem module '{module_name}' registered no problems. Did you forget "
                "@register_problem on your Problem subclass?"
            )
    return tuple(warnings)


def load_entry_point_problems(
    entry_points: Iterable[importlib.metadata.EntryPoint] | None = None,
) -> tuple[str, ...]:
    """Load the problems that installed packages offer through entry points.

    Each entry point in the group ``algorithm_playground.problems`` names
    either a module, which is imported so that its decorators run, or a
    :class:`~algorithm_playground.core.problem.Problem` subclass, which is
    registered. An entry point that fails to load does not stop the others,
    and anything it registered before failing is removed again.

    Args:
        entry_points: Replaces the installed entry points (for tests).

    Returns:
        One warning per entry point that failed to load.
    """
    if entry_points is None:
        entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    warnings: list[str] = []
    for entry_point in sorted(entry_points, key=lambda candidate: candidate.name):
        before = set(_REGISTRY)
        try:
            loaded = entry_point.load()
            if isinstance(loaded, type) and issubclass(loaded, Problem):
                register_problem(loaded)
            elif not isinstance(loaded, ModuleType):
                raise ProblemLoadError("it must name a module or a Problem subclass")
        except Exception as error:
            # Loading runs the code of a plugin, so any exception is that plugin's failure.
            _forget_new_problems(before)
            warnings.append(
                f"Could not load problem entry point '{entry_point.name}' "
                f"({entry_point.value}): {describe_error(error)}"
            )
            continue
        _label_new_problems(before, ProblemSource(ProblemSourceKind.ENTRY_POINT, entry_point.name))
    return tuple(warnings)
