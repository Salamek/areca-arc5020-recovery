# Recovery tool guide

All reconstruction tools open member inputs read-only and refuse inconsistent
metadata. Output image paths must not already exist. Work from full-disk
images or cloned disks whenever possible.

For new workflows, prefer the auto-detecting universal CLI:

```bash
./areca_raid.py inspect --json member0 member2 member3
./areca_raid.py reconstruct recovered.img member0 member2 member3
```

For any supported multi-volume member set, select a Volume Set by index or
exact name:

```bash
./areca_raid.py inspect --volume MULTI-VOL-B member0
./areca_raid.py reconstruct recovered-b.img member0 \
  --volume MULTI-VOL-B
```

See the [library and universal assembler guide](library.md).

## Inspect a member

```bash
./areca_member.py /dev/sdX
./areca_member.py --json /dev/sdX
```

The parser reports member count/index, volume size, RAID code, stripe size,
and any validation warnings.

For a validated two-member RAID1 member, create a read-only loop mapping:

```bash
sudo ./areca_member.py --create-loop /dev/sdX
```

The tool derives the offset from an embedded primary GPT when possible. It
refuses writable mapping unless `--writable-loop` is explicitly supplied.

## RAID1+0

Supply one healthy member from indices 0/1 and one from indices 2/3:

```bash
./areca_raid.py reconstruct recovered.img member0 member2
```

Limit output while testing partial captures:

```bash
./areca_raid.py reconstruct recovered.img member0 member2 --bytes 64MiB
```

Preview a device-mapper table for two complete physical members:

```bash
sudo ./areca_raid.py dm-table \
  /dev/disk/by-id/member-from-0-or-1 \
  /dev/disk/by-id/member-from-2-or-3
```

Create the mapping read-only:

```bash
sudo ./areca_raid.py create-dm arc5020-recovery \
  /dev/disk/by-id/member-from-0-or-1 \
  /dev/disk/by-id/member-from-2-or-3
```

Remove it afterward:

```bash
sudo dmsetup remove arc5020-recovery
```

## RAID3

The universal tool supports the experimentally verified three- and
four-member RAID3 layouts. Supply all members or all but one:

```bash
./areca_raid.py reconstruct recovered.img member0 member1 member2
./areca_raid.py reconstruct recovered.img member0 member2
```

The highest index is dedicated parity. If a data member is missing, its chunk
is recovered using the surviving data members and parity.

## RAID5

The tool supports the verified four-member left-symmetric layout. Supply all
members or any three:

```bash
./areca_raid.py reconstruct recovered.img member0 member1 member2 member3
./areca_raid.py reconstruct recovered.img member0 member2 member3
```

A missing data chunk is reconstructed from the three surviving row chunks.

## Pattern utility

`raid_pattern.py` generated the deterministic test streams used to derive the
layouts. Writing is destructive and requires an explicit acknowledgement:

```bash
sudo ./raid_pattern.py write /dev/sdX \
  --bytes 64MiB \
  --i-understand-this-destroys-data
```

Verify a logical device or reconstructed image:

```bash
./raid_pattern.py verify recovered.img --bytes 64MiB
```

Scan a member capture for encoded logical-LBA runs:

```bash
./raid_pattern.py scan member.img --offset 266240 --bytes 64MiB
```

Verify a RAID3 dedicated-parity member against the deterministic pattern:

```bash
./raid_pattern.py verify-raid3-parity parity-member \
  --offset 266240 \
  --bytes 32KiB \
  --pattern-lba-base 0
```

Verify one RAID5 member, including its rotating data/parity roles:

```bash
./raid_pattern.py verify-raid5-member member0 \
  --member-index 0 \
  --offset 266240 \
  --bytes 512KiB \
  --pattern-lba-base 0
```

## Verification

Run the standard-library test suite:

```bash
python -m unittest discover -s tests -v
```

Tests create synthetic temporary member images and do not depend on the
ignored raw captures or downloaded firmware.

## Safety

- Verify member identity and index before every operation.
- Never infer member order from `/dev/sdX` names.
- Keep original disks and filesystem mounts read-only.
- Do not initialize, repair, or mount an unknown reconstructed filesystem
  read-write.
- Clone failing disks before reconstruction.
- These tools cover only the exact layouts documented in
  [on-disk-format.md](on-disk-format.md).
