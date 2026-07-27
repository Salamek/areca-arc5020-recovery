"""Validated ARC-5020 array assembly and logical reconstruction."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .metadata import (
    SECTOR_SIZE,
    ArecaError,
    Inspection,
    inspect,
)

# All tested ARC-5020 layouts begin member data at LBA 520. This is an
# experimentally established family constant, not a decoded metadata field.
DATA_OFFSET_SECTORS = 520


class RaidLevel(str, Enum):
    RAID0 = "raid0"
    RAID1 = "raid1"
    RAID10 = "raid10"
    RAID3 = "raid3"
    RAID5 = "raid5"


@dataclass(frozen=True)
class Member:
    path: str
    inspection: Inspection
    fingerprint: str

    @property
    def index(self) -> int:
        return self.inspection.member_index

    @property
    def size(self) -> int:
        return self.inspection.device_bytes


def _normalized_fingerprint(path: str) -> str:
    """Hash metadata while normalizing the per-disk member-index field."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        data = bytearray(os.pread(fd, 8 * SECTOR_SIZE, 0))
    finally:
        os.close(fd)
    if len(data) != 8 * SECTOR_SIZE:
        raise ArecaError(f"{path}: short read while fingerprinting metadata")
    # Ignore LBA0, which may contain per-disk historical partition contents.
    metadata = data[SECTOR_SIZE:]
    index_offset = 0x54
    metadata[index_offset : index_offset + 4] = b"\0" * 4
    return hashlib.sha256(metadata).hexdigest()


def load_member(path: str) -> Member:
    resolved = str(Path(path).resolve())
    return Member(resolved, inspect(resolved), _normalized_fingerprint(resolved))


def xor_blocks(blocks: Iterable[bytes]) -> bytes:
    items = list(blocks)
    if not items:
        raise ArecaError("cannot XOR an empty block list")
    length = len(items[0])
    if any(len(block) != length for block in items):
        raise ArecaError("short or unequal member reads")
    result = bytearray(items[0])
    for block in items[1:]:
        for offset, value in enumerate(block):
            result[offset] ^= value
    return bytes(result)


def raid5_row_layout(row: int, member_count: int) -> tuple[int, list[int]]:
    parity = member_count - 1 - (row % member_count)
    data = [(parity + step) % member_count for step in range(1, member_count)]
    return parity, data


class ArecaArray:
    """A validated set of ARC-5020 members with a logical read mapping."""

    def __init__(
        self,
        members: list[Member],
        volume: int | str | None = None,
    ):
        if not members:
            raise ArecaError("no members supplied")
        first = members[0].inspection
        selected_index = self._select_volume(first, volume)
        fingerprint = members[0].fingerprint
        found: dict[int, Member] = {}
        for member in members:
            inspection = member.inspection
            if member.fingerprint != fingerprint:
                raise ArecaError(f"{member.path}: metadata fingerprint does not match")
            if len(inspection.volumes) != len(first.volumes):
                raise ArecaError(f"{member.path}: Volume record count does not match")
            if inspection.member_count != first.member_count:
                raise ArecaError(f"{member.path}: member count does not match")
            if inspection.member_index not in range(inspection.member_count):
                raise ArecaError(
                    f"{member.path}: invalid member index {inspection.member_index}"
                )
            if inspection.member_index in found:
                raise ArecaError(f"duplicate member index {inspection.member_index}")
            found[inspection.member_index] = member

        selected_volume = first.volumes[selected_index]
        if selected_volume.stripe_sectors <= 0:
            raise ArecaError("invalid zero stripe/chunk size")
        if selected_volume.stripe_sectors != selected_volume.stripe_sectors_copy:
            raise ArecaError("duplicate stripe/chunk fields do not match")
        if selected_volume.raid_level_code != selected_volume.raid_level_code_copy:
            raise ArecaError("duplicate RAID-level fields do not match")

        self.members = found
        self.member_count = first.member_count
        self.volumes = tuple(first.volumes)
        self.volume_index = selected_index
        self.volume = selected_volume
        self.chunk_sectors = selected_volume.stripe_sectors
        self.chunk_bytes = self.chunk_sectors * SECTOR_SIZE
        self.logical_bytes = selected_volume.bytes
        self.level = self._decode_level(selected_volume.raid_level_code)
        if len(self.volumes) > 1 and self.level != RaidLevel.RAID1:
            raise ArecaError(
                "multiple Volume Sets are currently validated only for RAID1"
            )
        self._validate_completeness()

    @classmethod
    def assemble(
        cls,
        paths: Iterable[str],
        volume: int | str | None = None,
    ) -> ArecaArray:
        return cls([load_member(path) for path in paths], volume)

    @staticmethod
    def _select_volume(inspection: Inspection, selector: int | str | None) -> int:
        volumes = inspection.volumes
        if selector is None:
            if len(volumes) == 1:
                return 0
            choices = ", ".join(
                f"{index}:{item.name or '<unnamed>'}"
                for index, item in enumerate(volumes)
            )
            raise ArecaError(
                f"multiple Volume Sets detected ({choices}); select one with --volume"
            )
        if isinstance(selector, int):
            if selector not in range(len(volumes)):
                raise ArecaError(f"Volume Set index out of range: {selector}")
            return selector
        matches = [
            index for index, item in enumerate(volumes) if item.name == selector
        ]
        if not matches:
            raise ArecaError(f"Volume Set not found: {selector!r}")
        if len(matches) != 1:
            raise ArecaError(f"Volume Set name is ambiguous: {selector!r}")
        return matches[0]

    def _decode_level(self, code: int) -> RaidLevel:
        if code == 0:
            return RaidLevel.RAID0
        if code == 1 and self.member_count == 2:
            return RaidLevel.RAID1
        if code == 1 and self.member_count == 4:
            return RaidLevel.RAID10
        if code == 2 and self.member_count in (3, 4):
            return RaidLevel.RAID3
        if code == 3 and self.member_count == 4:
            return RaidLevel.RAID5
        raise ArecaError(
            f"unsupported RAID code/member-count combination: {code}/{self.member_count}"
        )

    def _validate_completeness(self) -> None:
        count = len(self.members)
        if self.level == RaidLevel.RAID0 and count != self.member_count:
            raise ArecaError("RAID0 requires every member")
        if self.level == RaidLevel.RAID1 and count < 1:
            raise ArecaError("RAID1 requires at least one member")
        if self.level == RaidLevel.RAID10:
            if not any(index in self.members for index in (0, 1)):
                raise ArecaError("RAID1+0 requires one member from indices 0/1")
            if not any(index in self.members for index in (2, 3)):
                raise ArecaError("RAID1+0 requires one member from indices 2/3")
        if self.level in (RaidLevel.RAID3, RaidLevel.RAID5):
            if count not in (self.member_count - 1, self.member_count):
                raise ArecaError(
                    f"{self.level.value} requires {self.member_count - 1} "
                    f"or {self.member_count} members"
                )

    @property
    def supplied_indices(self) -> list[int]:
        return sorted(self.members)

    @property
    def data_offset_bytes(self) -> int:
        return self.volume.candidate_member_offset_bytes

    @property
    def data_offset_sectors(self) -> int:
        return self.volume.candidate_member_offset_sectors

    def maximum_reconstructable_bytes(self) -> int:
        available = min(
            member.size - self.data_offset_bytes for member in self.members.values()
        )
        if self.level == RaidLevel.RAID1:
            logical = available
        elif self.level == RaidLevel.RAID10:
            logical = available * 2
        elif self.level == RaidLevel.RAID0:
            logical = available * self.member_count
        else:
            logical = available * (self.member_count - 1)
        return min(self.logical_bytes, logical)

    def _open_sources(self) -> dict[int, int]:
        return {
            index: os.open(
                member.path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            )
            for index, member in self.members.items()
        }

    def _read_exact(self, fd: int, length: int, offset: int, context: str) -> bytes:
        data = os.pread(fd, length, offset)
        if len(data) != length:
            raise ArecaError(f"short read {context}: wanted {length}, got {len(data)}")
        return data

    def iter_logical(self, length: int | None = None):
        maximum = self.maximum_reconstructable_bytes()
        requested = maximum if length is None else length
        if requested <= 0 or requested % SECTOR_SIZE:
            raise ArecaError("output length must be a positive multiple of 512 bytes")
        if requested > maximum:
            raise ArecaError(
                f"requested {requested} bytes, but members can reconstruct only {maximum}"
            )

        fds = self._open_sources()
        try:
            remaining = requested
            logical_chunk = 0
            while remaining:
                amount = min(self.chunk_bytes, remaining)
                block = self._logical_chunk(fds, logical_chunk, amount)
                yield block
                remaining -= amount
                logical_chunk += 1
        finally:
            for fd in fds.values():
                os.close(fd)

    def _logical_chunk(
        self, fds: dict[int, int], logical_chunk: int, amount: int
    ) -> bytes:
        base = self.data_offset_bytes
        chunk = self.chunk_bytes

        if self.level == RaidLevel.RAID1:
            index = min(fds)
            return self._read_exact(
                fds[index], amount, base + logical_chunk * chunk, f"member {index}"
            )

        if self.level == RaidLevel.RAID0:
            index = logical_chunk % self.member_count
            packed = logical_chunk // self.member_count
            return self._read_exact(
                fds[index], amount, base + packed * chunk, f"member {index}"
            )

        if self.level == RaidLevel.RAID10:
            group = logical_chunk % 2
            candidates = (0, 1) if group == 0 else (2, 3)
            index = next(index for index in candidates if index in fds)
            packed = logical_chunk // 2
            return self._read_exact(
                fds[index], amount, base + packed * chunk, f"member {index}"
            )

        if self.level == RaidLevel.RAID3:
            data_members = self.member_count - 1
            data_index = logical_chunk % data_members
            row = logical_chunk // data_members
            offset = base + row * chunk
            if data_index in fds:
                return self._read_exact(
                    fds[data_index], amount, offset, f"member {data_index}, row {row}"
                )
            blocks = [
                self._read_exact(fd, amount, offset, f"member {index}, row {row}")
                for index, fd in fds.items()
            ]
            return xor_blocks(blocks)

        if self.level == RaidLevel.RAID5:
            data_members = self.member_count - 1
            row = logical_chunk // data_members
            position = logical_chunk % data_members
            _, data_order = raid5_row_layout(row, self.member_count)
            data_index = data_order[position]
            offset = base + row * chunk
            if data_index in fds:
                return self._read_exact(
                    fds[data_index], amount, offset, f"member {data_index}, row {row}"
                )
            blocks = [
                self._read_exact(fd, amount, offset, f"member {index}, row {row}")
                for index, fd in fds.items()
            ]
            return xor_blocks(blocks)

        raise AssertionError(self.level)

    def reconstruct(
        self,
        output: str,
        length: int | None = None,
        *,
        allow_block_device: bool = False,
    ) -> int:
        output_path = str(Path(output).resolve())
        existing_mode = None
        try:
            existing_mode = os.stat(output_path).st_mode
        except FileNotFoundError:
            pass

        if existing_mode is not None and stat.S_ISBLK(existing_mode):
            if not allow_block_device:
                raise ArecaError(
                    "refusing block-device output without explicit destructive approval"
                )
            flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
        elif existing_mode is not None:
            raise ArecaError(f"output already exists: {output_path}")
        else:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
            )

        requested = self.maximum_reconstructable_bytes() if length is None else length
        if existing_mode is not None and stat.S_ISBLK(existing_mode):
            from .metadata import device_size

            fd_check = os.open(output_path, os.O_RDONLY)
            try:
                if device_size(fd_check) < requested:
                    raise ArecaError("output block device is smaller than requested data")
            finally:
                os.close(fd_check)

        fd = os.open(output_path, flags, 0o600)
        try:
            written = 0
            for block in self.iter_logical(requested):
                if os.write(fd, block) != len(block):
                    raise ArecaError(f"short output write at byte {written}")
                written += len(block)
            os.fsync(fd)
            return written
        except Exception:
            os.close(fd)
            fd = -1
            if existing_mode is None:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
            raise
        finally:
            if fd >= 0:
                os.close(fd)

    def dm_table(self) -> str:
        """Return a direct device-mapper table where a safe mapping exists."""
        if self.maximum_reconstructable_bytes() < self.logical_bytes:
            raise ArecaError("complete members are required for a device-mapper target")
        for member in self.members.values():
            if not os.path.isabs(member.path):
                raise ArecaError("device-mapper inputs must use absolute paths")
            if not stat.S_ISBLK(os.stat(member.path).st_mode):
                raise ArecaError(
                    f"device-mapper input is not a block device: {member.path}"
                )
        sectors = self.logical_bytes // SECTOR_SIZE
        if self.level == RaidLevel.RAID1:
            member = self.members[min(self.members)]
            return f"0 {sectors} linear {member.path} {self.data_offset_sectors}"
        if self.level == RaidLevel.RAID0:
            devices = " ".join(
                f"{self.members[index].path} {self.data_offset_sectors}"
                for index in range(self.member_count)
            )
            return (
                f"0 {sectors} striped {self.member_count} "
                f"{self.chunk_sectors} {devices}"
            )
        if self.level == RaidLevel.RAID10:
            left = next(self.members[index] for index in (0, 1) if index in self.members)
            right = next(self.members[index] for index in (2, 3) if index in self.members)
            return (
                f"0 {sectors} striped 2 {self.chunk_sectors} "
                f"{left.path} {self.data_offset_sectors} "
                f"{right.path} {self.data_offset_sectors}"
            )
        raise ArecaError(
            f"direct device-mapper mapping is unavailable for {self.level.value}"
        )
