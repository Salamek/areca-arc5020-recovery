import os
import struct
import tempfile
import unittest

from areca import ArecaArray, ArecaError
from areca.metadata import RAID_MAGIC, VOLUME_MAGIC


class ArecaRaid10Tests(unittest.TestCase):
    def make_member(self, index: int, chunks: list[bytes]) -> str:
        stripe_bytes = 128 * 512
        size = 520 * 512 + len(chunks) * stripe_bytes
        image = bytearray(size)
        raid = memoryview(image)[512:1024]
        raid[:8] = RAID_MAGIC
        struct.pack_into("<I", raid, 8, 4)
        struct.pack_into("<I", raid, 12, 4)
        struct.pack_into("<I", raid, 0x54, index)
        struct.pack_into("<I", raid, 0x60, len(chunks) * 128)
        raid[0x68:0x78] = b"Raid Set # 00   "
        volume = memoryview(image)[1024:1536]
        volume[:8] = VOLUME_MAGIC
        struct.pack_into("<I", volume, 8, len(chunks) * 256)
        struct.pack_into("<I", volume, 20, len(chunks) * 256)
        volume[0x28] = 0x80
        volume[0x2A] = 0x80
        volume[0x2C] = 1
        volume[0x2D] = 1
        volume[0x34:0x44] = b"ARC-R10-TEST    "
        start = 520 * 512
        for number, chunk in enumerate(chunks):
            image[start + number * len(chunk) : start + (number + 1) * len(chunk)] = chunk
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(image)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def test_reconstructs_one_member_from_each_pair(self) -> None:
        chunk = 128 * 512
        even = [b"A" * chunk, b"C" * chunk]
        odd = [b"B" * chunk, b"D" * chunk]
        member0 = self.make_member(0, even)
        member3 = self.make_member(3, odd)
        output = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(output) and os.unlink(output))
        length = ArecaArray.assemble([member0, member3]).reconstruct(
            output, 4 * chunk
        )
        self.assertEqual(length, 4 * chunk)
        with open(output, "rb") as stream:
            self.assertEqual(stream.read(), b"".join([even[0], odd[0], even[1], odd[1]]))

    def test_rejects_members_from_same_pair(self) -> None:
        chunk = 128 * 512
        member0 = self.make_member(0, [b"A" * chunk])
        member1 = self.make_member(1, [b"A" * chunk])
        with self.assertRaises(ArecaError):
            ArecaArray.assemble([member0, member1])


if __name__ == "__main__":
    unittest.main()
