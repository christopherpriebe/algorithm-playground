"""Input types that compare badly, to test how the harness copes with them.

Every one is a list of integers, so the sorting problem's hooks can still
serialize it, with equality that raises, that cannot be judged, or that holds
only for the object itself.
"""

from typing_extensions import override


class AmbiguousTruth:
    """The result of a comparison that cannot be judged true or false, like an array's."""

    def __bool__(self) -> bool:
        message = "the truth value of a comparison is ambiguous"
        raise ValueError(message)


class UnequatableValues(list[int]):
    """A list of values whose comparison raises, like an input type that forgot equality."""

    @override
    def __eq__(self, other: object) -> bool:
        message = "no equality here"
        raise TypeError(message)

    @override
    def __ne__(self, other: object) -> bool:
        message = "no equality here"
        raise TypeError(message)

    __hash__ = None


class AmbiguousValues(list[int]):
    """A list of values whose comparison cannot be judged, like an array compared element-wise."""

    @override
    def __eq__(self, other: object) -> bool:
        return AmbiguousTruth()  # ty: ignore[invalid-return-type]  deliberately a non-boolean, as array types return

    @override
    def __ne__(self, other: object) -> bool:
        return AmbiguousTruth()  # ty: ignore[invalid-return-type]  deliberately a non-boolean, as array types return

    __hash__ = None


class IdentityValues(list[int]):
    """A list of values equal only to itself, like an input type without value equality."""

    @override
    def __eq__(self, other: object) -> bool:
        return self is other

    @override
    def __ne__(self, other: object) -> bool:
        return self is not other

    __hash__ = None
