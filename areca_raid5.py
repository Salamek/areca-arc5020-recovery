#!/usr/bin/env python3
"""Compatibility CLI for ARC-5020 RAID5 image reconstruction."""

from __future__ import annotations

import argparse
import sys

from areca import (
    ArecaArray,
    ArecaError,
    RaidLevel,
    parse_size,
    raid5_row_layout,
    xor_blocks,
)

row_layout = raid5_row_layout


def validate_members(paths: list[str]) -> ArecaArray:
    array = ArecaArray.assemble(paths)
    if array.level != RaidLevel.RAID5:
        raise ArecaError(f"expected RAID5, detected {array.level.value}")
    return array


def reconstruct(paths: list[str], output: str, byte_count: int | None) -> int:
    return validate_members(paths).reconstruct(output, byte_count)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("output")
    top.add_argument("members", nargs="+")
    top.add_argument("--bytes", type=parse_size)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        length = reconstruct(args.members, args.output, args.bytes)
        print(f"reconstructed {length} bytes into {args.output}")
    except (ArecaError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
