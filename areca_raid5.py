#!/usr/bin/env python3
"""Reconstruct the observed four-member ARC-5020 left-symmetric RAID5.

Parity rotates from the highest member index downward. Logical data begins
on the member immediately after parity and wraps around. Inputs are opened
read-only and one missing member can be tolerated.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from areca_member import ArecaError, Inspection, inspect
from raid_pattern import parse_size


SECTOR_SIZE = 512
DATA_OFFSET_SECTORS = 520


@dataclass
class MemberSet:
    paths: dict[int, str]
    member_count: int
    volume_sectors: int
    chunk_sectors: int
    supplied_indices: list[int]


def validate_members(paths: list[str]) -> MemberSet:
    if len(paths) not in (3, 4):
        raise ArecaError("four-member RAID5 recovery requires three or four members")
    found: dict[int, tuple[str, Inspection]] = {}
    reference: tuple[str, int, int, str, int, int] | None = None
    for path in paths:
        result = inspect(path)
        if result.member_count != 4 or len(result.volumes) != 1:
            raise ArecaError(f"{path}: not a single-volume four-member array")
        volume = result.volumes[0]
        if volume.raid_level_code != 3 or volume.raid_level_code_copy != 3:
            raise ArecaError(f"{path}: metadata does not identify RAID5")
        if (
            volume.stripe_sectors == 0
            or volume.stripe_sectors != volume.stripe_sectors_copy
        ):
            raise ArecaError(f"{path}: invalid or inconsistent stripe-size fields")
        index = result.member_index
        if index not in range(result.member_count):
            raise ArecaError(f"{path}: invalid member index {index}")
        if index in found:
            raise ArecaError(f"duplicate member index {index}")
        identity = (
            result.raid_set_name,
            result.raid_set_sectors,
            volume.sectors,
            volume.name,
            volume.stripe_sectors,
            result.member_count,
        )
        if reference is None:
            reference = identity
        elif identity != reference:
            raise ArecaError(f"{path}: array/volume metadata does not match")
        found[index] = (path, result)

    assert reference is not None
    return MemberSet(
        paths={index: item[0] for index, item in found.items()},
        member_count=reference[5],
        volume_sectors=reference[2],
        chunk_sectors=reference[4],
        supplied_indices=sorted(found),
    )


def xor_blocks(blocks: list[bytes]) -> bytes:
    if not blocks:
        raise ArecaError("cannot XOR an empty block list")
    length = len(blocks[0])
    if any(len(block) != length for block in blocks):
        raise ArecaError("short or unequal member reads")
    result = bytearray(blocks[0])
    for block in blocks[1:]:
        for offset, value in enumerate(block):
            result[offset] ^= value
    return bytes(result)


def row_layout(row: int, member_count: int) -> tuple[int, list[int]]:
    parity = member_count - 1 - (row % member_count)
    data = [
        (parity + step) % member_count
        for step in range(1, member_count)
    ]
    return parity, data


def reconstruct(paths: list[str], output: str, byte_count: int | None) -> int:
    members = validate_members(paths)
    chunk_bytes = members.chunk_sectors * SECTOR_SIZE
    base = DATA_OFFSET_SECTORS * SECTOR_SIZE
    available = min(inspect(path).device_bytes - base for path in members.paths.values())
    data_members = members.member_count - 1
    maximum = min(members.volume_sectors * SECTOR_SIZE, available * data_members)
    length = maximum if byte_count is None else byte_count
    if length <= 0 or length % chunk_bytes:
        raise ArecaError(
            f"output length must be a positive multiple of {chunk_bytes} bytes"
        )
    if length > maximum:
        raise ArecaError(
            f"requested {length} bytes, but inputs can reconstruct only {maximum}"
        )

    output_fd = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    source_fds: dict[int, int] = {}
    try:
        source_fds = {
            index: os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            for index, path in members.paths.items()
        }
        logical_chunks = length // chunk_bytes
        written_chunks = 0
        row = 0
        while written_chunks < logical_chunks:
            _, data_order = row_layout(row, members.member_count)
            offset = base + row * chunk_bytes
            cache = {
                index: os.pread(fd, chunk_bytes, offset)
                for index, fd in source_fds.items()
            }
            if any(len(block) != chunk_bytes for block in cache.values()):
                raise ArecaError(f"short member read at row {row}")
            for data_index in data_order:
                if written_chunks >= logical_chunks:
                    break
                if data_index in cache:
                    block = cache[data_index]
                else:
                    # XOR of every surviving block recovers the absent block,
                    # regardless of whether it is data or parity.
                    block = xor_blocks(list(cache.values()))
                if os.write(output_fd, block) != len(block):
                    raise ArecaError(
                        f"short output write at logical chunk {written_chunks}"
                    )
                written_chunks += 1
            row += 1
    except Exception:
        os.close(output_fd)
        output_fd = -1
        try:
            os.unlink(output)
        except FileNotFoundError:
            pass
        raise
    finally:
        for fd in source_fds.values():
            os.close(fd)
        if output_fd >= 0:
            os.close(output_fd)
    return length


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
