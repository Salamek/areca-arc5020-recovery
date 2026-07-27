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

    def test_detects_packed_volume_records(self) -> None:
        path = self.make_image()
        with open(path, "r+b") as handle:
            handle.seek(1024 + 128)
            volume = bytearray(128)
            volume[:8] = areca_member.VOLUME_MAGIC
            struct.pack_into("<I", volume, 8, 4096)
            struct.pack_into("<I", volume, 0x0C, 3815)
            struct.pack_into("<I", volume, 0x14, 4096)
            struct.pack_into("<I", volume, 0x18, 3815)
            struct.pack_into("<H", volume, 0x28, 128)
            struct.pack_into("<H", volume, 0x2A, 128)
            volume[0x2C] = volume[0x2D] = 1
            volume[0x2F] = 9
            volume[0x33] = 1
            volume[0x34:0x44] = b"MULTI-VOL-B\0\0\0\0\0"
            handle.write(volume)

        result = areca_member.inspect(path)
        self.assertEqual(len(result.volumes), 2)
        second = result.volumes[1]
        self.assertEqual(second.record_lba, 2)
        self.assertEqual(second.record_offset_in_lba, 128)
        self.assertEqual(second.record_slot, 1)
        self.assertEqual(second.allocation_offset_units, 3815)
        self.assertEqual(second.candidate_member_offset_sectors, 1_953_800)
        self.assertEqual(second.member_offset_sectors, 1_953_800)
        self.assertEqual(second.host_drive, 9)
        self.assertEqual(second.volume_index, 1)


if __name__ == "__main__":
    unittest.main()
