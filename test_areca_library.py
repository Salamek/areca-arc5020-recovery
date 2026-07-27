import os
import struct
import tempfile
import unittest

from areca import ArecaArray, ArecaError, RaidLevel, xor_blocks
from areca.metadata import RAID_MAGIC, VOLUME_MAGIC


class ArecaLibraryTests(unittest.TestCase):
    def make_member(
        self,
        *,
        index: int,
        member_count: int,
        raid_code: int,
        chunk_sectors: int,
        blocks: list[bytes],
        volume_sectors: int,
        name: bytes = b"ARC-LIB-TEST    ",
    ) -> str:
        chunk_bytes = chunk_sectors * 512
        image = bytearray(520 * 512 + len(blocks) * chunk_bytes)
        raid = memoryview(image)[512:1024]
        raid[:8] = RAID_MAGIC
        struct.pack_into("<I", raid, 8, member_count)
        struct.pack_into("<I", raid, 12, member_count)
        struct.pack_into("<I", raid, 0x54, index)
        struct.pack_into("<I", raid, 0x60, len(blocks) * chunk_sectors)
        raid[0x68:0x78] = b"Raid Set # 00   "
        volume = memoryview(image)[1024:1536]
        volume[:8] = VOLUME_MAGIC
        struct.pack_into("<I", volume, 8, volume_sectors)
        struct.pack_into("<I", volume, 20, volume_sectors)
        struct.pack_into("<H", volume, 0x28, chunk_sectors)
        struct.pack_into("<H", volume, 0x2A, chunk_sectors)
        volume[0x2C] = volume[0x2D] = raid_code
        volume[0x34:0x44] = name
        start = 520 * 512
        for number, block in enumerate(blocks):
            begin = start + number * chunk_bytes
            image[begin : begin + chunk_bytes] = block
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(image)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def reconstruct(self, array: ArecaArray, length: int) -> bytes:
        output = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(output) and os.unlink(output))
        array.reconstruct(output, length)
        with open(output, "rb") as stream:
            return stream.read()

    def test_autodetects_and_reconstructs_raid0(self) -> None:
        chunk = 4 * 512
        member_blocks = [
            [bytes([index + row * 4 + 1]) * chunk for row in range(2)]
            for index in range(4)
        ]
        members = [
            self.make_member(
                index=index,
                member_count=4,
                raid_code=0,
                chunk_sectors=4,
                blocks=member_blocks[index],
                volume_sectors=8 * 4,
            )
            for index in range(4)
        ]
        array = ArecaArray.assemble(members)
        expected = b"".join(
            member_blocks[index][row] for row in range(2) for index in range(4)
        )
        self.assertEqual(array.level, RaidLevel.RAID0)
        self.assertEqual(self.reconstruct(array, len(expected)), expected)
        with self.assertRaises(ArecaError):
            array.dm_table()

    def test_rejects_untested_raid0_member_count(self) -> None:
        chunk = 4 * 512
        members = [
            self.make_member(
                index=index,
                member_count=3,
                raid_code=0,
                chunk_sectors=4,
                blocks=[bytes([65 + index]) * chunk],
                volume_sectors=12,
            )
            for index in range(3)
        ]
        with self.assertRaisesRegex(ArecaError, "unsupported RAID code"):
            ArecaArray.assemble(members)

    def test_autodetects_and_reconstructs_raid1_from_one_member(self) -> None:
        chunk = 8 * 512
        blocks = [b"A" * chunk, b"B" * chunk]
        members = [
            self.make_member(
                index=index,
                member_count=2,
                raid_code=1,
                chunk_sectors=8,
                blocks=blocks,
                volume_sectors=16,
            )
            for index in range(2)
        ]
        array = ArecaArray.assemble([members[1]])
        self.assertEqual(array.level, RaidLevel.RAID1)
        self.assertEqual(self.reconstruct(array, 2 * chunk), b"".join(blocks))
        with self.assertRaises(ArecaError):
            array.dm_table()

    def test_rejects_mixed_array_fingerprints(self) -> None:
        chunk = 4 * 512
        first = self.make_member(
            index=0,
            member_count=2,
            raid_code=1,
            chunk_sectors=4,
            blocks=[b"A" * chunk],
            volume_sectors=4,
            name=b"ARRAY-A         ",
        )
        second = self.make_member(
            index=1,
            member_count=2,
            raid_code=1,
            chunk_sectors=4,
            blocks=[b"A" * chunk],
            volume_sectors=4,
            name=b"ARRAY-B         ",
        )
        with self.assertRaises(ArecaError):
            ArecaArray.assemble([first, second])

    def test_refuses_existing_file_output(self) -> None:
        chunk = 4 * 512
        member = self.make_member(
            index=0,
            member_count=2,
            raid_code=1,
            chunk_sectors=4,
            blocks=[b"A" * chunk],
            volume_sectors=4,
        )
        array = ArecaArray.assemble([member])
        output = tempfile.NamedTemporaryFile(delete=False)
        output.close()
        self.addCleanup(lambda: os.path.exists(output.name) and os.unlink(output.name))
        with self.assertRaises(ArecaError):
            array.reconstruct(output.name, chunk)

    def test_selects_packed_raid1_volume_by_index_or_name(self) -> None:
        chunk = 4 * 512
        member = self.make_member(
            index=0,
            member_count=2,
            raid_code=1,
            chunk_sectors=4,
            blocks=[b"A" * chunk],
            volume_sectors=4,
            name=b"MULTI-A         ",
        )
        second_start = (520 + 512) * 512
        with open(member, "r+b") as stream:
            stream.seek(1024 + 128)
            record = bytearray(128)
            record[:8] = VOLUME_MAGIC
            struct.pack_into("<I", record, 8, 4)
            struct.pack_into("<I", record, 0x0C, 1)
            struct.pack_into("<I", record, 0x14, 4)
            struct.pack_into("<I", record, 0x18, 1)
            struct.pack_into("<H", record, 0x28, 4)
            struct.pack_into("<H", record, 0x2A, 4)
            record[0x2C] = record[0x2D] = 1
            record[0x33] = 1
            record[0x34:0x44] = b"MULTI-B         "
            stream.write(record)
            stream.seek(second_start)
            stream.write(b"B" * chunk)

        with self.assertRaisesRegex(ArecaError, "multiple Volume Sets"):
            ArecaArray.assemble([member])

        by_index = ArecaArray.assemble([member], volume=1)
        by_name = ArecaArray.assemble([member], volume="MULTI-B")
        self.assertEqual(by_index.data_offset_sectors, 1032)
        self.assertEqual(by_index.volume_index, 1)
        self.assertEqual(self.reconstruct(by_index, chunk), b"B" * chunk)
        self.assertEqual(self.reconstruct(by_name, chunk), b"B" * chunk)

    def test_reconstructs_selected_packed_raid10_volume(self) -> None:
        chunk = 4 * 512
        members = [
            self.make_member(
                index=index,
                member_count=4,
                raid_code=1,
                chunk_sectors=4,
                blocks=[bytes([65 + index]) * chunk],
                volume_sectors=8,
                name=b"MULTI-A         ",
            )
            for index in (0, 2)
        ]
        second_start = (520 + 512) * 512
        for index, member in zip((0, 2), members):
            with open(member, "r+b") as stream:
                stream.seek(1024 + 128)
                record = bytearray(128)
                record[:8] = VOLUME_MAGIC
                struct.pack_into("<I", record, 8, 8)
                struct.pack_into("<I", record, 0x0C, 1)
                struct.pack_into("<I", record, 0x14, 8)
                struct.pack_into("<I", record, 0x18, 1)
                struct.pack_into("<H", record, 0x28, 4)
                struct.pack_into("<H", record, 0x2A, 4)
                record[0x2C] = record[0x2D] = 1
                record[0x33] = 1
                record[0x34:0x44] = b"MULTI-B         "
                stream.write(record)
                stream.seek(second_start)
                stream.write((b"L" if index == 0 else b"R") * chunk)

        array = ArecaArray.assemble(members, volume="MULTI-B")
        self.assertEqual(array.level, RaidLevel.RAID10)
        self.assertEqual(array.data_offset_sectors, 1032)
        self.assertEqual(
            self.reconstruct(array, 2 * chunk),
            b"L" * chunk + b"R" * chunk,
        )

    def test_reconstructs_selected_packed_raid0_volume(self) -> None:
        chunk = 4 * 512
        members = [
            self.make_member(
                index=index,
                member_count=4,
                raid_code=0,
                chunk_sectors=4,
                blocks=[bytes([65 + index]) * chunk],
                volume_sectors=16,
                name=b"MULTI-A         ",
            )
            for index in range(4)
        ]
        second_start = (520 + 512) * 512
        for index, member in enumerate(members):
            with open(member, "r+b") as stream:
                stream.seek(1024 + 128)
                record = bytearray(128)
                record[:8] = VOLUME_MAGIC
                struct.pack_into("<I", record, 8, 16)
                struct.pack_into("<I", record, 0x0C, 1)
                struct.pack_into("<I", record, 0x14, 16)
                struct.pack_into("<I", record, 0x18, 1)
                struct.pack_into("<H", record, 0x28, 4)
                struct.pack_into("<H", record, 0x2A, 4)
                record[0x2C] = record[0x2D] = 0
                record[0x33] = 1
                record[0x34:0x44] = b"MULTI-B         "
                stream.write(record)
                stream.seek(second_start)
                stream.write(bytes([76 + index]) * chunk)

        array = ArecaArray.assemble(members, volume=1)
        expected = b"".join(bytes([76 + index]) * chunk for index in range(4))
        self.assertEqual(array.level, RaidLevel.RAID0)
        self.assertEqual(array.data_offset_sectors, 1032)
        self.assertEqual(self.reconstruct(array, 4 * chunk), expected)

    def test_reconstructs_selected_packed_raid3_volume(self) -> None:
        chunk = 8 * 512
        data = [b"L" * chunk, b"M" * chunk, b"N" * chunk]
        second_blocks = data + [xor_blocks(data)]
        members = [
            self.make_member(
                index=index,
                member_count=4,
                raid_code=2,
                chunk_sectors=8,
                blocks=[bytes([65 + index]) * chunk],
                volume_sectors=24,
                name=b"MULTI-A         ",
            )
            for index in range(4)
        ]
        second_start = (520 + 512) * 512
        for index, member in enumerate(members):
            with open(member, "r+b") as stream:
                stream.seek(1024 + 128)
                record = bytearray(128)
                record[:8] = VOLUME_MAGIC
                struct.pack_into("<I", record, 8, 24)
                struct.pack_into("<I", record, 0x0C, 1)
                struct.pack_into("<I", record, 0x14, 24)
                struct.pack_into("<I", record, 0x18, 1)
                struct.pack_into("<H", record, 0x28, 8)
                struct.pack_into("<H", record, 0x2A, 8)
                record[0x2C] = record[0x2D] = 2
                record[0x33] = 1
                record[0x34:0x44] = b"MULTI-B         "
                stream.write(record)
                stream.seek(second_start)
                stream.write(second_blocks[index])

        array = ArecaArray.assemble(members, volume="MULTI-B")
        self.assertEqual(array.level, RaidLevel.RAID3)
        self.assertEqual(array.data_offset_sectors, 1032)
        self.assertEqual(self.reconstruct(array, 3 * chunk), b"".join(data))

    def test_reconstructs_selected_packed_raid5_volume(self) -> None:
        chunk = 4 * 512
        data = [b"L" * chunk, b"M" * chunk, b"N" * chunk]
        second_blocks = data + [xor_blocks(data)]
        members = [
            self.make_member(
                index=index,
                member_count=4,
                raid_code=3,
                chunk_sectors=4,
                blocks=[bytes([65 + index]) * chunk],
                volume_sectors=12,
                name=b"MULTI-A         ",
            )
            for index in range(4)
        ]
        second_start = (520 + 512) * 512
        for index, member in enumerate(members):
            with open(member, "r+b") as stream:
                stream.seek(1024 + 128)
                record = bytearray(128)
                record[:8] = VOLUME_MAGIC
                struct.pack_into("<I", record, 8, 12)
                struct.pack_into("<I", record, 0x0C, 1)
                struct.pack_into("<I", record, 0x14, 12)
                struct.pack_into("<I", record, 0x18, 1)
                struct.pack_into("<H", record, 0x28, 4)
                struct.pack_into("<H", record, 0x2A, 4)
                record[0x2C] = record[0x2D] = 3
                record[0x33] = 1
                record[0x34:0x44] = b"MULTI-B         "
                stream.write(record)
                stream.seek(second_start)
                stream.write(second_blocks[index])

        array = ArecaArray.assemble(members, volume=1)
        self.assertEqual(array.level, RaidLevel.RAID5)
        self.assertEqual(array.data_offset_sectors, 1032)
        self.assertEqual(self.reconstruct(array, 3 * chunk), b"".join(data))


if __name__ == "__main__":
    unittest.main()
