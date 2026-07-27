# Areca ARC-5020 recovery tools

Experimental Linux tools for inspecting and reconstructing member disks from
an Areca ARC-5020 external RAID enclosure.

The project documents the enclosure's usable but partially hidden iSCSI
implementation and experimentally verified on-disk layouts for:

- RAID1
- Four-member RAID1+0 with metadata-defined stripe size
- Three- and four-member RAID3
- Four-member left-symmetric RAID5

It is based on an ARC-5020 running firmware `V1.50 2012-03-05`. This project
is not affiliated with Areca.

## Status

| Layout | Metadata detection | Reconstruction | One missing member |
|---|---:|---:|---:|
| RAID1, 2 members | Yes | Read-only loop mapping | Yes |
| RAID1+0, 4 members | Yes | Image and read-only device mapper | One member per mirror pair required |
| RAID3, 3 or 4 members | Yes | Image | Yes |
| RAID5, 4 members | Yes | Image | Yes |

Reconstruction was validated against deterministic logical-LBA patterns.
RAID1 recovery was additionally verified using an ext4 filesystem and known
file checksums. The complete test suite uses generated temporary fixtures and
does not require private disk captures.

## Tools

| Tool | Purpose |
|---|---|
| `areca_member.py` | Inspect metadata and map a validated RAID1 member |
| `areca_raid10.py` | Reconstruct four-member RAID1+0 |
| `areca_raid3.py` | Reconstruct three- or four-member RAID3 |
| `areca_raid5.py` | Reconstruct four-member RAID5 |
| `raid_pattern.py` | Generate, verify, and scan deterministic test patterns |
| `areca_iscsi_init.sh` | Configure/login with conservative iSCSI parameters |
| `areca_iscsi_limits.sh` | Apply runtime block queue limits |
| `areca_iscsi_deinit.sh` | Log out and remove the configured node |

The tools require only Python's standard library and common Linux storage
utilities.

## Quick start

Inspect member images or disks:

```bash
./areca_member.py --json /path/to/member
```

Reconstruct RAID1+0 from one healthy member in each mirror pair:

```bash
./areca_raid10.py reconstruct recovered.img member0 member2
```

Reconstruct RAID3 or RAID5 from all members or all but one:

```bash
./areca_raid3.py recovered.img member0 member1 member2
./areca_raid5.py recovered.img member0 member1 member3
```

Run tests:

```bash
python -m unittest -v
```

See the [recovery guide](docs/recovery.md) for supported combinations,
device-mapper usage, and safety requirements.

## Important safety warning

These are experimental recovery tools. A wrong layout assumption can produce
plausible-looking but corrupted output.

- Work on disk images or clones where possible.
- Keep source members and recovered filesystems read-only.
- Identify members using embedded metadata, not `/dev/sdX` ordering.
- Review parser warnings and stop on inconsistent metadata.
- `raid_pattern.py write` is destructive and exists only for controlled test
  arrays.

Unknown Areca models, firmware versions, RAID member counts, multiple Volume
Sets, and untested layouts are intentionally rejected where possible.

## Documentation

- [Recovery tool guide](docs/recovery.md)
- [Decoded on-disk format and RAID layouts](docs/on-disk-format.md)
- [iSCSI export and Linux initiator workaround](docs/iscsi.md)
- [Chronological research log and experimental evidence](docs/research-log.md)

Raw member captures and downloaded firmware are excluded from Git because they
are large, potentially contain residual user data, and may not be
redistributable.
