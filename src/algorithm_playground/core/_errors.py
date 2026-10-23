"""The base class of the exceptions that the package raises."""

__all__ = ["AlgorithmPlaygroundError", "CaseError"]


class AlgorithmPlaygroundError(Exception):
    """Base class of every exception class that algorithm-playground defines.

    Each of them also derives from the built-in exception that fits it, such as
    :class:`ValueError` for input that cannot be used or :class:`RuntimeError` for
    a failure while running, so a caller can catch either one. An invalid argument
    to a function (a negative size, a value out of range) is still a plain
    :class:`ValueError` or :class:`TypeError`.
    """


class CaseError(AlgorithmPlaygroundError, ValueError):
    """Raised when a case identifier, a size or a case plan cannot be turned into cases."""
