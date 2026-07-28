import os
import struct
import tempfile
import unittest

from areca import ArecaArray, raid5_row_layout, xor_blocks
from areca.metadata import RAID_MAGIC, VOLUME_MAGIC


class ArecaRaid5Tests(unittest.TestCase):
    def make_member(self, index: int, blocks: list[bytes]) -> str:
        sectors = 4
        chunk = sectors * 512
        image = bytearray(520 * 512 + len(blocks) * chunk)
        raid = memoryview(image)[512:1024]
        raid[:8] = RAID_MAGIC
        struct.pack_into("<I", raid, 8, 4)
        struct.pack_into("<I", raid, 12, 4)
        struct.pack_into("<I", raid, 0x54, index)
        struct.pack_into("<I", raid, 0x60, len(blocks) * sectors)
        raid[0x68:0x78] = b"Raid Set # 00   "
        volume = memoryview(image)[1024:1536]
        volume[:8] = VOLUME_MAGIC
        struct.pack_into("<I", volume, 8, len(blocks) * sectors * 3)
        struct.pack_into("<I", volume, 20, len(blocks) * sectors * 3)
        struct.pack_into("<H", volume, 0x28, sectors)
        struct.pack_into("<H", volume, 0x2A, sectors)
        volume[0x2C] = volume[0x2D] = 3
        volume[0x34:0x44] = b"ARC-R5-TEST     "
        start = 520 * 512
        for number, block in enumerate(blocks):
            image[start + number * chunk : start + (number + 1) * chunk] = block
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(image)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def make_set(self) -> tuple[list[str], bytes]:
        chunk = 4 * 512
        member_blocks = [[] for _ in range(4)]
        logical_parts = []
        for row in range(5):
            parity_index, data_order = raid5_row_layout(row, 4)
            data = [bytes([row * 3 + n + 1]) * chunk for n in range(3)]
            logical_parts.extend(data)
            parity = xor_blocks(data)
            for index, block in zip(data_order, data):
                member_blocks[index].append(block)
            member_blocks[parity_index].append(parity)
        members = [self.make_member(i, member_blocks[i]) for i in range(4)]
        return members, b"".join(logical_parts)

    def reconstruct(self, members: list[str], length: int) -> bytes:
        output = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(output) and os.unlink(output))
        ArecaArray.assemble(members).reconstruct(output, length)
        with open(output, "rb") as stream:
            return stream.read()

    def test_left_symmetric_rows(self) -> None:
        self.assertEqual(raid5_row_layout(0, 4), (3, [0, 1, 2]))
        self.assertEqual(raid5_row_layout(1, 4), (2, [3, 0, 1]))
        self.assertEqual(raid5_row_layout(2, 4), (1, [2, 3, 0]))
        self.assertEqual(raid5_row_layout(3, 4), (0, [1, 2, 3]))

    def test_reconstructs_all_and_each_missing_member(self) -> None:
        members, logical = self.make_set()
        self.assertEqual(self.reconstruct(members, len(logical)), logical)
        for missing in range(4):
            with self.subTest(missing=missing):
                supplied = [path for index, path in enumerate(members) if index != missing]
                self.assertEqual(self.reconstruct(supplied, len(logical)), logical)


if __name__ == "__main__":
    unittest.main()
