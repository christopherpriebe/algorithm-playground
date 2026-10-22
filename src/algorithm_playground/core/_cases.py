"""Cases: the inputs a problem is exercised on, and the plan that picks them.

A *fixture* is a named, hand-written input. A *generator* is a named function
that turns a seeded random number generator and a size (one number for each
dimension of the problem) into an input. A
:class:`Case` is one concrete input together with where it came from, and
that origin gives it a stable, printable identifier:

* ``fixture:empty`` is the fixture called ``empty``;
* ``generated:nearly_sorted:size=37:seed=1234567`` is what the generator
  (also called the distribution) ``nearly_sorted`` returns for size 37 and
  seed 1234567; a problem with several dimensions names each of them,
  ``generated:exact:vertices=100:edges=500:seed=1``;
* ``shrunk:...`` is a smaller input derived from a failing case (see
  :func:`~algorithm_playground.core.run_tests`); it records where it
  came from but cannot be replayed on its own.

Fixture and generated identifiers can be parsed back with
:func:`resolve_case`, which is how ``--case IDENTIFIER`` reproduces exactly
the input of an earlier run. A :class:`CasePlan` describes which cases a test
run should use and :func:`build_cases` expands it deterministically.

The functions here call the problem's ``fixtures`` and ``generators`` hooks and
the function of a generator. When one raises, or returns something that does not
fit, they raise :class:`~algorithm_playground.core.HookError`, which names
the hook, instead of the original exception.
"""

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from algorithm_playground.core._dimensions import (
    DEFAULT_MAXIMUM_SIZE,
    PLAIN_INTEGER_RULE,
    RESERVED_DIMENSION_NAMES,
    Dimension,
    Size,
    build_default_maximum_size,
    build_minimum_size,
    parse_plain_integer,
)
from algorithm_playground.core._errors import CaseError
from algorithm_playground.core._hooks import call_hook

if TYPE_CHECKING:
    # problem.py imports this module, so the import is for annotations only.
    from algorithm_playground.core._problem import AnyProblem

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
    "ShrunkOrigin",
    "build_cases",
    "build_startup_case",
    "check_sizes",
    "collect_problem_fixtures",
    "collect_problem_generators",
    "generate_case",
    "get_default_generator",
    "parse_case_identifier",
    "resolve_case",
    "select_generators",
]

InputT = TypeVar("InputT")
ItemT = TypeVar("ItemT")

FIXTURE_PREFIX = "fixture:"
GENERATED_PREFIX = "generated:"
SHRUNK_PREFIX = "shrunk:"

DEFAULT_RANDOM_CASE_COUNT = 20

# A generated identifier is at least NAME and seed=N once the prefix is removed.
_MINIMUM_GENERATED_PART_COUNT = 2


def _checked_list(items: Iterable[object], expected: type[ItemT]) -> list[ItemT]:
    """Collect ``items``, requiring each to be an instance of ``expected``.

    Args:
        items: The items to check.
        expected: The class each item must be an instance of.

    Returns:
        The items as a list.

    Raises:
        TypeError: If an item is not an instance of ``expected``.
    """
    collected: list[ItemT] = []
    for item in items:
        if not isinstance(item, expected):
            message = f"it returned a {type(item).__name__} where a {expected.__name__} belongs"
            raise TypeError(message)
        collected.append(item)
    return collected


def _labeled_integer(identifier: str, part: str, label: str) -> int:
    """Parse ``label=N`` where ``N`` is written the way identifiers write it (``5``, not ``05``).

    Args:
        identifier: The whole case identifier, for messages.
        part: The part of the identifier to parse.
        label: The expected label.

    Returns:
        The integer.

    Raises:
        CaseError: If the part is not ``label=N`` with a plainly written ``N``.
    """
    prefix = f"{label}="
    if label and part.startswith(prefix):
        value = parse_plain_integer(part.removeprefix(prefix))
        if value is not None:
            return value
    message = f"Case identifier {identifier!r} has no valid '{label}=N' part: {PLAIN_INTEGER_RULE}"
    raise CaseError(message)


def _parse_generated_identifier(text: str) -> "GeneratedOrigin | None":
    """Parse ``generated:NAME:label=N:...:seed=N``; return ``None`` if the shape does not match.

    Args:
        text: The case identifier.

    Returns:
        The origin, or ``None`` when ``text`` does not have the shape.

    Raises:
        CaseError: If the dimensions or the seed are malformed, a dimension is
            negative or named twice, or no dimension is named.
    """
    parts = text.removeprefix(GENERATED_PREFIX).split(":")
    if len(parts) < _MINIMUM_GENERATED_PART_COUNT or not parts[0]:
        return None
    generator_name, *dimension_parts, seed_part = parts
    seed = _labeled_integer(text, seed_part, "seed")
    if not dimension_parts:
        message = f"Case identifier {text!r} names no dimension"
        raise CaseError(message)
    values: dict[str, int] = {}
    for part in dimension_parts:
        label = part.partition("=")[0]
        if label in RESERVED_DIMENSION_NAMES:
            message = f"Case identifier {text!r} uses the reserved name '{label}' for a dimension"
            raise CaseError(message)
        if label and not label.isidentifier():
            message = f"Case identifier {text!r} has the dimension label {label!r}, which is not a Python identifier"
            raise CaseError(message)
        value = _labeled_integer(text, part, label)
        if value < 0:
            message = f"Case identifier {text!r} has a negative '{label}'"
            raise CaseError(message)
        if label in values:
            message = (
                f"Case identifier {text!r} names the dimension '{label}' more than once"
            )
            raise CaseError(message)
        values[label] = value
    return GeneratedOrigin(
        generator_name=generator_name, seed=seed, size=Size(**values)
    )


def _fixture_cases(problem: "AnyProblem") -> list["AnyCase"]:
    return [
        Case(
            FixtureOrigin(fixture.name, description=fixture.description),
            fixture.input_data,
        )
        for fixture in collect_problem_fixtures(problem)
    ]


@dataclass(frozen=True, slots=True)
class _SizeSampler:
    """Draw the sizes of the generated cases of one plan.

    Args:
        dimensions: The dimensions of the problem, in declared order.
        maximum_size: The largest size to generate.
        permutations: The shuffled strata of every dimension but the first.
        count: The number of generated cases.
    """

    dimensions: Sequence[Dimension]
    maximum_size: Size
    permutations: Mapping[str, Sequence[int]]
    count: int

    def sample(self, index: int, random_generator: random.Random) -> Size:
        """Draw the size of the case at position ``index``.

        Args:
            index: The position of the case among the generated cases.
            random_generator: The generator of the case, which supplies the
                jitter inside each stratum.

        Returns:
            The size.
        """
        values: dict[str, int] = {}
        for dimension in self.dimensions:
            permutation = self.permutations.get(dimension.name)
            stratum = index if permutation is None else permutation[index]
            position = (stratum + random_generator.random()) / self.count
            maximum = self.maximum_size[dimension.name]
            span = maximum - dimension.minimum
            values[dimension.name] = min(
                maximum, dimension.minimum + int(span * position**2)
            )
        return Size(**values)


def _build_size_sampler(
    plan: "CasePlan", dimensions: Sequence[Dimension], maximum_size: Size
) -> _SizeSampler:
    """Shuffle the strata of every dimension but the first and bundle them with the bounds.

    Args:
        plan: The plan the cases belong to.
        dimensions: The dimensions of the problem, in declared order.
        maximum_size: The largest size to generate.

    Returns:
        The sampler.
    """
    permutations: dict[str, list[int]] = {}
    for dimension in dimensions[1:]:
        permutation = list(range(plan.random_case_count))
        random.Random(  # noqa: S311  seeded generator for reproducible inputs, not cryptography
            f"algorithm-playground:{plan.seed}:{dimension.name}"
        ).shuffle(permutation)
        permutations[dimension.name] = permutation
    return _SizeSampler(
        dimensions=dimensions,
        maximum_size=maximum_size,
        permutations=permutations,
        count=plan.random_case_count,
    )


def _random_case(
    plan: "CasePlan",
    index: int,
    *,
    sampler: _SizeSampler,
    generators: Sequence["AnyInputGenerator"],
) -> "AnyCase":
    """Build the generated case at position ``index`` of ``plan``.

    Args:
        plan: The plan the case belongs to.
        index: The position of the case among the generated cases.
        sampler: The draw of the sizes.
        generators: The generators to alternate between.

    Returns:
        The generated case.
    """
    random_generator = random.Random(  # noqa: S311  seeded generator for reproducible inputs, not cryptography
        f"algorithm-playground:{plan.seed}:{index}"
    )
    seed = random_generator.randrange(2**32)
    size = sampler.sample(index, random_generator)
    generator = generators[(index + index // len(generators)) % len(generators)]
    return generate_case(generator, size=size, seed=seed)


def _is_valid_generator_name(name: str) -> bool:
    """Tell whether a generator name can be read back from a case identifier.

    Args:
        name: The name to check.

    Returns:
        Whether the name is non-empty and has no colon or whitespace.
    """
    return (
        isinstance(name, str)
        and bool(name)
        and ":" not in name
        and not any(character.isspace() for character in name)
    )


@dataclass(frozen=True, slots=True)
class Fixture(Generic[InputT]):
    """A named, hand-written input.

    Args:
        name: The name that identifies the fixture in case identifiers.
        input_data: The input.
        description: Why the input is interesting.

    Raises:
        ValueError: If the name is empty.
    """

    name: str
    input_data: InputT
    _: KW_ONLY
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            message = "A fixture needs a non-empty name"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class InputGenerator(Generic[InputT]):
    """A named function that builds an input of a given size from a seeded random generator.

    Users know a generator as a *distribution*.

    Args:
        name: The name that identifies the generator in case identifiers. It
            must not contain a colon or whitespace.
        description: What kind of input the generator builds.
        generate: ``generate(random_generator, **size)`` returns an input. It
            receives the random generator positionally and one keyword argument
            per dimension of the problem, so a generator for a problem with the
            one dimension ``size`` can be written ``generate(random_generator,
            size)``. It must return the same input whenever it receives a
            generator in the same state, must accept every combination of
            values at or above the minimums of the problem's dimensions, and
            must take all of its randomness from ``random_generator``.

    Raises:
        ValueError: If the name is empty or contains a colon or whitespace.
    """

    name: str
    _: KW_ONLY
    description: str
    generate: Callable[..., InputT]

    def __post_init__(self) -> None:
        if not _is_valid_generator_name(self.name):
            message = (
                f"The generator name {self.name!r} must be non-empty and contain "
                "no colon or whitespace"
            )
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class FixtureOrigin:
    """The case is the fixture called ``name``.

    ``description`` repeats the fixture's description for reports; it does not
    take part in comparisons, because the identifier is the name alone.
    """

    name: str
    _: KW_ONLY
    description: str = field(default="", compare=False)

    @property
    def identifier(self) -> str:
        """The stable text that names the case."""
        return f"{FIXTURE_PREFIX}{self.name}"


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedOrigin:
    """The case is what generator ``generator_name`` returns for ``size`` and ``seed``."""

    generator_name: str
    seed: int
    size: Size

    @property
    def identifier(self) -> str:
        """The stable text that names the case."""
        return f"{GENERATED_PREFIX}{self.generator_name}:{self.size}:seed={self.seed}"


@dataclass(frozen=True, slots=True)
class ShrunkOrigin:
    """The case is a smaller input that still fails, found by shrinking another case."""

    source_identifier: str

    @property
    def identifier(self) -> str:
        """The stable text that names the case."""
        return f"{SHRUNK_PREFIX}{self.source_identifier}"


CaseOrigin = FixtureOrigin | GeneratedOrigin | ShrunkOrigin


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class CasePlan:
    """Which cases a test run uses.

    The generated cases are spread over the generators in turn, shifted by one
    every round, so that each of them covers the whole range of sizes.

    The first dimension of the problem is stratified over the positions of the
    cases and squared, so that small inputs are over-represented. Every later
    dimension gets its own Latin-hypercube style stratification: a permutation
    of the positions, shuffled by the plan's seed and the name of the
    dimension, picks the stratum of each case, so the dimensions vary
    independently while each of them still covers its whole range.

    Args:
        include_fixtures: Whether the problem's fixtures are part of the run.
        random_case_count: The number of generated cases.
        maximum_size: The largest size of a generated case, for each dimension.
            ``None`` means the default maximum of each dimension of the
            problem. Sizes start at the minimums of the dimensions.
        generator_names: The generators to use. Empty means all of the
            problem's generators.
        seed: The seed from which the seeds of the generated cases derive.

    Raises:
        CaseError: If ``random_case_count`` is negative.
    """

    include_fixtures: bool = True
    random_case_count: int = DEFAULT_RANDOM_CASE_COUNT
    maximum_size: Size | None = None
    generator_names: tuple[str, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        if self.random_case_count < 0:
            message = f"The random case count must not be negative, got {self.random_case_count}"
            raise CaseError(message)


def get_default_generator(problem: "AnyProblem") -> AnyInputGenerator:
    """Return the problem's default generator: the first one it lists.

    Raise :class:`CaseError` if the problem defines no generator.
    Raise :class:`~algorithm_playground.core.HookError` if the ``generators`` hook fails.

    Args:
        problem: The problem.

    Returns:
        The generator.
    """
    return select_generators(problem, ())[0]


def build_startup_case(problem: "AnyProblem", seed: int) -> AnyCase:
    """Build the smallest input of the default generator: the input startup time is measured on.

    Raise :class:`CaseError` if the problem defines no generator.
    Raise :class:`~algorithm_playground.core.HookError` if a hook fails.

    Args:
        problem: The problem.
        seed: The seed for the generator.

    Returns:
        The case, at the problem's minimum size.
    """
    return generate_case(
        get_default_generator(problem), size=build_minimum_size(problem), seed=seed
    )


def _require_dimensions(problem: "AnyProblem", size: Size, subject: str) -> None:
    """Require a size to name exactly the dimensions of the problem.

    Args:
        problem: The problem.
        size: The size to check.
        subject: What the size is, for the message.

    Raises:
        CaseError: If the size names other dimensions than the problem has.
    """
    names = [dimension.name for dimension in problem.dimensions]
    if set(size) != set(names):
        message = (
            f"Problem '{problem.name}' has the dimensions {', '.join(names)}, "
            f"but {subject} names {', '.join(size)}"
        )
        raise CaseError(message)


def check_sizes(problem: "AnyProblem", sizes: Sequence[Size]) -> None:
    """Require every size to be one the problem accepts.

    Args:
        problem: The problem.
        sizes: The sizes to check.

    Raises:
        CaseError: If a size names other dimensions than the problem has, or is
            below the minimum of a dimension.
    """
    for size in sizes:
        _require_dimensions(problem, size, "a size")
    for dimension in problem.dimensions:
        too_small = sorted(
            (size for size in sizes if size[dimension.name] < dimension.minimum),
            key=lambda size: tuple(size.values()),
        )
        if too_small:
            listing = ", ".join(str(size) for size in too_small)
            message = (
                f"Problem '{problem.name}' needs a '{dimension.name}' of at least "
                f"{dimension.minimum}, but the sizes include {listing}"
            )
            raise CaseError(message)


def generate_case(
    generator: InputGenerator[InputT], *, size: Size, seed: int
) -> Case[InputT]:
    """Run a generator and wrap the input as a case.

    The generator receives the random generator and one keyword argument per
    dimension of ``size``.

    Raise :class:`~algorithm_playground.core.HookError` if the generator raises.

    Args:
        generator: The generator to run.
        size: The size of the input.
        seed: The seed of the random generator that the generator receives.

    Returns:
        The case, identified by the generator's name, the size and the seed.
    """
    input_data = call_hook(
        f"'{generator.name}' generator",
        lambda: generator.generate(
            random.Random(seed),  # noqa: S311  seeded generator for reproducible inputs, not cryptography
            **size,
        ),
    )
    return Case(
        GeneratedOrigin(generator_name=generator.name, seed=seed, size=size), input_data
    )


def build_cases(problem: "AnyProblem", plan: CasePlan) -> tuple[AnyCase, ...]:
    """Expand a plan into cases: the fixtures first, then the generated cases.

    The result depends only on the problem and the plan. Each generated case
    gets its own seed, derived from the plan's seed and the case's position.
    The first dimension is stratified over its minimum up to the maximum and
    squared, so that small inputs (where most bugs live) are over-represented
    while the largest sizes still appear; it grows with the position. Every
    later dimension is stratified the same way but in a shuffled order, so the
    dimensions vary independently. The generator of a position is
    ``(position + position // count) % count``, so every generator gets small
    and large sizes alike instead of one generator getting all the small
    ones.

    Raise :class:`~algorithm_playground.core.HookError` if a hook fails.

    Args:
        problem: The problem.
        plan: Which cases to build.

    Returns:
        The cases.

    Raises:
        CaseError: If the plan names an unknown generator, its maximum size names other
            dimensions than the problem has or is below the minimum of one, or the
            problem defines no generator.
    """
    cases = _fixture_cases(problem) if plan.include_fixtures else []
    if plan.random_case_count == 0:
        return tuple(cases)

    maximum_size = (
        build_default_maximum_size(problem)
        if plan.maximum_size is None
        else plan.maximum_size
    )
    _require_dimensions(problem, maximum_size, "the maximum")
    for dimension in problem.dimensions:
        if maximum_size[dimension.name] < dimension.minimum:
            message = (
                f"The maximum {maximum_size} is below the smallest size "
                f"problem '{problem.name}' accepts for '{dimension.name}', "
                f"{dimension.minimum}"
            )
            raise CaseError(message)
    generators = select_generators(problem, plan.generator_names)
    sampler = _build_size_sampler(plan, problem.dimensions, maximum_size)
    cases.extend(
        _random_case(plan, index, sampler=sampler, generators=generators)
        for index in range(plan.random_case_count)
    )
    return tuple(cases)


def parse_case_identifier(text: str) -> FixtureOrigin | GeneratedOrigin:
    """Parse the identifier of a fixture or generated case.

    Args:
        text: ``fixture:NAME`` or ``generated:DISTRIBUTION:size=N:seed=N`` (one
            ``name=N`` part for each dimension).

    Returns:
        Where the case comes from.

    Raises:
        CaseError: If ``text`` is malformed, or names a shrunk case, which
            cannot be replayed on its own.
    """
    if text.startswith(FIXTURE_PREFIX):
        name = text.removeprefix(FIXTURE_PREFIX)
        if not name:
            message = f"Case identifier {text!r} names no fixture"
            raise CaseError(message)
        return FixtureOrigin(name)
    if text.startswith(GENERATED_PREFIX):
        origin = _parse_generated_identifier(text)
        if origin is not None:
            return origin
    if text.startswith(SHRUNK_PREFIX):
        message = (
            f"Case identifier {text!r} names a shrunk input, which cannot be replayed on its own. "
            "Use the identifier of the case it was shrunk from; shrinking runs again."
        )
        raise CaseError(message)
    message = (
        f"Unrecognized case identifier {text!r}. Expected 'fixture:NAME' or "
        "'generated:DISTRIBUTION:size=N:seed=N' (one 'name=N' part for each dimension)."
    )
    raise CaseError(message)


def resolve_case(problem: "AnyProblem", identifier: str) -> AnyCase:
    """Rebuild the case named by an identifier.

    Raise :class:`~algorithm_playground.core.HookError` if a hook fails.

    Args:
        problem: The problem.
        identifier: The identifier of a fixture or generated case.

    Returns:
        The case, with the same input as in the run that printed the identifier.

    Raises:
        CaseError: If the identifier is malformed or names no fixture, generator or size
            the problem has.
    """
    origin = parse_case_identifier(identifier)
    if isinstance(origin, FixtureOrigin):
        fixtures = collect_problem_fixtures(problem)
        for fixture in fixtures:
            if fixture.name == origin.name:
                return Case(
                    FixtureOrigin(fixture.name, description=fixture.description),
                    fixture.input_data,
                )
        available = ", ".join(fixture.name for fixture in fixtures) or "(none)"
        message = f"No fixture named '{origin.name}'. Available fixtures: {available}"
        raise CaseError(message)
    generator = select_generators(problem, (origin.generator_name,))[0]
    check_sizes(problem, (origin.size,))
    size = Size(
        **{
            dimension.name: origin.size[dimension.name]
            for dimension in problem.dimensions
        }
    )
    return generate_case(generator, size=size, seed=origin.seed)


def select_generators(
    problem: "AnyProblem", names: Sequence[str]
) -> list[AnyInputGenerator]:
    """Select generators by name (users call generators distributions).

    Raise :class:`~algorithm_playground.core.HookError` if the ``generators`` hook fails.

    Args:
        problem: The problem.
        names: The generator names. Empty means all of the problem's generators.

    Returns:
        The generators called ``names``, in that order and each once, or all of
        the problem's generators when ``names`` is empty.

    Raises:
        CaseError: If the problem defines no generator or ``names`` holds an unknown
            name.
    """
    generators = collect_problem_generators(problem)
    if not generators:
        message = f"Problem '{problem.name}' defines no input distributions"
        raise CaseError(message)
    if not names:
        return generators
    by_name = {generator.name: generator for generator in generators}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        listing = ", ".join(f"'{name}'" for name in unknown)
        available = ", ".join(by_name)
        message = (
            f"Unknown distribution {listing}. Available distributions: {available}"
        )
        raise CaseError(message)
    return [by_name[name] for name in dict.fromkeys(names)]


def collect_problem_fixtures(problem: "AnyProblem") -> list[AnyFixture]:
    """Call the problem's ``fixtures`` hook and check what it returns.

    Raise :class:`~algorithm_playground.core.HookError` if the hook raises or yields something that is not a
    :class:`Fixture`.

    Args:
        problem: The problem.

    Returns:
        The fixtures.
    """
    return call_hook("fixtures", lambda: _checked_list(problem.fixtures(), Fixture))


def collect_problem_generators(problem: "AnyProblem") -> list[AnyInputGenerator]:
    """Call the problem's ``generators`` hook and check what it returns.

    Raise :class:`~algorithm_playground.core.HookError` if the hook raises or returns something that is not made
    of :class:`InputGenerator` objects.

    Args:
        problem: The problem.

    Returns:
        The generators, the default one first.
    """
    return call_hook(
        "generators", lambda: _checked_list(problem.generators(), InputGenerator)
    )
