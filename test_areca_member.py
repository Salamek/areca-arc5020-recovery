import os
import struct
import tempfile
import unittest

import areca_member


class ArecaMemberTests(unittest.TestCase):
    def make_image(self) -> str:
        image = bytearray(4 * 1024 * 1024)
        raid = memoryview(image)[512:1024]
        raid[:8] = areca_member.RAID_MAGIC
        struct.pack_into("<I", raid, 8, 2)
        struct.pack_into("<I", raid, 12, 2)
        struct.pack_into("<I", raid, 0x54, 1)
        struct.pack_into("<I", raid, 0x60, 4096 + 512)
        raid[0x68:0x78] = b"Raid Set # 00   "

        volume = memoryview(image)[1024:1536]
        volume[:8] = areca_member.VOLUME_MAGIC
        struct.pack_into("<I", volume, 8, 4096)
        struct.pack_into("<I", volume, 20, 4096)
        volume[0x28] = 0x80
        volume[0x2A] = 0x80
        volume[0x2C] = 1
        volume[0x2D] = 1
        volume[0x34:0x44] = b"ARC-TEST-VOL#00 "

        offset_lba = 520
        mbr = offset_lba * 512
        image[mbr + 510 : mbr + 512] = b"\x55\xaa"
        gpt = mbr + 512
        image[gpt : gpt + 8] = areca_member.GPT_MAGIC
        struct.pack_into("<I", image, gpt + 12, 92)
        struct.pack_into("<Q", image, gpt + 24, 1)

        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(image)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        return handle.name

    def test_detects_validated_layout(self) -> None:
        path = self.make_image()
        result = areca_member.inspect(path)
        self.assertTrue(result.areca_detected)
        self.assertEqual(result.member_count, 2)
        self.assertEqual(result.member_index, 1)
        self.assertEqual(result.volumes[0].sectors, 4096)
        self.assertEqual(result.volumes[0].member_offset_sectors, 520)
        self.assertEqual(result.volumes[0].stripe_sectors, 128)
        self.assertEqual(result.volumes[0].stripe_sectors_copy, 128)
        self.assertEqual(result.volumes[0].raid_level_code, 1)

    def test_rejects_missing_magic(self) -> None:
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(bytes(4096))
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        with self.assertRaises(areca_member.ArecaError):
            areca_member.inspect(handle.name)


if __name__ == "__main__":
    unittest.main()
