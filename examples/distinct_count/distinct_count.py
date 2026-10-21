#!/usr/bin/env python3
"""Reference implementation of the distinct-count executable contract.

Usage: distinct_count.py <input.bin> <output.bin>
"""

import struct
import sys
from pathlib import Path


def main(arguments: list[str]) -> int:
    """Count the distinct values of the input file and write the count.

    Args:
        arguments: The command line, starting with the script name.

    Returns:
        The exit status: 0 on success, 2 for a wrong number of arguments.
    """
    if len(arguments) < 3:
        print("usage: distinct_count.py <input.bin> <output.bin>", file=sys.stderr)
        return 2
    raw = Path(arguments[1]).read_bytes()
    (count,) = struct.unpack_from("<Q", raw)
    values = struct.unpack_from(f"<{count}i", raw, 8)
    Path(arguments[2]).write_bytes(struct.pack("<Q", len(set(values))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
