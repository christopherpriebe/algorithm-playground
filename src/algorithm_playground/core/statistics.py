"""Summary statistics for benchmark timing samples.

Reports `minimum`, `median`, `mean`, and `standard_deviation` over a list of
wall-time samples. Minimum is the headline metric: it filters out scheduling
noise and reflects the best achievable throughput on the host.
:func:`estimate_growth_exponent` fits a power law to a series of
measurements to say how the cost grows with the input size, and
:func:`estimate_growth` also names the best-fitting class (``n log n``).
"""

import math
import statistics as _statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = [
    "GROWTH_CLASSES",
    "MINIMUM_CLASS_SIZE",
    "MINIMUM_GROWTH_POINTS",
    "Growth",
    "TimingSummary",
    "estimate_growth",
    "estimate_growth_exponent",
    "fit_growth_class",
    "format_duration",
    "subtract_startup",
    "summarize",
]

MINIMUM_GROWTH_POINTS = 3
MINIMUM_CLASS_SIZE = 2

# The classes a measurement is compared with, from slowest-growing to fastest-growing, as
# (name, cost of an input of size n up to a constant factor).
GROWTH_CLASSES: tuple[tuple[str, Callable[[float], float]], ...] = (
    ("1", lambda size: 1.0),
    ("log n", math.log2),
    ("n", lambda size: size),
    ("n log n", lambda size: size * math.log2(size)),
    ("n^2", lambda size: size**2),
    ("n^3", lambda size: size**3),
)


def _require_equal_lengths(sizes: Sequence[float], values: Sequence[float]) -> None:
    if len(sizes) != len(values):
        raise ValueError(f"Got {len(sizes)} sizes but {len(values)} values")


def _squared_residual(
    points: Sequence[tuple[float, float]], cost: Callable[[float], float]
) -> float:
    """Sum the squared deviations of ``log(value) - log(cost(size))`` from their mean."""
    offsets = [log_value - math.log(cost(size)) for size, log_value in points]
    mean_offset = math.fsum(offsets) / len(offsets)
    return math.fsum((offset - mean_offset) ** 2 for offset in offsets)


@dataclass(frozen=True)
class TimingSummary:
    """Summary of a list of wall-time samples in seconds."""

    samples: tuple[float, ...]
    minimum: float
    median: float
    mean: float
    standard_deviation: float

    @property
    def count(self) -> int:
        """The number of samples."""
        return len(self.samples)


@dataclass(frozen=True)
class Growth:
    """How a cost grows with the input size: the fitted exponent and the nearest class.

    ``exponent`` is the ``k`` of ``cost ~ size ** k`` (see
    :func:`estimate_growth_exponent`). ``growth_class`` is the best fit among
    ``1``, ``log n``, ``n``, ``n log n``, ``n^2`` and ``n^3``, or ``None`` when
    too few points had a size of at least 2 to compare them.
    """

    exponent: float
    growth_class: str | None = None

    def describe(self) -> str:
        """Write the growth for people.

        Returns:
            ``~ n log n (n^1.21)``, or ``n^1.21`` without a class.
        """
        fitted = f"n^{self.exponent:.2f}"
        if self.growth_class is None:
            return fitted
        return f"~ {self.growth_class} ({fitted})"


def summarize(samples: list[float]) -> TimingSummary:
    """Compute the headline statistics over ``samples``.

    Args:
        samples: Wall times in seconds.

    Returns:
        The sorted samples with their minimum, median, mean and standard deviation.

    Raises:
        ValueError: If ``samples`` is empty.
    """
    if not samples:
        raise ValueError("Cannot summarize an empty sample list")
    sorted_samples = tuple(sorted(samples))
    return TimingSummary(
        samples=sorted_samples,
        minimum=sorted_samples[0],
        median=_statistics.median(sorted_samples),
        mean=_statistics.fmean(sorted_samples),
        standard_deviation=_statistics.pstdev(sorted_samples) if len(sorted_samples) > 1 else 0.0,
    )


def subtract_startup(samples: list[float], startup_seconds: float) -> list[float]:
    """Remove the startup time from every sample.

    Results are not clamped: a sample that comes out negative is faster than
    the average startup run, meaning the work is below the noise floor of
    the measurement.

    Args:
        samples: Wall times in seconds.
        startup_seconds: The startup time to subtract from each sample.

    Returns:
        The samples minus ``startup_seconds``, in the same order.
    """
    return [sample - startup_seconds for sample in samples]


def estimate_growth_exponent(sizes: Sequence[float], values: Sequence[float]) -> float | None:
    """Estimate ``k`` in ``value ~ size ** k`` by least squares on log-log axes.

    Only points with a positive size and a positive value take part, since
    the logarithm of anything else is undefined. Linear work gives about
    ``1``, quadratic work about ``2``.

    Args:
        sizes: The input sizes.
        values: The cost measured at each size, in the order of ``sizes``.

    Returns:
        The exponent, or ``None`` when fewer than three points remain or they
        all share one size.

    Raises:
        ValueError: If ``sizes`` and ``values`` differ in length.
    """
    _require_equal_lengths(sizes, values)
    points = [
        (math.log(size), math.log(value))
        for size, value in zip(sizes, values, strict=True)
        if size > 0 and value > 0
    ]
    if len(points) < MINIMUM_GROWTH_POINTS or len({log_size for log_size, _ in points}) < 2:
        return None
    mean_log_size = math.fsum(log_size for log_size, _ in points) / len(points)
    mean_log_value = math.fsum(log_value for _, log_value in points) / len(points)
    spread = math.fsum((log_size - mean_log_size) ** 2 for log_size, _ in points)
    covariance = math.fsum(
        (log_size - mean_log_size) * (log_value - mean_log_value) for log_size, log_value in points
    )
    return covariance / spread


def estimate_growth(sizes: Sequence[float], values: Sequence[float]) -> Growth | None:
    """Estimate the exponent and the class of the growth of ``values`` with ``sizes``.

    The exponent is :func:`estimate_growth_exponent`. The class is the one of
    :func:`fit_growth_class`.

    Args:
        sizes: The input sizes.
        values: The cost measured at each size, in the order of ``sizes``.

    Returns:
        The growth, or ``None`` when there is no exponent.

    Raises:
        ValueError: If ``sizes`` and ``values`` differ in length.
    """
    exponent = estimate_growth_exponent(sizes, values)
    if exponent is None:
        return None
    return Growth(exponent, fit_growth_class(sizes, values))


def fit_growth_class(sizes: Sequence[float], values: Sequence[float]) -> str | None:
    """Find the class among ``1``, ``log n``, ``n``, ``n log n``, ``n^2`` and ``n^3`` that fits best.

    Each class is fitted as ``value ~ constant * f(size)`` by least squares on
    the logarithms, which treats a factor of two the same wherever it occurs in
    the series, and the class with the smallest sum of squared residuals wins
    (the slower-growing one when they tie). Only points with a size of at least
    2 and a positive value take part.

    Args:
        sizes: The input sizes.
        values: The cost measured at each size, in the order of ``sizes``.

    Returns:
        The name of the best class, or ``None`` unless three points with two
        different sizes take part.

    Raises:
        ValueError: If ``sizes`` and ``values`` differ in length.
    """
    _require_equal_lengths(sizes, values)
    points = [
        (size, math.log(value))
        for size, value in zip(sizes, values, strict=True)
        if size >= MINIMUM_CLASS_SIZE and value > 0
    ]
    if len(points) < MINIMUM_GROWTH_POINTS or len({size for size, _ in points}) < 2:
        return None
    best_name, best_residual = None, math.inf
    for name, cost in GROWTH_CLASSES:
        residual = _squared_residual(points, cost)
        if residual < best_residual:
            best_name, best_residual = name, residual
    return best_name


def format_duration(seconds: float) -> str:
    """Format ``seconds`` as a human-friendly fixed-unit string.

    Args:
        seconds: The duration, which may be negative.

    Returns:
        The duration in seconds, milliseconds, microseconds or nanoseconds,
        whichever keeps the number at or above one.
    """
    sign = "-" if seconds < 0 else ""
    magnitude = abs(seconds)
    if magnitude >= 1.0:
        return f"{sign}{magnitude:.3f} s"
    elif magnitude >= 1e-3:
        return f"{sign}{magnitude * 1e3:.3f} ms"
    elif magnitude >= 1e-6:
        return f"{sign}{magnitude * 1e6:.3f} us"
    else:
        return f"{sign}{magnitude * 1e9:.3f} ns"
