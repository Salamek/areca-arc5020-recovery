# TODO

## Completed format research

### Multiple Volume Sets in one Raid Set

Status: completed for RAID0, RAID1, RAID1+0, RAID3, and RAID5.

The ARC-5020 can create multiple Volume Sets inside one Raid Set. Member
LBAs 2 through 7 contain 128-byte packed `$VolumE$` records. The parser
reports all packed slots, and the universal tool selects by index or name.

Observed fields:

- `+0x0c` and `+0x18`: duplicate allocation-offset values;
- allocation unit is 512 sectors (256 KiB);
- member start is `520 + allocation_offset * 512` sectors;
- `+0x2f`: host drive mapping (observed values 8 and 9);
- `+0x33`: zero-based Volume Set index.

The equal-sized sample contains:

- Volume A: 1,952,768 sectors, allocation value 0, verified start LBA 520;
- Volume B: 1,952,768 sectors, allocation value 3815, verified start
  LBA 1,953,800.

Completed controlled experiment:

1. Create a two-member RAID1 Raid Set. RAID1 avoids stripe/parity ambiguity.
2. Create two Volume Sets with distinct names. Equal-sized volumes were used.
3. Map them to separate iSCSI targets, such as USB/8 and USB/9.
4. Capture and decode the first 4 KiB of one physical member. Completed.
5. Extend `raid_pattern.py` with a per-volume pattern LBA base. Completed.
6. Write and verify a distinct 16 MiB pattern on each Volume Set. Completed.
7. Locate both patterns on one RAID1 member. Completed at LBAs 520 and
   1,953,800.
8. Repeat with RAID0, RAID1+0, RAID3, and RAID5. Completed; row/stripe
   numbering restarts for each Volume Set.
9. Add `--volume INDEX_OR_NAME` to `areca_raid.py` and a library API for
   selecting Volume Sets. Completed.

All currently supported RAID layouts accept Volume Set selection by index or
exact name.

End-to-end 16 MiB reconstructions of both tested RAID1 Volume Sets passed
their distinct pattern verification.

Still untested:

- whether a single Raid Set can mix RAID levels or stripe sizes between its
  Volume Sets;
- how deletion, resizing, or non-sequential allocation affects metadata.

## Possible future experiments

### Writable live RAID1+0, RAID3, and RAID5 devices

Status: out of scope for the current recovery-focused project.

The decoded layouts are sufficient for writes, but the current active-device
backend uses direct device-mapper targets. Those targets cannot preserve all
required redundancy:

- RAID1+0 writes must update both members of the selected mirror pair.
- RAID3 writes must update the data member and dedicated parity.
- RAID5 writes must update the data member and the row's rotating parity.

A future implementation would require:

1. Random-access logical `pread`/`pwrite` APIs in the `areca` library.
2. Request splitting at stripe/chunk boundaries.
3. An NBD or ublk block-device backend.
4. Serialized read-modify-write handling for partial RAID3/RAID5 stripes:

   ```text
   new parity = old parity XOR old data XOR new data
   ```

5. Direct parity calculation for full-stripe writes.
6. Mirrored write fan-out for RAID1+0.
7. Flush/fsync propagation to every affected member.
8. Defined behavior for discard, write-zeroes, FUA, and member write errors.
9. Testing for concurrent writes and mid-update failures.

Even a functional implementation would retain a RAID write-hole risk unless
it added a journal or another crash-consistency mechanism. It would therefore
be an interesting experiment, but has little practical value for the current
goal of safe data recovery.

The supported approach remains:

- expose directly representable recovery mappings read-only; or
- reconstruct the logical array into a separate image or output block device.
