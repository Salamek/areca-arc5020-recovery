#!/usr/bin/env python3
"""Compatibility CLI for ARC-5020 four-member RAID1+0 reconstruction."""

from __future__ import annotations

import argparse
import subprocess
import sys

from areca import ArecaArray, ArecaError, RaidLevel, parse_size


def validate_members(paths: list[str]) -> ArecaArray:
    array = ArecaArray.assemble(paths)
    if array.level != RaidLevel.RAID10:
        raise ArecaError(f"expected RAID1+0, detected {array.level.value}")
    return array


def reconstruct(paths: list[str], output: str, byte_count: int | None) -> int:
    return validate_members(paths).reconstruct(output, byte_count)


def dm_table(paths: list[str]) -> tuple[ArecaArray, str]:
    array = validate_members(paths)
    return array, array.dm_table()


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    image = commands.add_parser("reconstruct", help="create a reconstructed image")
    image.add_argument("output")
    image.add_argument("members", nargs="+")
    image.add_argument("--bytes", type=parse_size)
    table = commands.add_parser("dm-table", help="print a dmsetup table")
    table.add_argument("members", nargs="+")
    create = commands.add_parser("create-dm", help="create a read-only dm mapping")
    create.add_argument("name")
    create.add_argument("members", nargs="+")
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "reconstruct":
            length = reconstruct(args.members, args.output, args.bytes)
            print(f"reconstructed {length} bytes into {args.output}")
        else:
            array, table = dm_table(args.members)
            print(f"selected member indices: {array.supplied_indices}", file=sys.stderr)
            if args.command == "dm-table":
                print(table)
            else:
                subprocess.run(
                    ["dmsetup", "create", args.name, "--readonly", "--table", table],
                    check=True,
                )
                print(f"/dev/mapper/{args.name}")
    except (ArecaError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
