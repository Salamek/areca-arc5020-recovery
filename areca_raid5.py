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
    parse_volume_selector,
    raid5_row_layout,
    xor_blocks,
)

row_layout = raid5_row_layout


def validate_members(
    paths: list[str], volume: int | str | None = None
) -> ArecaArray:
    array = ArecaArray.assemble(paths, volume=volume)
    if array.level != RaidLevel.RAID5:
        raise ArecaError(f"expected RAID5, detected {array.level.value}")
    return array


def reconstruct(
    paths: list[str],
    output: str,
    byte_count: int | None,
    volume: int | str | None = None,
) -> int:
    return validate_members(paths, volume).reconstruct(output, byte_count)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("output")
    top.add_argument("members", nargs="+")
    top.add_argument("--bytes", type=parse_size)
    top.add_argument("--volume", type=parse_volume_selector)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        length = reconstruct(args.members, args.output, args.bytes, args.volume)
        print(f"reconstructed {length} bytes into {args.output}")
    except (ArecaError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
