"""Summary statistics for benchmark timing samples.

Reports `minimum`, `median`, `mean`, and `standard_deviation` over a list of
wall-time samples. Minimum is the headline metric: it filters out scheduling
noise and reflects the best achievable throughput on the host.
"""

from __future__ import annotations

import statistics as _statistics
from dataclasses import dataclass


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


def subtract_baseline(samples: list[float], baseline_seconds: float) -> list[float]:
    """Return ``samples`` with ``baseline_seconds`` removed from each one.

    Results are not clamped: a sample that comes out negative is faster than
    the average baseline run, meaning the work is below the noise floor of
    the measurement.
    """
    return [sample - baseline_seconds for sample in samples]


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
