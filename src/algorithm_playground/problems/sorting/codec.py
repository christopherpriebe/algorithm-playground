"""The binary format of sorting inputs and outputs.

Both files hold ``u64 count`` followed by ``count`` little-endian ``i32``
values; see :doc:`/problems/sorting` for the full contract.
"""

from pathlib import Path

from algorithm_playground.core.binary_format import (
    expect_end_of_stream,
    read_i32_array,
    read_u64,
    write_i32_array,
    write_u64,
)

__all__ = ["I32_MAX", "I32_MIN", "read_values", "write_values"]

I32_MIN = -(2**31)
I32_MAX = 2**31 - 1


def write_values(values: list[int], path: Path) -> None:
    """Write ``values`` to ``path`` as an input file.

    Args:
        values: The values to write, each within the i32 range.
        path: The file to create or overwrite.

    Raises:
        ValueError: If a value is outside the i32 range.
    """
    with path.open("wb") as stream:
        write_u64(stream, len(values))
        write_i32_array(stream, values)


def read_values(path: Path, what: str = "The file") -> list[int]:
    """Read a file of values.

    Args:
        path: The file to read.
        what: How the file is named in an error message, for example
            ``"The output file"``.

    Returns:
        The values in the file.

    Raises:
        algorithm_playground.core.binary_format.BinaryFormatError: If the file does not match its header exactly.
    """
    with path.open("rb") as stream:
        values = read_i32_array(stream, read_u64(stream))
        expect_end_of_stream(stream, what)
    return values
