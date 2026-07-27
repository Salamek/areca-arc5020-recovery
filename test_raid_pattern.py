import os
import tempfile
import unittest

import raid_pattern


class RaidPatternTests(unittest.TestCase):
    def test_sector_round_trip(self) -> None:
        for lba in (0, 1, 127, 128, 2**32 + 7):
            self.assertEqual(
                raid_pattern.decode_sector(raid_pattern.make_sector(lba)), lba
            )

    def test_detects_corruption(self) -> None:
        data = bytearray(raid_pattern.make_sector(42))
        data[100] ^= 1
        self.assertIsNone(raid_pattern.decode_sector(bytes(data)))

    def test_write_verify_and_scan(self) -> None:
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.truncate(1024 * 1024)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        digest = raid_pattern.write_pattern(handle.name, 512 * 32, True)
        self.assertEqual(len(digest), 64)
        raid_pattern.verify_pattern(handle.name, 512 * 32)
        runs = raid_pattern.scan_runs(handle.name, 0, 512 * 64)
        self.assertEqual(runs, [(0, 0, 32)])

    def test_distinct_pattern_lba_base(self) -> None:
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.truncate(512 * 16)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        raid_pattern.write_pattern(handle.name, 512 * 16, True, 1_000_000)
        raid_pattern.verify_pattern(
            handle.name, 512 * 16, pattern_lba_base=1_000_000
        )
        self.assertEqual(
            raid_pattern.scan_runs(handle.name, 0, 512 * 16),
            [(0, 1_000_000, 16)],
        )


if __name__ == "__main__":
    unittest.main()
