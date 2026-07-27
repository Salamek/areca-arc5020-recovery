#!/usr/bin/env python3
"""Reconstruct the observed ARC-5020 four-member RAID 1+0 layout.

The validated layout has adjacent mirror pairs (indices 0+1 and 2+3),
64 KiB stripes, and member data beginning at LBA 520.  Inputs are always
opened read-only.  Ambiguous or inconsistent member sets are rejected.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass

from areca_member import ArecaError, Inspection, inspect
from raid_pattern import parse_size


SECTOR_SIZE = 512
DATA_OFFSET_SECTORS = 520


@dataclass
class SelectedPair:
    even: str
    odd: str
    volume_sectors: int
    stripe_sectors: int
    supplied_indices: list[int]


def validate_members(paths: list[str]) -> SelectedPair:
    if len(paths) < 2:
        raise ArecaError("provide at least one member from each mirror pair")

    found: dict[int, tuple[str, Inspection]] = {}
    reference: tuple[str, int, int, str, int] | None = None
    for path in paths:
        result = inspect(path)
        if result.member_count != 4 or len(result.volumes) != 1:
            raise ArecaError(f"{path}: not a single-volume four-member array")
        volume = result.volumes[0]
        if (
            volume.stripe_sectors == 0
            or volume.stripe_sectors != volume.stripe_sectors_copy
        ):
            raise ArecaError(f"{path}: invalid or inconsistent stripe-size fields")
        if (
            volume.raid_level_code != 1
            or volume.raid_level_code_copy != 1
        ):
            raise ArecaError(f"{path}: metadata is not in the RAID1 family")
        if result.member_index not in range(4):
            raise ArecaError(f"{path}: invalid member index {result.member_index}")
        if result.member_index in found:
            raise ArecaError(f"duplicate member index {result.member_index}")

        identity = (
            result.raid_set_name,
            result.raid_set_sectors,
            volume.sectors,
            volume.name,
            volume.stripe_sectors,
        )
        if reference is None:
            reference = identity
        elif identity != reference:
            raise ArecaError(f"{path}: array/volume metadata does not match")
        found[result.member_index] = (path, result)

    group_a = [index for index in (0, 1) if index in found]
    group_b = [index for index in (2, 3) if index in found]
    if not group_a or not group_b:
        raise ArecaError(
            "members must include one of indices 0/1 and one of indices 2/3"
        )

    assert reference is not None
    return SelectedPair(
        even=found[group_a[0]][0],
        odd=found[group_b[0]][0],
        volume_sectors=reference[2],
        stripe_sectors=reference[4],
        supplied_indices=sorted(found),
    )


def available_data_bytes(path: str) -> int:
    result = inspect(path)
    return max(0, result.device_bytes - DATA_OFFSET_SECTORS * SECTOR_SIZE)


def reconstruct(paths: list[str], output: str, byte_count: int | None) -> int:
    selected = validate_members(paths)
    stripe_bytes = selected.stripe_sectors * SECTOR_SIZE
    available_logical = 2 * min(
        available_data_bytes(selected.even),
        available_data_bytes(selected.odd),
    )
    maximum = min(selected.volume_sectors * SECTOR_SIZE, available_logical)
    length = maximum if byte_count is None else byte_count
    if length <= 0 or length % stripe_bytes:
        raise ArecaError(
            f"output length must be a positive multiple of {stripe_bytes} bytes"
        )
    if length > maximum:
        raise ArecaError(
            f"requested {length} bytes, but inputs can reconstruct only {maximum}"
        )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    output_fd = os.open(output, flags, 0o600)
    source_fds: list[int] = []
    try:
        source_fds = [
            os.open(selected.even, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)),
            os.open(selected.odd, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)),
        ]
        chunks = length // stripe_bytes
        base = DATA_OFFSET_SECTORS * SECTOR_SIZE
        for logical_chunk in range(chunks):
            source = source_fds[logical_chunk % 2]
            packed_chunk = logical_chunk // 2
            data = os.pread(source, stripe_bytes, base + packed_chunk * stripe_bytes)
            if len(data) != stripe_bytes:
                raise ArecaError(f"short member read at logical chunk {logical_chunk}")
            written = os.write(output_fd, data)
            if written != len(data):
                raise ArecaError(f"short output write at logical chunk {logical_chunk}")
    except Exception:
        os.close(output_fd)
        output_fd = -1
        try:
            os.unlink(output)
        except FileNotFoundError:
            pass
        raise
    finally:
        for fd in source_fds:
            os.close(fd)
        if output_fd >= 0:
            os.close(output_fd)
    return length


def dm_table(paths: list[str]) -> tuple[SelectedPair, str]:
    selected = validate_members(paths)
    for path in (selected.even, selected.odd):
        if not os.path.isabs(path):
            raise ArecaError("device-mapper inputs must be absolute paths")
        if available_data_bytes(path) < (selected.volume_sectors // 2) * SECTOR_SIZE:
            raise ArecaError(f"{path}: too short for the complete logical volume")
    table = (
        f"0 {selected.volume_sectors} striped 2 {selected.stripe_sectors} "
        f"{selected.even} {DATA_OFFSET_SECTORS} "
        f"{selected.odd} {DATA_OFFSET_SECTORS}"
    )
    return selected, table


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)

    image = commands.add_parser("reconstruct", help="create a reconstructed image")
    image.add_argument("output")
    image.add_argument("members", nargs="+")
    image.add_argument("--bytes", type=parse_size)

    table = commands.add_parser("dm-table", help="print a read-only dmsetup table")
    table.add_argument("members", nargs="+")

    create = commands.add_parser(
        "create-dm", help="create a read-only device-mapper reconstruction"
    )
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
            selected, table = dm_table(args.members)
            print(f"selected member indices: {selected.supplied_indices}", file=sys.stderr)
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
