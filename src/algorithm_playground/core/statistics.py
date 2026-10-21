"""Summary statistics for benchmark timing samples.

Reports `minimum`, `median`, `mean`, and `standard_deviation` over a list of
wall-time samples. Minimum is the headline metric: it filters out scheduling
noise and reflects the best achievable throughput on the host.
:func:`estimate_growth_exponent` fits a power law to a series of
measurements to say how the cost grows with the input size, and
:func:`estimate_growth` also names the best-fitting class (``n log n``).
"""

from __future__ import annotations

import math
import statistics as _statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

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
        return len(self.samples)


def summarize(samples: list[float]) -> TimingSummary:
    """Compute the headline statistics over ``samples`` (seconds)."""
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
    """Return ``samples`` with ``startup_seconds`` removed from each one.

    Results are not clamped: a sample that comes out negative is faster than
    the average startup run, meaning the work is below the noise floor of
    the measurement.
    """
    return [sample - startup_seconds for sample in samples]


def estimate_growth_exponent(sizes: Sequence[float], values: Sequence[float]) -> float | None:
    """Estimate ``k`` in ``value ~ size ** k`` by least squares on log-log axes.

    Only points with a positive size and a positive value take part, since
    the logarithm of anything else is undefined. Return ``None`` when fewer
    than three such points remain or when they all share one size. Linear
    work gives about ``1``, quadratic work about ``2``.
    """
    if len(sizes) != len(values):
        raise ValueError(f"Got {len(sizes)} sizes but {len(values)} values")
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
        """Write it for people: ``~ n log n (n^1.21)``, or ``n^1.21`` without a class."""
        fitted = f"n^{self.exponent:.2f}"
        return fitted if self.growth_class is None else f"~ {self.growth_class} ({fitted})"


def estimate_growth(sizes: Sequence[float], values: Sequence[float]) -> Growth | None:
    """Estimate the exponent and the class of the growth of ``values`` with ``sizes``.

    The exponent is :func:`estimate_growth_exponent`; ``None`` when there is
    none. The class is the one of :func:`fit_growth_class`.
    """
    exponent = estimate_growth_exponent(sizes, values)
    if exponent is None:
        return None
    return Growth(exponent, fit_growth_class(sizes, values))


def fit_growth_class(sizes: Sequence[float], values: Sequence[float]) -> str | None:
    """Return the class among ``1``, ``log n``, ``n``, ``n log n``, ``n^2`` and ``n^3`` that fits best.

    Each class is fitted as ``value ~ constant * f(size)`` by least squares on
    the logarithms, which treats a factor of two the same wherever it occurs in
    the series, and the class with the smallest sum of squared residuals wins
    (the slower-growing one when they tie). Only points with a size of at least
    2 and a positive value take part, and there must be three of them with
    two different sizes; otherwise return ``None``.
    """
    if len(sizes) != len(values):
        raise ValueError(f"Got {len(sizes)} sizes but {len(values)} values")
    points = [
        (size, math.log(value))
        for size, value in zip(sizes, values, strict=True)
        if size >= MINIMUM_CLASS_SIZE and value > 0
    ]
    if len(points) < MINIMUM_GROWTH_POINTS or len({size for size, _ in points}) < 2:
        return None
    best_name, best_residual = None, math.inf
    for name, cost in GROWTH_CLASSES:
        offsets = [log_value - math.log(cost(size)) for size, log_value in points]
        mean_offset = math.fsum(offsets) / len(offsets)
        residual = math.fsum((offset - mean_offset) ** 2 for offset in offsets)
        if residual < best_residual:
            best_name, best_residual = name, residual
    return best_name


def format_duration(seconds: float) -> str:
    """Format ``seconds`` as a human-friendly fixed-unit string."""
    sign = "-" if seconds < 0 else ""
    magnitude = abs(seconds)
    if magnitude >= 1.0:
        return f"{sign}{magnitude:.3f} s"
    if magnitude >= 1e-3:
        return f"{sign}{magnitude * 1e3:.3f} ms"
    if magnitude >= 1e-6:
        return f"{sign}{magnitude * 1e6:.3f} us"
    return f"{sign}{magnitude * 1e9:.3f} ns"
