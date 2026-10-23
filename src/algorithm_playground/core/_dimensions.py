"""Dimensions: the numbers that make up the size of a problem's input.

A :class:`Dimension` names one of them (a graph has ``vertices`` and
``edges``). A :class:`Size` gives one non-negative integer per dimension, and
prints as the part of a case identifier that names them,
``vertices=100:edges=500``. A problem that declares no dimension has one called
``size``.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from algorithm_playground.core._errors import CaseError

if TYPE_CHECKING:
    # problem.py imports the cases, which import this module, so the import is for annotations only.
    from algorithm_playground.core._problem import AnyProblem

__all__ = [
    "DEFAULT_MAXIMUM_SIZE",
    "PLAIN_INTEGER_RULE",
    "RESERVED_DIMENSION_NAMES",
    "Dimension",
    "Size",
    "build_default_maximum_size",
    "build_minimum_size",
    "check_dimension_name",
    "get_growth_dimension",
    "parse_plain_integer",
    "parse_size",
]

DEFAULT_MAXIMUM_SIZE = 100

PLAIN_INTEGER_RULE = "N must be a plain integer, without a plus sign, leading zeros, underscores, or spaces"


RESERVED_DIMENSION_NAMES = {
    "seed": "The dimension name 'seed' is reserved for the seed of a case",
    "random_generator": "The dimension name 'random_generator' is reserved for the generator's own argument",
}


def check_dimension_name(name: object) -> str | None:
    """Check that a name can be a dimension: a Python identifier that is not reserved.

    Args:
        name: The name to check.

    Returns:
        The reason the name is not usable, or ``None`` when it is.
    """
    if name in RESERVED_DIMENSION_NAMES:
        return RESERVED_DIMENSION_NAMES[str(name)]
    if not isinstance(name, str) or not name.isidentifier():
        return (
            f"The dimension name {name!r} must be a Python identifier: letters, "
            "digits and underscores, not starting with a digit"
        )
    return None


@dataclass(frozen=True, slots=True)
class Dimension:
    """One number that makes up the size of an input.

    Args:
        name: The name that identifies the dimension in sizes and case
            identifiers, and the name of the generator parameter that receives
            it. It must be a Python identifier (letters, digits and
            underscores, not starting with a digit) other than ``seed`` and
            ``random_generator``.
        description: What the number counts.
        minimum: The smallest value at which every generator returns a valid
            input. Startup timing, the generated test cases, the benchmark
            sizes and the ``debug`` default size all start from it.
        default_maximum: The largest value of the dimension in the cases that
            ``test`` generates when the user names no maximum.

    Raises:
        ValueError: If the name is not usable, a bound is not an integer, the
            minimum is negative, or the default maximum is below the minimum.
    """

    name: str
    _: KW_ONLY
    description: str = ""
    minimum: int = 0
    default_maximum: int = DEFAULT_MAXIMUM_SIZE

    def __post_init__(self) -> None:
        reason = check_dimension_name(self.name)
        if reason is not None:
            raise ValueError(reason)
        for field_name, value in (
            ("minimum", self.minimum),
            ("default maximum", self.default_maximum),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                message = (
                    f"The {field_name} of the dimension '{self.name}' must be an "
                    f"integer, got {value!r}"
                )
                raise ValueError(message)  # noqa: TRY004  every rule of a dimension raises ValueError
        if self.minimum < 0:
            message = (
                f"The minimum of the dimension '{self.name}' must not be negative, "
                f"got {self.minimum}"
            )
            raise ValueError(message)
        if self.default_maximum < self.minimum:
            message = (
                f"The default maximum of the dimension '{self.name}' "
                f"({self.default_maximum}) is below its minimum ({self.minimum})"
            )
            raise ValueError(message)


class Size(Mapping[str, int]):
    """The size of an input: a non-negative integer for each dimension, in the order given.

    A size is immutable and hashable. Two sizes with the same values are equal
    whatever their order.

    Args:
        **values: The value of each dimension, by the name of the dimension.

    Raises:
        ValueError: If there is no value, a value is not an integer (a boolean
            is not), or a value is negative.
    """

    __slots__ = ("_values",)

    def __init__(self, /, **values: int) -> None:
        if not values:
            message = "A size needs at least one dimension"
            raise ValueError(message)
        for name, value in values.items():
            if not isinstance(value, int) or isinstance(value, bool):
                message = f"The dimension '{name}' must be an integer, got {value!r}"
                raise ValueError(message)  # noqa: TRY004  every rule of a size raises ValueError
            if value < 0:
                message = f"The dimension '{name}' must not be negative, got {value}"
                raise ValueError(message)
        self._values = dict(values)

    @override
    def __getitem__(self, name: str) -> int:
        return self._values[name]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    @override
    def __str__(self) -> str:
        return ":".join(f"{name}={value}" for name, value in self._values.items())

    @override
    def __repr__(self) -> str:
        listing = ", ".join(f"{name}={value}" for name, value in self._values.items())
        return f"Size({listing})"

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        return self._values == dict(other.items())

    @override
    def __hash__(self) -> int:
        return hash(frozenset(self._values.items()))

    @override
    def __reduce__(
        self,
    ) -> tuple[Callable[..., "Size"], tuple[tuple[tuple[str, int], ...]]]:
        return _rebuild_size, (tuple(self._values.items()),)


def _rebuild_size(items: tuple[tuple[str, int], ...]) -> Size:
    return Size(**dict(items))


def parse_plain_integer(digits: str) -> int | None:
    """Parse an integer written the way identifiers write it (``5``, not ``05``).

    Args:
        digits: The text to parse.

    Returns:
        The integer, or ``None`` when the text is not a plainly written integer.
        A minus sign is allowed.
    """
    try:
        value = int(digits)
    except ValueError:
        return None
    return value if str(value) == digits else None


def _describe_size_form(dimensions: Sequence[Dimension]) -> str:
    names = [dimension.name for dimension in dimensions]
    if len(names) == 1:
        return f"A size for the dimension {names[0]} is a plain number or {names[0]}=N"
    listing = ", ".join(names)
    form = ":".join(f"{name}=N" for name in names)
    return f"A size for the dimensions {listing} names each of them once, as {form}"


def parse_size(text: str, dimensions: Sequence[Dimension]) -> Size:
    """Parse the text of a size: ``name=N`` parts separated by colons.

    Each dimension appears exactly once, in any order. A bare integer stands
    for the only dimension of a problem that has just one.

    Args:
        text: The text of the size.
        dimensions: The dimensions of the problem, in declared order.

    Returns:
        The size, with its dimensions in declared order.

    Raises:
        CaseError: If a dimension is missing, unknown or repeated, or a value
            is not a plainly written, non-negative integer.
    """
    names = [dimension.name for dimension in dimensions]
    form = _describe_size_form(dimensions)
    parts = text.split(":")
    if len(names) == 1 and "=" not in text and ":" not in text:
        parts = [f"{names[0]}={text}"]
    values: dict[str, int] = {}
    for part in parts:
        label, separator, digits = part.partition("=")
        if not separator:
            message = f"{form}; got {text!r}"
            raise CaseError(message)
        if label not in names:
            message = (
                f"{form}; got {text!r}, which names the unknown dimension '{label}'"
            )
            raise CaseError(message)
        if label in values:
            message = f"The dimension '{label}' is named more than once in {text!r}"
            raise CaseError(message)
        value = parse_plain_integer(digits)
        if value is None:
            message = f"The dimension '{label}' in {text!r} is not valid: {PLAIN_INTEGER_RULE}"
            raise CaseError(message)
        if value < 0:
            message = f"The dimension '{label}' in {text!r} is negative"
            raise CaseError(message)
        values[label] = value
    missing = [name for name in names if name not in values]
    if missing:
        listing = ", ".join(f"'{name}'" for name in missing)
        message = f"{form}; got {text!r}, which lacks {listing}"
        raise CaseError(message)
    return Size(**{name: values[name] for name in names})


def build_minimum_size(problem: "AnyProblem") -> Size:
    """Build the smallest size of a problem: every dimension at its minimum.

    Args:
        problem: The problem.

    Returns:
        The size.
    """
    return Size(
        **{dimension.name: dimension.minimum for dimension in problem.dimensions}
    )


def build_default_maximum_size(problem: "AnyProblem") -> Size:
    """Build the default largest size of a problem: every dimension at its default maximum.

    Args:
        problem: The problem.

    Returns:
        The size.
    """
    return Size(
        **{
            dimension.name: dimension.default_maximum
            for dimension in problem.dimensions
        }
    )


def get_growth_dimension(problem: "AnyProblem") -> Dimension:
    """Return the dimension that benchmarks fit growth against.

    Args:
        problem: The problem.

    Returns:
        The dimension its ``growth_dimension`` names, else its first one.
    """
    if problem.growth_dimension is not None:
        for dimension in problem.dimensions:
            if dimension.name == problem.growth_dimension:
                return dimension
    return problem.dimensions[0]
