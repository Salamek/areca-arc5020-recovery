#!/usr/bin/env python3
"""Write and inspect an LBA-addressed RAID layout test pattern."""

from __future__ import annotations

import argparse
import array
import fcntl
import hashlib
import os
import stat
import struct
import sys
from pathlib import Path


SECTOR_SIZE = 512
CHUNK_SIZE = 128 * 1024
MAGIC = b"ARCLBA01"
XOR_CONSTANT = 0xA5A55A5AF0F00F0F
RECORD = struct.Struct("<8sQQQ")
RECORDS_PER_SECTOR = SECTOR_SIZE // RECORD.size
BLKGETSIZE64 = 0x80081272


class PatternError(RuntimeError):
    pass


def size_of(fd: int) -> int:
    info = os.fstat(fd)
    if stat.S_ISREG(info.st_mode):
        return info.st_size
    if stat.S_ISBLK(info.st_mode):
        value = array.array("Q", [0])
        fcntl.ioctl(fd, BLKGETSIZE64, value, True)
        return int(value[0])
    raise PatternError("input must be a regular file or block device")


def make_sector(lba: int) -> bytes:
    inverse = (~lba) & 0xFFFFFFFFFFFFFFFF
    check = lba ^ XOR_CONSTANT
    record = RECORD.pack(MAGIC, lba, inverse, check)
    return record * RECORDS_PER_SECTOR


def decode_sector(data: bytes) -> int | None:
    if len(data) != SECTOR_SIZE:
        return None
    expected_lba: int | None = None
    for offset in range(0, SECTOR_SIZE, RECORD.size):
        magic, lba, inverse, check = RECORD.unpack_from(data, offset)
        if magic != MAGIC:
            return None
        if inverse != ((~lba) & 0xFFFFFFFFFFFFFFFF):
            return None
        if check != (lba ^ XOR_CONSTANT):
            return None
        if expected_lba is None:
            expected_lba = lba
        elif lba != expected_lba:
            return None
    return expected_lba


def mounted_sources() -> set[str]:
    result: set[str] = set()
    with open("/proc/self/mountinfo", "r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip().split()
            separator = fields.index("-")
            source = fields[separator + 2]
            if source.startswith("/"):
                result.add(os.path.realpath(source))
    return result


def write_pattern(path: str, byte_count: int, destructive_ack: bool) -> str:
    if not destructive_ack:
        raise PatternError(
            "refusing to write without --i-understand-this-destroys-data"
        )
    if byte_count <= 0 or byte_count % SECTOR_SIZE:
        raise PatternError("write length must be a positive multiple of 512")

    resolved = os.path.realpath(path)
    if resolved in mounted_sources():
        raise PatternError(f"refusing to overwrite mounted source {resolved}")

    mode = os.stat(path).st_mode
    if stat.S_ISBLK(mode) and os.geteuid() != 0:
        raise PatternError("writing a block device requires root")
    if not (stat.S_ISBLK(mode) or stat.S_ISREG(mode)):
        raise PatternError("output must be a block device or regular test file")

    flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    digest = hashlib.sha256()
    try:
        available = size_of(fd)
        if byte_count > available:
            raise PatternError(
                f"requested {byte_count} bytes, device/file has {available}"
            )
        sectors_per_chunk = CHUNK_SIZE // SECTOR_SIZE
        total_sectors = byte_count // SECTOR_SIZE
        lba = 0
        while lba < total_sectors:
            count = min(sectors_per_chunk, total_sectors - lba)
            chunk = b"".join(make_sector(value) for value in range(lba, lba + count))
            written = os.write(fd, chunk)
            if written != len(chunk):
                raise PatternError(
                    f"short write at LBA {lba}: {written}/{len(chunk)} bytes"
                )
            digest.update(chunk)
            lba += count
            if lba % (128 * 1024) == 0 or lba == total_sectors:
                mib = lba * SECTOR_SIZE // (1024 * 1024)
                print(f"\rwritten {mib} MiB", end="", file=sys.stderr, flush=True)
        os.fsync(fd)
        print(file=sys.stderr)
        return digest.hexdigest()
    finally:
        os.close(fd)


def verify_pattern(path: str, byte_count: int, start_lba: int = 0) -> None:
    if byte_count <= 0 or byte_count % SECTOR_SIZE:
        raise PatternError("verify length must be a positive multiple of 512")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        offset = start_lba * SECTOR_SIZE
        if offset + byte_count > size_of(fd):
            raise PatternError("verification range exceeds input size")
        sectors = byte_count // SECTOR_SIZE
        for index in range(sectors):
            data = os.pread(fd, SECTOR_SIZE, offset + index * SECTOR_SIZE)
            decoded = decode_sector(data)
            expected = start_lba + index
            if decoded != expected:
                raise PatternError(
                    f"pattern mismatch at input sector {index}: "
                    f"decoded {decoded}, expected logical LBA {expected}"
                )
    finally:
        os.close(fd)


def scan_runs(path: str, offset: int, byte_count: int) -> list[tuple[int, int, int]]:
    """Return runs as (input sector, first logical LBA, sector count)."""
    if offset % SECTOR_SIZE or byte_count % SECTOR_SIZE:
        raise PatternError("scan offset and length must be multiples of 512")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    runs: list[tuple[int, int, int]] = []
    try:
        if offset + byte_count > size_of(fd):
            raise PatternError("scan range exceeds input size")
        current: list[int] | None = None
        sectors = byte_count // SECTOR_SIZE
        for input_sector in range(sectors):
            data = os.pread(fd, SECTOR_SIZE, offset + input_sector * SECTOR_SIZE)
            lba = decode_sector(data)
            if lba is None:
                if current is not None:
                    runs.append(tuple(current))
                    current = None
                continue
            if (
                current is not None
                and input_sector == current[0] + current[2]
                and lba == current[1] + current[2]
            ):
                current[2] += 1
            else:
                if current is not None:
                    runs.append(tuple(current))
                current = [input_sector, lba, 1]
        if current is not None:
            runs.append(tuple(current))
        return runs
    finally:
        os.close(fd)


def parse_size(value: str) -> int:
    suffixes = {
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
    }
    lowered = value.lower()
    for suffix, multiplier in suffixes.items():
        if lowered.endswith(suffix):
            number = lowered[: -len(suffix)]
            return int(number) * multiplier
    return int(value)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)

    write = commands.add_parser("write", help="destructively write the pattern")
    write.add_argument("device")
    write.add_argument("--bytes", type=parse_size, default=parse_size("1GiB"))
    write.add_argument(
        "--i-understand-this-destroys-data", action="store_true", required=True
    )

    verify = commands.add_parser("verify", help="verify a contiguous pattern")
    verify.add_argument("input")
    verify.add_argument("--bytes", type=parse_size, required=True)
    verify.add_argument("--start-lba", type=int, default=0)

    scan = commands.add_parser(
        "scan", help="report contiguous logical-LBA runs in a member/image"
    )
    scan.add_argument("input")
    scan.add_argument("--offset", type=parse_size, required=True)
    scan.add_argument("--bytes", type=parse_size, required=True)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "write":
            digest = write_pattern(
                args.device,
                args.bytes,
                args.i_understand_this_destroys_data,
            )
            print(f"SHA256 {digest}")
        elif args.command == "verify":
            verify_pattern(args.input, args.bytes, args.start_lba)
            print("pattern verified")
        elif args.command == "scan":
            runs = scan_runs(args.input, args.offset, args.bytes)
            for input_sector, logical_lba, count in runs:
                print(
                    f"input_sector={input_sector} "
                    f"logical_lba={logical_lba} sectors={count}"
                )
            if not runs:
                print("no valid pattern sectors found")
        return 0
    except (OSError, PatternError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
