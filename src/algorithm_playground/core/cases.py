"""Cases: the inputs a problem is exercised on, and the plan that picks them.

A *fixture* is a named, hand-written input. A *generator* is a named function
that turns a seeded random number generator and a size into an input. A
:class:`Case` is one concrete input together with where it came from, and
that origin gives it a stable, printable identifier:

* ``fixture:empty`` is the fixture called ``empty``;
* ``generated:nearly_sorted:size=37:seed=1234567`` is what the generator
  (also called the distribution) ``nearly_sorted`` returns for size 37 and
  seed 1234567;
* ``shrunk:...`` is a smaller input derived from a failing case (see
  :func:`~algorithm_playground.core.testing.run_tests`); it records where it
  came from but cannot be replayed on its own.

Fixture and generated identifiers can be parsed back with
:func:`resolve_case`, which is how ``--case IDENTIFIER`` reproduces exactly
the input of an earlier run. A :class:`CasePlan` describes which cases a test
run should use and :func:`build_cases` expands it deterministically.

The functions here call the problem's ``fixtures`` and ``generators`` hooks and
the function of a generator. When one raises, or returns something that does not
fit, they raise :class:`~algorithm_playground.core.hooks.HookError`, which names
the hook, instead of the original exception.
"""

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from algorithm_playground.core.hooks import call_hook

if TYPE_CHECKING:
    # problem.py imports this module, so the import is for annotations only.
    from algorithm_playground.core.problem import AnyProblem

__all__ = [
    "DEFAULT_MAXIMUM_SIZE",
    "DEFAULT_RANDOM_CASE_COUNT",
    "FIXTURE_PREFIX",
    "GENERATED_PREFIX",
    "SHRUNK_PREFIX",
    "AnyCase",
    "AnyFixture",
    "AnyInputGenerator",
    "Case",
    "CaseError",
    "CaseOrigin",
    "CasePlan",
    "Fixture",
    "FixtureOrigin",
    "GeneratedOrigin",
    "InputGenerator",
    "InputT",
    "ShrunkOrigin",
    "build_cases",
    "check_sizes",
    "default_generator",
    "generate_case",
    "parse_case_identifier",
    "problem_fixtures",
    "problem_generators",
    "resolve_case",
    "select_generators",
    "startup_case",
]

InputT = TypeVar("InputT")
ItemT = TypeVar("ItemT")

FIXTURE_PREFIX = "fixture:"
GENERATED_PREFIX = "generated:"
SHRUNK_PREFIX = "shrunk:"

DEFAULT_RANDOM_CASE_COUNT = 20
DEFAULT_MAXIMUM_SIZE = 100


def _checked_list(items: Iterable[object], expected: type[ItemT]) -> list[ItemT]:
    """Collect ``items``, requiring each to be an instance of ``expected``."""
    collected: list[ItemT] = []
    for item in items:
        if not isinstance(item, expected):
            raise TypeError(
                f"it returned a {type(item).__name__} where a {expected.__name__} belongs"
            )
        collected.append(item)
    return collected


def _to_integer(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _labeled_integer(identifier: str, part: str, label: str) -> int:
    """Parse ``label=N`` where ``N`` is written the way identifiers write it (``5``, not ``05``)."""
    prefix = f"{label}="
    if part.startswith(prefix):
        digits = part.removeprefix(prefix)
        value = _to_integer(digits)
        if value is not None and str(value) == digits:
            return value
    raise CaseError(
        f"Case identifier {identifier!r} has no valid '{label}=N' part: N must be a plain "
        "integer, without a plus sign, leading zeros, underscores, or spaces"
    )


def _parse_generated_identifier(text: str) -> "GeneratedOrigin | None":
    """Parse ``generated:NAME:size=N:seed=N``; return ``None`` if the shape does not match."""
    parts = text.removeprefix(GENERATED_PREFIX).rsplit(":", 2)
    if len(parts) != 3 or not parts[0]:
        return None
    generator_name, size_part, seed_part = parts
    size = _labeled_integer(text, size_part, "size")
    if size < 0:
        raise CaseError(f"Case identifier {text!r} has a negative size")
    return GeneratedOrigin(generator_name, _labeled_integer(text, seed_part, "seed"), size)


def _fixture_cases(problem: "AnyProblem") -> list["AnyCase"]:
    return [
        Case(FixtureOrigin(fixture.name, fixture.description), fixture.input_data)
        for fixture in problem_fixtures(problem)
    ]


def _random_case(
    plan: "CasePlan", index: int, *, minimum_size: int, generators: Sequence["AnyInputGenerator"]
) -> "AnyCase":
    """Build the generated case at position ``index`` of ``plan``."""
    random_generator = random.Random(f"algorithm-playground:{plan.seed}:{index}")
    seed = random_generator.randrange(2**32)
    position = (index + random_generator.random()) / plan.random_case_count
    span = plan.maximum_size - minimum_size
    size = min(plan.maximum_size, minimum_size + int(span * position**2))
    generator = generators[(index + index // len(generators)) % len(generators)]
    return generate_case(generator, size=size, seed=seed)


class CaseError(ValueError):
    """Raised when a case identifier or a case plan cannot be turned into cases."""


@dataclass(frozen=True)
class Fixture(Generic[InputT]):
    """A named, hand-written input.

    Args:
        name: The name that identifies the fixture in case identifiers.
        input_data: The input.
        description: Why the input is interesting.
    """

    name: str
    input_data: InputT
    description: str = ""


@dataclass(frozen=True)
class InputGenerator(Generic[InputT]):
    """A named function that builds an input of a given size from a seeded random generator.

    Users know a generator as a *distribution*.

    Args:
        name: The name that identifies the generator in case identifiers. It
            must not contain a colon or whitespace.
        description: What kind of input the generator builds.
        generate: ``generate(random_generator, size)`` returns an input. It
            must return the same input whenever it receives a generator in the
            same state, must accept every size from the problem's
            ``minimum_size`` up, and must take all of its randomness from
            ``random_generator``.
    """

    name: str
    description: str
    generate: Callable[[random.Random, int], InputT]


@dataclass(frozen=True)
class FixtureOrigin:
    """The case is the fixture called ``name``.

    ``description`` repeats the fixture's description for reports; it does not
    take part in comparisons, because the identifier is the name alone.
    """

    name: str
    description: str = field(default="", compare=False)

    @property
    def identifier(self) -> str:
        """The stable text that names the case."""
        return f"{FIXTURE_PREFIX}{self.name}"


@dataclass(frozen=True)
class GeneratedOrigin:
    """The case is what generator ``generator_name`` returns for ``size`` and ``seed``."""

    generator_name: str
    seed: int
    size: int

    @property
    def identifier(self) -> str:
        """The stable text that names the case."""
        return f"{GENERATED_PREFIX}{self.generator_name}:size={self.size}:seed={self.seed}"


@dataclass(frozen=True)
class ShrunkOrigin:
    """The case is a smaller input that still fails, found by shrinking another case."""

    source_identifier: str

    @property
    def identifier(self) -> str:
        """The stable text that names the case."""
        return f"{SHRUNK_PREFIX}{self.source_identifier}"


CaseOrigin = FixtureOrigin | GeneratedOrigin | ShrunkOrigin


@dataclass(frozen=True)
class Case(Generic[InputT]):
    """One concrete input and where it came from."""

    origin: CaseOrigin
    input_data: InputT

    @property
    def identifier(self) -> str:
        """The stable text that names this case."""
        return self.origin.identifier


# Aliases for values whose input type is not known where they are handled: the engines work
# with problems of every input type.
AnyFixture = Fixture[Any]
AnyInputGenerator = InputGenerator[Any]
AnyCase = Case[Any]


@dataclass(frozen=True)
class CasePlan:
    """Which cases a test run uses.

    The generated cases are spread over the generators in turn, shifted by one
    every round, so that each of them covers the whole range of sizes.

    Args:
        include_fixtures: Whether the problem's fixtures are part of the run.
        random_case_count: The number of generated cases.
        maximum_size: The largest size of a generated case. Sizes start at the
            problem's ``minimum_size``.
        generator_names: The generators to use. Empty means all of the
            problem's generators.
        seed: The seed from which the seeds of the generated cases derive.

    Raises:
        CaseError: If ``random_case_count`` or ``maximum_size`` is negative.
    """

    include_fixtures: bool = True
    random_case_count: int = DEFAULT_RANDOM_CASE_COUNT
    maximum_size: int = DEFAULT_MAXIMUM_SIZE
    generator_names: tuple[str, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        if self.random_case_count < 0:
            raise CaseError(
                f"The random case count must not be negative, got {self.random_case_count}"
            )
        if self.maximum_size < 0:
            raise CaseError(f"The maximum size must not be negative, got {self.maximum_size}")


def default_generator(problem: "AnyProblem") -> AnyInputGenerator:
    """Return the problem's default generator: the first one it lists.

    Args:
        problem: The problem.

    Returns:
        The generator.

    Raises:
        CaseError: If the problem defines no generator.
        HookError: If the ``generators`` hook fails.
    """
    return select_generators(problem, ())[0]


def startup_case(problem: "AnyProblem", seed: int) -> AnyCase:
    """Build the smallest input of the default generator: the input startup time is measured on.

    Args:
        problem: The problem.
        seed: The seed for the generator.

    Returns:
        The case, at the problem's ``minimum_size``.

    Raises:
        CaseError: If the problem defines no generator.
        HookError: If a hook fails.
    """
    return generate_case(default_generator(problem), size=problem.minimum_size, seed=seed)


def check_sizes(problem: "AnyProblem", sizes: Sequence[int]) -> None:
    """Require every size to be one the problem accepts.

    Args:
        problem: The problem.
        sizes: The sizes to check.

    Raises:
        CaseError: If a size is below the problem's ``minimum_size``.
    """
    too_small = sorted(size for size in sizes if size < problem.minimum_size)
    if too_small:
        listing = ", ".join(str(size) for size in too_small)
        raise CaseError(
            f"Problem '{problem.name}' needs inputs of at least {problem.minimum_size} "
            f"elements, but the sizes include {listing}"
        )


def generate_case(generator: InputGenerator[InputT], *, size: int, seed: int) -> Case[InputT]:
    """Run a generator and wrap the input as a case.

    Args:
        generator: The generator to run.
        size: The size of the input.
        seed: The seed of the random generator that the generator receives.

    Returns:
        The case, identified by the generator's name, the size and the seed.

    Raises:
        CaseError: If ``size`` is negative.
        HookError: If the generator raises.
    """
    if size < 0:
        raise CaseError(f"The size must not be negative, got {size}")
    input_data = call_hook(
        f"'{generator.name}' generator", lambda: generator.generate(random.Random(seed), size)
    )
    return Case(GeneratedOrigin(generator.name, seed, size), input_data)


def build_cases(problem: "AnyProblem", plan: CasePlan) -> tuple[AnyCase, ...]:
    """Expand a plan into cases: the fixtures first, then the generated cases.

    The result depends only on the problem and the plan. Each generated case
    gets its own seed, derived from the plan's seed and the case's position.
    Sizes are stratified over ``minimum_size..maximum_size`` and squared, so
    that small inputs (where most bugs live) are over-represented while the
    largest sizes still appear. Sizes grow with the position, and the
    generator of a position is ``(position + position // count) % count``, so
    every generator gets small and large sizes alike instead of one generator
    getting all the small ones.

    Args:
        problem: The problem.
        plan: Which cases to build.

    Returns:
        The cases.

    Raises:
        CaseError: If the plan names an unknown generator, its maximum size is
            below the problem's ``minimum_size``, or the problem defines no
            generator.
        HookError: If a hook fails.
    """
    cases = _fixture_cases(problem) if plan.include_fixtures else []
    if plan.random_case_count == 0:
        return tuple(cases)

    minimum_size = problem.minimum_size
    if plan.maximum_size < minimum_size:
        raise CaseError(
            f"The maximum size {plan.maximum_size} is below the smallest size "
            f"problem '{problem.name}' accepts, {minimum_size}"
        )
    generators = select_generators(problem, plan.generator_names)
    cases.extend(
        _random_case(plan, index, minimum_size=minimum_size, generators=generators)
        for index in range(plan.random_case_count)
    )
    return tuple(cases)


def parse_case_identifier(text: str) -> FixtureOrigin | GeneratedOrigin:
    """Parse the identifier of a fixture or generated case.

    Args:
        text: ``fixture:NAME`` or ``generated:DISTRIBUTION:size=N:seed=N``.

    Returns:
        Where the case comes from.

    Raises:
        CaseError: If ``text`` is malformed, or names a shrunk case, which
            cannot be replayed on its own.
    """
    if text.startswith(FIXTURE_PREFIX):
        name = text.removeprefix(FIXTURE_PREFIX)
        if not name:
            raise CaseError(f"Case identifier {text!r} names no fixture")
        return FixtureOrigin(name)
    if text.startswith(GENERATED_PREFIX):
        origin = _parse_generated_identifier(text)
        if origin is not None:
            return origin
    if text.startswith(SHRUNK_PREFIX):
        raise CaseError(
            f"Case identifier {text!r} names a shrunk input, which cannot be replayed on its own. "
            "Use the identifier of the case it was shrunk from; shrinking runs again."
        )
    raise CaseError(
        f"Unrecognized case identifier {text!r}. Expected 'fixture:NAME' or "
        "'generated:DISTRIBUTION:size=N:seed=N'."
    )


def resolve_case(problem: "AnyProblem", identifier: str) -> AnyCase:
    """Rebuild the case named by an identifier.

    Args:
        problem: The problem.
        identifier: The identifier of a fixture or generated case.

    Returns:
        The case, with the same input as in the run that printed the identifier.

    Raises:
        CaseError: If the identifier is malformed or names no fixture,
            generator or size the problem has.
        HookError: If a hook fails.
    """
    origin = parse_case_identifier(identifier)
    if isinstance(origin, FixtureOrigin):
        fixtures = problem_fixtures(problem)
        for fixture in fixtures:
            if fixture.name == origin.name:
                return Case(FixtureOrigin(fixture.name, fixture.description), fixture.input_data)
        available = ", ".join(fixture.name for fixture in fixtures) or "(none)"
        raise CaseError(f"No fixture named '{origin.name}'. Available fixtures: {available}")
    generator = select_generators(problem, (origin.generator_name,))[0]
    check_sizes(problem, (origin.size,))
    return generate_case(generator, size=origin.size, seed=origin.seed)


def select_generators(problem: "AnyProblem", names: Sequence[str]) -> list[AnyInputGenerator]:
    """Select generators by name (users call generators distributions).

    Args:
        problem: The problem.
        names: The generator names. Empty means all of the problem's generators.

    Returns:
        The generators called ``names``, in that order and each once, or all of
        the problem's generators when ``names`` is empty.

    Raises:
        CaseError: If the problem defines no generator or ``names`` holds an
            unknown name.
        HookError: If the ``generators`` hook fails.
    """
    generators = problem_generators(problem)
    if not generators:
        raise CaseError(f"Problem '{problem.name}' defines no input distributions")
    if not names:
        return generators
    by_name = {generator.name: generator for generator in generators}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        listing = ", ".join(f"'{name}'" for name in unknown)
        available = ", ".join(by_name)
        raise CaseError(f"Unknown distribution {listing}. Available distributions: {available}")
    return [by_name[name] for name in dict.fromkeys(names)]


def problem_fixtures(problem: "AnyProblem") -> list[AnyFixture]:
    """Call the problem's ``fixtures`` hook and check what it returns.

    Args:
        problem: The problem.

    Returns:
        The fixtures.

    Raises:
        HookError: If the hook raises or yields something that is not a
            :class:`Fixture`.
    """
    return call_hook("fixtures", lambda: _checked_list(problem.fixtures(), Fixture))


def problem_generators(problem: "AnyProblem") -> list[AnyInputGenerator]:
    """Call the problem's ``generators`` hook and check what it returns.

    Args:
        problem: The problem.

    Returns:
        The generators, the default one first.

    Raises:
        HookError: If the hook raises or returns something that is not made of
            :class:`InputGenerator` objects.
    """
    return call_hook("generators", lambda: _checked_list(problem.generators(), InputGenerator))
