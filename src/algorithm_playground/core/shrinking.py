"""Building blocks for a problem's ``shrink`` hook.

Shrinking turns a failing input into a smaller or simpler one that still fails.
The harness drives the search (see :func:`~algorithm_playground.core.testing.run_tests`);
a problem only lists the candidates, most aggressive first. These functions
cover the usual shapes of input so that a problem composes its ``shrink`` from
them instead of rewriting them:

* :func:`shrink_sequence` removes elements, :func:`shrink_integers` makes the
  numbers of a sequence simpler, :func:`shrink_integer_sequence` does both (the
  usual shrinker for an array of numbers), and :func:`shrink_each` shrinks every
  element of a sequence on its own;
* :func:`shrink_integer` simplifies one number;
* :func:`shrink_fields` applies a shrinker to each field of a dataclass or a
  tuple, which is how an input made of several parts is shrunk part by part;
* :func:`distinct` drops candidates that were already tried.

A candidate may break a rule that the input must keep (an array that has to be
sorted, a graph whose edges must name existing vertices). The problem's
``check_input`` hook reports that, and the harness skips such candidates, so a
shrinker can be generous and a validity rule is written once.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass, replace
from itertools import chain
from typing import Any, NamedTuple, TypeVar, cast

__all__ = [
    "Shrinker",
    "distinct",
    "shrink_each",
    "shrink_fields",
    "shrink_integer",
    "shrink_integer_sequence",
    "shrink_integers",
    "shrink_sequence",
]

CandidateT = TypeVar("CandidateT")
ValueT = TypeVar("ValueT")
SequenceT = TypeVar("SequenceT", bound=Sequence[object])
IntegerSequenceT = TypeVar("IntegerSequenceT", bound=Sequence[int])

# Turns a value of one type into simpler candidates of that type. The type differs for each
# element or field that a caller shrinks, so it cannot be spelled out here.
Shrinker = Callable[[Any], Iterable[Any]]


def _same_type(original: SequenceT, items: Sequence[object]) -> SequenceT:
    if isinstance(original, list):
        return cast(SequenceT, items)
    elif isinstance(original, tuple) and not hasattr(original, "_fields"):
        return cast(SequenceT, tuple(items))
    else:
        raise TypeError(f"Only a list or a tuple can be shrunk, got {type(original).__name__}")


def _get_field(value: object, field: str | int) -> object:
    if isinstance(field, int):
        return cast(Sequence[object], value)[field]
    else:
        return getattr(value, field)


def _with_field(value: ValueT, field: str | int, replacement: object) -> ValueT:
    if is_dataclass(value) and not isinstance(value, type):
        if not isinstance(field, str) or field not in {item.name for item in fields(value)}:
            raise TypeError(f"{type(value).__name__} has no dataclass field {field!r}")
        return replace(value, **{field: replacement})
    elif isinstance(value, tuple) and hasattr(value, "_replace") and isinstance(field, str):
        return cast(ValueT, cast(NamedTuple, value)._replace(**{field: replacement}))
    elif isinstance(value, tuple) and isinstance(field, int):
        return cast(ValueT, (*value[:field], replacement, *value[field + 1 :]))
    else:
        raise TypeError(
            "Fields can be shrunk in a dataclass, a named tuple or a tuple, "
            f"got {type(value).__name__}"
        )


def shrink_sequence(values: SequenceT, *, minimum_length: int = 0) -> Iterator[SequenceT]:
    """Yield a sequence with a chunk of elements removed, the largest chunks first.

    The halves come first, then smaller chunks down to single elements, so a
    failure that needs only a few elements is found in a handful of runs.

    Args:
        values: The list or tuple to shrink.
        minimum_length: The fewest elements a candidate may have.

    Yields:
        Candidates of the type of ``values`` (a list stays a list, a tuple a
        tuple).

    Raises:
        TypeError: If ``values`` is neither a list nor a tuple (a named tuple
            counts as neither).
    """
    count = len(values)
    chunk = max(count // 2, 1) if count else 0
    while chunk >= 1:
        for start in range(0, count, chunk):
            kept = [*values[:start], *values[start + chunk :]]
            if len(kept) >= minimum_length:
                yield _same_type(values, kept)
        chunk //= 2


def shrink_integer(value: int) -> Iterator[int]:
    """Yield simpler integers for a number: zero, then half of it.

    Args:
        value: The number to simplify.

    Yields:
        ``0`` and then ``value`` halved (rounded toward zero), each only when
        it differs from ``value`` and from the earlier candidate. Nothing for
        ``0``.
    """
    if value == 0:
        return
    yield 0
    half = value // 2 if value > 0 else -(-value // 2)
    if half not in (0, value):
        yield half


def shrink_each(values: SequenceT, shrink_element: Shrinker) -> Iterator[SequenceT]:
    """Yield a sequence with one element replaced by each candidate for that element.

    Elements are taken in order. The length stays the same.

    Args:
        values: The list or tuple to shrink.
        shrink_element: Returns the simpler candidates for one element.

    Yields:
        Candidates of the type of ``values``.

    Raises:
        TypeError: If ``values`` is neither a list nor a tuple.
    """
    for position, element in enumerate(values):
        for simpler in shrink_element(element):
            yield _same_type(values, [*values[:position], simpler, *values[position + 1 :]])


def shrink_integers(values: IntegerSequenceT) -> Iterator[IntegerSequenceT]:
    """Yield a sequence of integers with simpler numbers, most aggressive first.

    First every number becomes ``0``, then every number is replaced by its rank
    among the distinct numbers (which keeps their order but makes them small),
    then one number at a time becomes ``0`` or half of itself.

    Args:
        values: The list or tuple of integers to shrink.

    Yields:
        Candidates of the type of ``values``. A candidate equal to ``values``
        is not yielded.

    Raises:
        TypeError: If ``values`` is neither a list nor a tuple.
    """
    if any(values):
        yield _same_type(values, [0] * len(values))
    ranks = {value: rank for rank, value in enumerate(sorted(set(values)))}
    ranked = [ranks[value] for value in values]
    if ranked != list(values):
        yield _same_type(values, ranked)
    yield from shrink_each(values, shrink_integer)


def shrink_integer_sequence(values: IntegerSequenceT) -> Iterator[IntegerSequenceT]:
    """Yield smaller or simpler versions of a sequence of integers, most aggressive first.

    First elements are removed (:func:`shrink_sequence`), then the numbers are
    made simpler (:func:`shrink_integers`). It is the whole ``shrink`` hook of a
    problem whose input is an array of numbers.

    Args:
        values: The list or tuple of integers to shrink.

    Yields:
        Candidates of the type of ``values``. No candidate repeats an earlier
        one or equals ``values``.

    Raises:
        TypeError: If ``values`` is neither a list nor a tuple.
    """
    return distinct(chain(shrink_sequence(values), shrink_integers(values)), values)


def shrink_fields(value: ValueT, shrinkers: Mapping[str | int, Shrinker]) -> Iterator[ValueT]:
    """Yield a value with one field replaced by each candidate for that field.

    ``shrinkers`` maps each field to a function from the field's value to its
    candidates, for example ``{"values": shrink_sequence, "target":
    shrink_integer}``. Fields are visited in the order of the mapping, so put
    the most aggressive first. A field that is not named is left alone.

    Args:
        value: A dataclass instance (name the fields), a named tuple (name the
            fields) or a plain tuple (give positions).
        shrinkers: The shrinker of each field to shrink.

    Yields:
        Copies of ``value`` with one field replaced.

    Raises:
        TypeError: If ``value`` is not a dataclass instance or a tuple, or a
            dataclass has no field of a given name.
    """
    for field, shrink_field in shrinkers.items():
        for candidate in shrink_field(_get_field(value, field)):
            yield _with_field(value, field, candidate)


def distinct(candidates: Iterable[CandidateT], *excluded: CandidateT) -> Iterator[CandidateT]:
    """Yield each candidate once, skipping those equal to an excluded value.

    Candidates are compared by their ``repr``.

    Args:
        candidates: The candidates, in the order to try them.
        *excluded: Values never to yield, usually the input being shrunk.

    Yields:
        The candidates not seen before and not excluded, in their order.
    """
    seen = {repr(candidate) for candidate in excluded}
    for candidate in candidates:
        key = repr(candidate)
        if key not in seen:
            seen.add(key)
            yield candidate
