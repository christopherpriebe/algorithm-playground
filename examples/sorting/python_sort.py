#!/usr/bin/env python3
"""Reference Python implementation of the sorting executable contract.

Reads a binary array of int32 values from ``input_path``, sorts it with the
built-in ``sorted``, and writes the result to ``output_path``. When a third
argument ``trace_path`` is supplied, it also writes a state-snapshot trace
(kind ``0``) holding two snapshots: the input and the sorted output. The
built-in sort exposes no intermediate states, so this only demonstrates the
trace format; an algorithm you write yourself would record a snapshot after
each step.
"""

import struct
import sys
from pathlib import Path

USAGE = "usage: python_sort.py <input.bin> <output.bin> [<trace.bin>]"
SNAPSHOT_TRACE_KIND = 0
HEADER_BYTES = 8  # the u64 element count
ELEMENT_BYTES = 4  # one i32 value
TRACE_ARGUMENT_COUNT = 4  # the script name, input, output and trace paths


def _encode_array(values: list[int]) -> bytes:
    return struct.pack(f"<Q{len(values)}i", len(values), *values)


def read_input(path: Path) -> list[int]:
    """Read an input file.

    Args:
        path: The file holding ``u64 count`` and then ``count`` i32 values.

    Returns:
        The values.

    Raises:
        ValueError: If the file is too small or its size does not match its count.
    """
    raw = path.read_bytes()
    if len(raw) < HEADER_BYTES:
        message = "Input file is too small to contain a u64 count."
        raise ValueError(message)
    (count,) = struct.unpack_from("<Q", raw, 0)
    expected_bytes = HEADER_BYTES + ELEMENT_BYTES * count
    if len(raw) != expected_bytes:
        message = (
            f"Input file size mismatch: header declares {count} elements "
            f"({expected_bytes} bytes), file is {len(raw)} bytes."
        )
        raise ValueError(message)
    return list(struct.unpack_from(f"<{count}i", raw, HEADER_BYTES))


def write_output(path: Path, values: list[int]) -> None:
    """Write the sorted values in the same format as the input.

    Args:
        path: The output file.
        values: The sorted values.
    """
    path.write_bytes(_encode_array(values))


def write_trace(path: Path, snapshots: list[list[int]]) -> None:
    """Write a state-snapshot trace (kind ``0``).

    Args:
        path: The trace file.
        snapshots: The array after each step.
    """
    buffer = bytearray(struct.pack("<II", SNAPSHOT_TRACE_KIND, len(snapshots)))
    for snapshot in snapshots:
        buffer.extend(_encode_array(snapshot))
    path.write_bytes(bytes(buffer))


def main(arguments: list[str]) -> int:
    """Sort the input file and write the output and, if asked, the trace.

    Args:
        arguments: The command line, starting with the script name.

    Returns:
        The exit status: 0 on success, 2 for a wrong number of arguments.
    """
    if len(arguments) not in (TRACE_ARGUMENT_COUNT - 1, TRACE_ARGUMENT_COUNT):
        print(USAGE, file=sys.stderr)
        return 2

    input_path = Path(arguments[1])
    output_path = Path(arguments[2])
    trace_path = Path(arguments[3]) if len(arguments) == TRACE_ARGUMENT_COUNT else None

    values = read_input(input_path)
    sorted_values = sorted(values)
    write_output(output_path, sorted_values)
    if trace_path is not None:
        write_trace(trace_path, [values, sorted_values])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
