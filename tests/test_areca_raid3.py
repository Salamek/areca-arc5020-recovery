import os
import struct
import tempfile
import unittest

from areca import ArecaArray, xor_blocks
from areca.metadata import RAID_MAGIC, VOLUME_MAGIC


class ArecaRaid3Tests(unittest.TestCase):
    def make_member(
        self, index: int, blocks: list[bytes], member_count: int = 4
    ) -> str:
        chunk_sectors = 8
        chunk = chunk_sectors * 512
        image = bytearray(520 * 512 + len(blocks) * chunk)
        raid = memoryview(image)[512:1024]
        raid[:8] = RAID_MAGIC
        struct.pack_into("<I", raid, 8, member_count)
        struct.pack_into("<I", raid, 12, member_count)
        struct.pack_into("<I", raid, 0x54, index)
        struct.pack_into("<I", raid, 0x60, len(blocks) * chunk_sectors)
        raid[0x68:0x78] = b"Raid Set # 00   "
        volume = memoryview(image)[1024:1536]
        volume[:8] = VOLUME_MAGIC
        data_members = member_count - 1
        struct.pack_into(
            "<I", volume, 8, len(blocks) * chunk_sectors * data_members
        )
        struct.pack_into(
            "<I", volume, 20, len(blocks) * chunk_sectors * data_members
        )
        struct.pack_into("<H", volume, 0x28, chunk_sectors)
        struct.pack_into("<H", volume, 0x2A, chunk_sectors)
        volume[0x2C] = volume[0x2D] = 2
        volume[0x34:0x44] = b"ARC-R3-TEST     "
        start = 520 * 512
        for number, block in enumerate(blocks):
            image[start + number * chunk : start + (number + 1) * chunk] = block
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(image)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def make_set(self) -> tuple[list[str], bytes]:
        chunk = 8 * 512
        data = [
            [bytes([index * 3 + row + 1]) * chunk for row in range(2)]
            for index in range(3)
        ]
        parity = [
            xor_blocks([data[0][row], data[1][row], data[2][row]])
            for row in range(2)
        ]
        members = [self.make_member(i, data[i] if i < 3 else parity) for i in range(4)]
        logical = b"".join(
            data[index][row] for row in range(2) for index in range(3)
        )
        return members, logical

    def reconstruct(self, members: list[str], length: int) -> bytes:
        output = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(output) and os.unlink(output))
        ArecaArray.assemble(members).reconstruct(output, length)
        with open(output, "rb") as stream:
            return stream.read()

    def test_reconstructs_with_all_members(self) -> None:
        members, logical = self.make_set()
        self.assertEqual(self.reconstruct(members, len(logical)), logical)

    def test_reconstructs_each_missing_data_member(self) -> None:
        members, logical = self.make_set()
        for missing in range(3):
            with self.subTest(missing=missing):
                supplied = [path for index, path in enumerate(members) if index != missing]
                self.assertEqual(self.reconstruct(supplied, len(logical)), logical)

    def test_reconstructs_without_parity(self) -> None:
        members, logical = self.make_set()
        self.assertEqual(self.reconstruct(members[:3], len(logical)), logical)

    def test_three_member_layout_and_each_omission(self) -> None:
        chunk = 8 * 512
        data = [
            [bytes([index * 4 + row + 1]) * chunk for row in range(3)]
            for index in range(2)
        ]
        parity = [
            xor_blocks([data[0][row], data[1][row]])
            for row in range(3)
        ]
        blocks = [data[0], data[1], parity]
        members = [self.make_member(i, blocks[i], 3) for i in range(3)]
        logical = b"".join(
            data[index][row] for row in range(3) for index in range(2)
        )
        self.assertEqual(self.reconstruct(members, len(logical)), logical)
        for missing in range(3):
            with self.subTest(missing=missing):
                supplied = [
                    path for index, path in enumerate(members) if index != missing
                ]
                self.assertEqual(self.reconstruct(supplied, len(logical)), logical)


if __name__ == "__main__":
    unittest.main()
