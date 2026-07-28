# Areca ARC-5020 recovery tools

[![CI](https://github.com/Salamek/areca-arc5020-recovery/actions/workflows/ci.yml/badge.svg)](https://github.com/Salamek/areca-arc5020-recovery/actions/workflows/ci.yml)

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

| Layout | Metadata detection | Reconstruction | Degraded input |
|---|---:|---:|---:|
| RAID0, 4 members | Yes | Image and device mapper | No |
| RAID1, 2 members | Yes | Image, loop, and device mapper | One surviving member |
| RAID1+0, 4 members | Yes | Image and read-only device mapper | One member from each mirror pair |
| RAID3, 3 or 4 members | Yes | Image | One member may be missing |
| RAID5, 4 members | Yes | Image | One member may be missing |

Reconstruction was validated against deterministic logical-LBA patterns.
RAID1 recovery was additionally verified using an ext4 filesystem and known
file checksums. The primary RAID1+0 recovery workflow was validated end to
end using physical members from different mirror pairs: the tool created a
read-only device-mapper reconstruction, Linux recognized the ext4 filesystem,
and a recovered 2 GiB file matched its original SHA-256 checksum. The complete
test suite uses generated temporary fixtures and does not require private disk
captures.

## Tools

| Tool | Purpose |
|---|---|
| `areca_member.py` | Inspect metadata and map a validated RAID1 member |
| `areca_raid.py` | Universal auto-detection and reconstruction CLI |
| `raid_pattern.py` | Generate, verify, and scan deterministic test patterns |
| `areca_iscsi.sh` | Login and automatically apply conservative iSCSI limits |
| `areca_iscsi_discover.sh` | Run SendTargets discovery for a portal |
| `areca_iscsi_logout.sh` | Log out one exact target and portal |

The tools require only Python's standard library and common Linux storage
utilities.

Use directly from a checkout, or install the library and console commands:

```bash
python -m pip install .
```

## Quick start

Inspect member images or disks:

```bash
./areca_member.py --json /path/to/member
```

Reconstruct RAID1+0 from one healthy member in each mirror pair:

```bash
./areca_raid.py inspect --json member0 member2
./areca_raid.py reconstruct recovered.img member0 member2
```

Select one Volume Set when a Raid Set contains several:

```bash
./areca_raid.py inspect --volume 1 member0 member2
./areca_raid.py reconstruct recovered.img member0 member2 \
  --volume ARC-5020-VOL#01
```

Reconstruct RAID3 or RAID5 from all members or all but one:

```bash
./areca_raid.py reconstruct recovered-raid3.img member0 member1 member2
./areca_raid.py reconstruct recovered-raid5.img member0 member1 member3
```

Run tests:

```bash
python -m unittest discover -s tests -v
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

Unknown Areca models, firmware versions, RAID member counts, and untested
layouts are intentionally rejected where possible. Multiple Volume Sets are
supported for every experimentally verified layout: RAID0, RAID1, RAID1+0,
RAID3, and RAID5.

## Documentation

- [Recovery tool guide](docs/recovery.md)
- [Python library and universal assembler](docs/library.md)
- [Decoded on-disk format and RAID layouts](docs/on-disk-format.md)
- [iSCSI export and Linux initiator workaround](docs/iscsi.md)
- [Chronological research log and experimental evidence](docs/research-log.md)
- [Out-of-scope ideas and future experiments](TODO.md)

## License

Copyright (C) 2026 ARC-5020 recovery contributors.

This project is free software licensed under the
[GNU General Public License version 3 or later](LICENSE). It is distributed
without any warranty; see the license for details.
