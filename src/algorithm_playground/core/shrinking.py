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

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass, replace
from itertools import chain
from typing import Any, TypeVar, cast

T = TypeVar("T")
SequenceT = TypeVar("SequenceT", bound=Sequence[Any])


def shrink_sequence(values: SequenceT, *, minimum_length: int = 0) -> Iterator[SequenceT]:
    """Yield ``values`` with a chunk of elements removed, the largest chunks first.

    The halves come first, then smaller chunks down to single elements, so a
    failure that needs only a few elements is found in a handful of runs. The
    result has the type of ``values`` (a list stays a list, a tuple a tuple) and
    never has fewer than ``minimum_length`` elements.
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
    """Yield simpler integers for ``value``: zero, then half of it (rounded toward zero)."""
    if value == 0:
        return
    yield 0
    half = value // 2 if value > 0 else -(-value // 2)
    if half not in (0, value):
        yield half


def shrink_each(
    values: SequenceT, shrink_element: Callable[[Any], Iterable[Any]]
) -> Iterator[SequenceT]:
    """Yield ``values`` with one element replaced by each candidate of ``shrink_element``.

    Elements are taken in order. The length stays the same.
    """
    for position, element in enumerate(values):
        for simpler in shrink_element(element):
            yield _same_type(values, [*values[:position], simpler, *values[position + 1 :]])


def shrink_integers(values: SequenceT) -> Iterator[SequenceT]:
    """Yield versions of a sequence of integers with simpler numbers, most aggressive first.

    First every number becomes ``0``, then every number is replaced by its rank
    among the distinct numbers (which keeps their order but makes them small),
    then one number at a time becomes ``0`` or half of itself. A candidate equal
    to ``values`` is not yielded.
    """
    if any(values):
        yield _same_type(values, [0] * len(values))
    ranks = {value: rank for rank, value in enumerate(sorted(set(values)))}
    ranked = [ranks[value] for value in values]
    if ranked != list(values):
        yield _same_type(values, ranked)
    yield from shrink_each(values, shrink_integer)


def shrink_integer_sequence(values: SequenceT) -> Iterator[SequenceT]:
    """Yield smaller or simpler versions of a sequence of integers, most aggressive first.

    First elements are removed (:func:`shrink_sequence`), then the numbers are
    made simpler (:func:`shrink_integers`). No candidate repeats an earlier one
    or equals ``values``. It is the whole ``shrink`` hook of a problem whose
    input is an array of numbers.
    """
    return distinct(chain(shrink_sequence(values), shrink_integers(values)), values)


def shrink_fields(
    value: T, shrinkers: Mapping[str | int, Callable[[Any], Iterable[Any]]]
) -> Iterator[T]:
    """Yield ``value`` with one field replaced by each candidate of that field's shrinker.

    ``value`` is a dataclass instance (name the fields), a named tuple (name the
    fields) or a plain tuple (give positions). ``shrinkers`` maps each field to
    a function from the field's value to its candidates, for example
    ``{"values": shrink_sequence, "target": shrink_integer}``. Fields are
    visited in the order of the mapping, so put the most aggressive first. A
    field that is not named is left alone.
    """
    for field, shrink_field in shrinkers.items():
        for candidate in shrink_field(_get_field(value, field)):
            yield _with_field(value, field, candidate)


def distinct(candidates: Iterable[T], *excluded: T) -> Iterator[T]:
    """Yield each candidate once, skipping any equal to one of ``excluded`` (usually the input)."""
    seen = {repr(candidate) for candidate in excluded}
    for candidate in candidates:
        key = repr(candidate)
        if key not in seen:
            seen.add(key)
            yield candidate


def _same_type(original: SequenceT, items: list[Any]) -> SequenceT:
    if isinstance(original, list):
        return cast(SequenceT, items)
    if isinstance(original, tuple) and not hasattr(original, "_fields"):
        return cast(SequenceT, tuple(items))
    raise TypeError(f"Only a list or a tuple can be shrunk, got {type(original).__name__}")


def _get_field(value: Any, field: str | int) -> Any:
    if isinstance(field, int):
        return value[field]
    return getattr(value, field)


def _with_field(value: Any, field: str | int, replacement: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        if not isinstance(field, str) or field not in {item.name for item in fields(value)}:
            raise TypeError(f"{type(value).__name__} has no dataclass field {field!r}")
        return replace(value, **{field: replacement})
    if isinstance(value, tuple) and hasattr(value, "_replace") and isinstance(field, str):
        return value._replace(**{field: replacement})
    if isinstance(value, tuple) and isinstance(field, int):
        return (*value[:field], replacement, *value[field + 1 :])
    raise TypeError(
        f"Fields can be shrunk in a dataclass, a named tuple or a tuple, got {type(value).__name__}"
    )
