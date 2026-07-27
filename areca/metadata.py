#!/usr/bin/env python3
"""Inspect an Areca RAID member and expose a recoverable RAID1 volume.

This is an experimental parser based on an ARC-5020 V1.50 RAID1 member.
It deliberately refuses ambiguous layouts instead of guessing.
"""

from __future__ import annotations

import argparse
import array
import fcntl
import json
import os
import stat
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SECTOR_SIZE = 512
RAID_RECORD_LBA = 1
VOLUME_RECORD_FIRST_LBA = 2
VOLUME_RECORD_LAST_LBA = 7
VOLUME_RECORD_SIZE = 128
VOLUME_ALLOCATION_UNIT_SECTORS = 512
OBSERVED_DATA_START_SECTORS = 520
RAID_MAGIC = b"$RaidSD$"
VOLUME_MAGIC = b"$VolumE$"
GPT_MAGIC = b"EFI PART"
BLKGETSIZE64 = 0x80081272
SCAN_BYTES = 16 * 1024 * 1024


class ArecaError(RuntimeError):
    pass


@dataclass
class Volume:
    record_lba: int
    record_offset_in_lba: int
    record_byte_offset: int
    record_slot: int
    name: str
    sectors: int
    bytes: int
    allocation_offset_units: int
    allocation_offset_units_copy: int
    candidate_member_offset_sectors: int
    candidate_member_offset_bytes: int
    host_drive: int
    volume_index: int
    stripe_sectors: int
    stripe_sectors_copy: int
    raid_level_code: int
    raid_level_code_copy: int
    inferred_raid_level: str | None
    member_offset_sectors: int
    member_offset_bytes: int
    offset_source: str
    gpt_header_member_lba: int | None


@dataclass
class Inspection:
    path: str
    device_bytes: int
    sector_size: int
    areca_detected: bool
    raid_magic_lba: int
    volume_magic_lbas: list[int]
    volume_record_byte_offsets: list[int]
    raid_set_name: str
    member_count: int
    member_index: int
    raw_raid_record_word_0c: int
    raid_set_sectors: int
    volumes: list[Volume]
    warnings: list[str]


def pread_exact(fd: int, length: int, offset: int) -> bytes:
    data = os.pread(fd, length, offset)
    if len(data) != length:
        raise ArecaError(
            f"short read at byte {offset}: wanted {length}, got {len(data)}"
        )
    return data


def device_size(fd: int) -> int:
    mode = os.fstat(fd).st_mode
    if stat.S_ISREG(mode):
        return os.fstat(fd).st_size
    if stat.S_ISBLK(mode):
        value = array.array("Q", [0])
        fcntl.ioctl(fd, BLKGETSIZE64, value, True)
        return int(value[0])
    raise ArecaError("input must be a regular file or block device")


def text_field(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("ascii", "replace").rstrip()


def find_gpt_offset(fd: int, limit: int) -> tuple[int, int] | None:
    """Return (logical-volume start LBA, GPT header member LBA)."""
    scan = os.pread(fd, min(SCAN_BYTES, limit), 0)
    candidates: list[tuple[int, int]] = []
    position = 0
    while True:
        position = scan.find(GPT_MAGIC, position)
        if position < 0:
            break
        if position % SECTOR_SIZE == 0 and position + 92 <= len(scan):
            header = scan[position : position + SECTOR_SIZE]
            header_size = struct.unpack_from("<I", header, 12)[0]
            current_lba = struct.unpack_from("<Q", header, 24)[0]
            if 92 <= header_size <= SECTOR_SIZE and current_lba in (1,):
                member_lba = position // SECTOR_SIZE
                if member_lba >= current_lba:
                    candidates.append((member_lba - current_lba, member_lba))
        position += 1

    unique = sorted(set(candidates))
    if not unique:
        return None
    if len(unique) != 1:
        raise ArecaError(f"ambiguous GPT-derived offsets: {unique}")
    return unique[0]


def inspect(path: str) -> Inspection:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        size = device_size(fd)
        if size < 8 * SECTOR_SIZE:
            raise ArecaError("input is too small to contain Areca metadata")

        raid = pread_exact(
            fd, SECTOR_SIZE, RAID_RECORD_LBA * SECTOR_SIZE
        )
        if raid[:8] != RAID_MAGIC:
            actual = raid[:8]
            raise ArecaError(
                f"Areca RAID signature absent at LBA 1 "
                f"(found {actual!r}, expected {RAID_MAGIC!r})"
            )

        records: list[tuple[int, int, int, bytes]] = []
        for lba in range(VOLUME_RECORD_FIRST_LBA, VOLUME_RECORD_LAST_LBA + 1):
            sector = pread_exact(fd, SECTOR_SIZE, lba * SECTOR_SIZE)
            for offset in range(0, SECTOR_SIZE, VOLUME_RECORD_SIZE):
                record = sector[offset : offset + VOLUME_RECORD_SIZE]
                if record[:8] == VOLUME_MAGIC:
                    byte_offset = lba * SECTOR_SIZE + offset
                    slot = (
                        (lba - VOLUME_RECORD_FIRST_LBA)
                        * (SECTOR_SIZE // VOLUME_RECORD_SIZE)
                        + offset // VOLUME_RECORD_SIZE
                    )
                    records.append((lba, offset, slot, record))

        if not records:
            raise ArecaError("RAID signature found, but no Volume record in LBAs 2-7")

        warnings: list[str] = []
        gpt = find_gpt_offset(fd, size)

        member_count = struct.unpack_from("<I", raid, 8)[0]
        volumes: list[Volume] = []
        for record_lba, record_offset, record_slot, record in records:
            location = f"LBA {record_lba} +{record_offset}"
            sectors = struct.unpack_from("<I", record, 8)[0]
            duplicate_sectors = struct.unpack_from("<I", record, 20)[0]
            if sectors == 0:
                raise ArecaError(f"Volume record at {location} has zero length")
            if duplicate_sectors != sectors:
                warnings.append(
                    f"Volume {location}: sector-count copy at +0x14 "
                    f"is {duplicate_sectors}, expected {sectors}"
                )

            allocation_offset_units = struct.unpack_from("<I", record, 0x0C)[0]
            allocation_offset_units_copy = struct.unpack_from("<I", record, 0x18)[0]
            candidate_member_offset_sectors = (
                OBSERVED_DATA_START_SECTORS
                + allocation_offset_units * VOLUME_ALLOCATION_UNIT_SECTORS
            )
            if allocation_offset_units != allocation_offset_units_copy:
                warnings.append(
                    f"Volume {location}: allocation-offset copies at +0x0c/+0x18 "
                    f"are {allocation_offset_units}/{allocation_offset_units_copy}"
                )

            if allocation_offset_units != allocation_offset_units_copy:
                member_offset_sectors = -1
                gpt_member_lba = None
                offset_source = "unresolved"
            else:
                member_offset_sectors = candidate_member_offset_sectors
                gpt_member_lba = (
                    gpt[1]
                    if gpt is not None and allocation_offset_units == 0
                    else None
                )
                offset_source = "verified ARC-5020 allocation metadata"
                if (
                    gpt is not None
                    and allocation_offset_units == 0
                    and gpt[0] != member_offset_sectors
                ):
                    warnings.append(
                        f"Volume {location}: metadata start LBA "
                        f"{member_offset_sectors} disagrees with GPT-derived "
                        f"start LBA {gpt[0]}"
                    )

            stripe_sectors = struct.unpack_from("<H", record, 0x28)[0]
            stripe_sectors_copy = struct.unpack_from("<H", record, 0x2A)[0]
            raid_level_code = record[0x2C]
            raid_level_code_copy = record[0x2D]
            if stripe_sectors == 0 or stripe_sectors != stripe_sectors_copy:
                warnings.append(
                    f"Volume {location}: stripe fields at +0x28/+0x2a "
                    f"are {stripe_sectors}/{stripe_sectors_copy}"
                )
            if raid_level_code != raid_level_code_copy:
                warnings.append(
                    f"Volume {location}: RAID-level fields at +0x2c/+0x2d "
                    f"are {raid_level_code}/{raid_level_code_copy}"
                )
            if raid_level_code == 0:
                inferred = "RAID0 (observed ARC-5020 code)"
            elif raid_level_code == 1 and member_count == 2:
                inferred = "RAID1 (observed ARC-5020 combination)"
            elif raid_level_code == 1 and member_count == 4:
                inferred = "RAID1+0 (observed ARC-5020 combination)"
            elif raid_level_code == 1:
                inferred = "RAID1-family (unsupported member count)"
            elif raid_level_code == 2:
                inferred = "RAID3 (observed ARC-5020 code)"
            elif raid_level_code == 3:
                inferred = "RAID5 (observed ARC-5020 code)"
            else:
                inferred = None
            volume = Volume(
                record_lba=record_lba,
                record_offset_in_lba=record_offset,
                record_byte_offset=record_lba * SECTOR_SIZE + record_offset,
                record_slot=record_slot,
                name=text_field(record[0x34:0x44]),
                sectors=sectors,
                bytes=sectors * SECTOR_SIZE,
                allocation_offset_units=allocation_offset_units,
                allocation_offset_units_copy=allocation_offset_units_copy,
                candidate_member_offset_sectors=candidate_member_offset_sectors,
                candidate_member_offset_bytes=(
                    candidate_member_offset_sectors * SECTOR_SIZE
                ),
                host_drive=record[0x2F],
                volume_index=record[0x33],
                stripe_sectors=stripe_sectors,
                stripe_sectors_copy=stripe_sectors_copy,
                raid_level_code=raid_level_code,
                raid_level_code_copy=raid_level_code_copy,
                inferred_raid_level=inferred,
                member_offset_sectors=member_offset_sectors,
                member_offset_bytes=(
                    member_offset_sectors * SECTOR_SIZE
                    if member_offset_sectors >= 0
                    else -1
                ),
                offset_source=offset_source,
                gpt_header_member_lba=gpt_member_lba,
            )
            if member_offset_sectors >= 0:
                if raid_level_code == 0:
                    data_width = member_count
                elif raid_level_code == 1 and member_count == 4:
                    data_width = 2
                elif raid_level_code in (2, 3):
                    data_width = member_count - 1
                else:
                    data_width = 1
                member_sectors = (volume.sectors + data_width - 1) // data_width
                end = volume.member_offset_bytes + member_sectors * SECTOR_SIZE
                if end > size:
                    warnings.append(
                        f"Volume {location}: input ends before the complete "
                        f"Volume Set ({size} bytes available, {end} required)"
                    )
                if gpt_member_lba is not None:
                    mbr = pread_exact(fd, SECTOR_SIZE, volume.member_offset_bytes)
                    if mbr[510:512] != b"\x55\xaa":
                        warnings.append(
                            f"Volume {location}: GPT was found, but the derived "
                            "volume start lacks an MBR 0x55aa signature"
                        )
            volumes.append(volume)

        raid_set_sectors = struct.unpack_from("<I", raid, 0x60)[0]
        if volumes and raid_set_sectors and volumes[0].sectors > raid_set_sectors:
            warnings.append(
                "Volume sector count exceeds the per-member Raid Set capacity "
                "field; this may be valid for a striped layout"
            )

        return Inspection(
            path=str(Path(path).resolve()),
            device_bytes=size,
            sector_size=SECTOR_SIZE,
            areca_detected=True,
            raid_magic_lba=RAID_RECORD_LBA,
            volume_magic_lbas=[lba for lba, _, _, _ in records],
            volume_record_byte_offsets=[
                lba * SECTOR_SIZE + offset for lba, offset, _, _ in records
            ],
            raid_set_name=text_field(raid[0x68:0x78]),
            member_count=member_count,
            member_index=struct.unpack_from("<I", raid, 0x54)[0],
            raw_raid_record_word_0c=struct.unpack_from("<I", raid, 12)[0],
            raid_set_sectors=raid_set_sectors,
            volumes=volumes,
            warnings=warnings,
        )
    finally:
        os.close(fd)


def print_human(result: Inspection) -> None:
    print("Areca metadata: detected")
    print(f"Input: {result.path}")
    print(f"Member size: {result.device_bytes} bytes")
    print(f"Raid Set: {result.raid_set_name or '<unnamed>'}")
    print(f"Member count: {result.member_count}")
    print(f"Member index: {result.member_index} (zero-based)")
    print(
        "Raw Raid record word at +0x0c: "
        f"0x{result.raw_raid_record_word_0c:08x}"
    )
    print(f"Raid Set capacity field: {result.raid_set_sectors} sectors")
    for index, volume in enumerate(result.volumes):
        print(f"Volume {index}:")
        print(f"  Name: {volume.name or '<unnamed>'}")
        print(
            f"  Metadata record: LBA {volume.record_lba} "
            f"+{volume.record_offset_in_lba} (slot {volume.record_slot}, "
            f"byte {volume.record_byte_offset})"
        )
        print(
            "  Allocation-offset copies at +0x0c/+0x18: "
            f"{volume.allocation_offset_units}/"
            f"{volume.allocation_offset_units_copy} units"
        )
        start_label = (
            "Verified member start"
            if (
                volume.raid_level_code == 0
                or volume.raid_level_code == 2
                or volume.raid_level_code == 3
                or (
                    result.member_count in (2, 4)
                    and volume.raid_level_code == 1
                )
            )
            else "Candidate member start (unverified for this RAID level)"
        )
        print(
            f"  {start_label}: {volume.candidate_member_offset_sectors} sectors "
            f"({volume.candidate_member_offset_bytes} bytes)"
        )
        print(
            f"  Host drive: {volume.host_drive}; "
            f"volume index: {volume.volume_index}"
        )
        print(
            f"  Stripe size: {volume.stripe_sectors} sectors "
            f"({volume.stripe_sectors * SECTOR_SIZE} bytes)"
        )
        print(
            "  Stripe-size copies at +0x28/+0x2a: "
            f"{volume.stripe_sectors}/{volume.stripe_sectors_copy} sectors"
        )
        print(
            "  RAID-level code copies at +0x2c/+0x2d: "
            f"{volume.raid_level_code}/{volume.raid_level_code_copy}"
        )
        if volume.inferred_raid_level:
            print(f"  Inferred RAID level: {volume.inferred_raid_level}")
        else:
            print("  Inferred RAID level: unknown/unsupported")
        print(f"  Logical length: {volume.sectors} sectors ({volume.bytes} bytes)")
        if volume.member_offset_sectors >= 0:
            print(
                f"  Member offset: {volume.member_offset_sectors} sectors "
                f"({volume.member_offset_bytes} bytes)"
            )
            print(f"  Offset source: {volume.offset_source}")
        else:
            print("  Member offset: unresolved")
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)


def create_loop(result: Inspection, writable: bool) -> str:
    if os.geteuid() != 0:
        raise ArecaError("loop creation requires root; run the script with sudo")
    if len(result.volumes) != 1:
        raise ArecaError("loop creation requires exactly one detected Volume record")
    volume = result.volumes[0]
    if volume.member_offset_bytes < 0:
        raise ArecaError("loop creation refused because volume offset is unresolved")
    if result.device_bytes < volume.member_offset_bytes + volume.bytes:
        raise ArecaError("loop creation requires a complete Volume Set capture")
    if result.member_count != 2 or not volume.inferred_raid_level.startswith("RAID1 "):
        raise ArecaError(
            "linear loop creation is only supported for the validated "
            "two-member RAID1 layout"
        )
    command = [
        "losetup",
        "--find",
        "--show",
        "--partscan",
        "--offset",
        str(volume.member_offset_bytes),
        "--sizelimit",
        str(volume.bytes),
    ]
    if not writable:
        command.append("--read-only")
    command.append(result.path)
    completed = subprocess.run(
        command, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect experimental Areca $RaidSD$/$VolumE$ metadata and "
            "optionally create a translated loop device."
        )
    )
    parser.add_argument("device", help="member block device or raw image")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable inspection JSON"
    )
    parser.add_argument(
        "--create-loop",
        action="store_true",
        help="create a partition-scanning loop mapping (root required)",
    )
    parser.add_argument(
        "--writable-loop",
        action="store_true",
        help="make the loop mapping writable (unsafe; requires --create-loop)",
    )
    args = parser.parse_args()
    if args.writable_loop and not args.create_loop:
        parser.error("--writable-loop requires --create-loop")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = inspect(args.device)
        if args.json:
            print(json.dumps(asdict(result), indent=2))
        else:
            print_human(result)
        if args.create_loop:
            loop = create_loop(result, writable=args.writable_loop)
            print(loop)
        return 0
    except (ArecaError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
