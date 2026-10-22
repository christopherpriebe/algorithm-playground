"""Helpers that write and decode sorting traces in tests."""

from pathlib import Path

from algorithm_playground.problems.sorting import SortingTrace, read_trace


def write_trace(directory: Path, content: bytes) -> Path:
    """Write ``content`` to a trace file in ``directory`` and return its path."""
    path = directory / "trace.bin"
    path.write_bytes(content)
    return path


def decode_trace(
    directory: Path, content: bytes, input_values: list[int] | None = None
) -> SortingTrace:
    """Write ``content`` as a trace file and decode it, asserting that it decodes.

    Args:
        directory: The directory that receives the trace file.
        content: The bytes of the trace file.
        input_values: The input the trace belongs to (default: empty).

    Returns:
        The decoded trace.
    """
    trace = read_trace(write_trace(directory, content), input_values or [])
    assert trace is not None
    return trace
