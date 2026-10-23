"""Sizes of a problem with one dimension called ``size``, the common case in the suite."""

from algorithm_playground.core import Size


def build_sizes(*values: int) -> tuple[Size, ...]:
    """Build one size per value for a problem whose only dimension is ``size``.

    Args:
        *values: The value of the dimension in each size.

    Returns:
        The sizes, in the order of the values.
    """
    return tuple(Size(size=value) for value in values)
