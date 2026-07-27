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

    def test_verifies_raid3_parity(self) -> None:
        chunk_sectors = 8
        chunks = []
        for member in range(3):
            chunks.append(
                b"".join(
                    raid_pattern.make_sector(member * chunk_sectors + sector)
                    for sector in range(chunk_sectors)
                )
            )
        parity = raid_pattern.xor_blocks(chunks)
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(parity)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name))
        raid_pattern.verify_raid3_parity(
            handle.name, 0, len(parity), pattern_lba_base=0
        )
        with open(handle.name, "r+b") as stream:
            stream.seek(17)
            original = stream.read(1)
            stream.seek(17)
            stream.write(bytes([original[0] ^ 1]))
        with self.assertRaises(raid_pattern.PatternError):
            raid_pattern.verify_raid3_parity(
                handle.name, 0, len(parity), pattern_lba_base=0
            )

    def test_verifies_raid5_data_and_parity_members(self) -> None:
        chunk_sectors = 2
        chunk_bytes = chunk_sectors * 512
        member_data = [bytearray() for _ in range(4)]
        for row in range(4):
            parity_index, data_order = raid_pattern.raid5_row_layout(row, 4)
            blocks = []
            for position in range(3):
                first_lba = (row * 3 + position) * chunk_sectors
                blocks.append(
                    b"".join(
                        raid_pattern.make_sector(first_lba + sector)
                        for sector in range(chunk_sectors)
                    )
                )
            for position, member_index in enumerate(data_order):
                member_data[member_index].extend(blocks[position])
            member_data[parity_index].extend(raid_pattern.xor_blocks(blocks))

        paths = []
        for data in member_data:
            handle = tempfile.NamedTemporaryFile(delete=False)
            handle.write(data)
            handle.close()
            paths.append(handle.name)
            self.addCleanup(lambda path=handle.name: os.unlink(path))

        for member_index, path in enumerate(paths):
            raid_pattern.verify_raid5_member(
                path,
                0,
                4 * chunk_bytes,
                0,
                member_index,
                chunk_sectors=chunk_sectors,
            )


if __name__ == "__main__":
    unittest.main()
