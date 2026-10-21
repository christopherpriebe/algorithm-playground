"""The binary format of sorting inputs and outputs.

Both files hold ``u64 count`` followed by ``count`` little-endian ``i32``
values; see :doc:`/problems/sorting` for the full contract.
"""

from __future__ import annotations

from pathlib import Path

from algorithm_playground.core.binary_format import (
    expect_end_of_stream,
    read_i32_array,
    read_u64,
    write_i32_array,
    write_u64,
)

I32_MIN = -(2**31)
I32_MAX = 2**31 - 1


def write_values(values: list[int], path: Path) -> None:
    """Write ``values`` to ``path`` as an input file; reject values outside the i32 range."""
    with path.open("wb") as stream:
        write_u64(stream, len(values))
        write_i32_array(stream, values)


def read_values(path: Path, what: str = "The file") -> list[int]:
    """Read a file of values; raise :class:`BinaryFormatError` unless it matches its header exactly.

    ``what`` names the file in the error message, for example ``"The output file"``.
    """
    with path.open("rb") as stream:
        values = read_i32_array(stream, read_u64(stream))
        expect_end_of_stream(stream, what)
    return values
