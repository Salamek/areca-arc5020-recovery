# Python library and universal assembler

The `areca` package contains all metadata parsing, member validation, layout
mapping, degraded reads, and reconstruction logic. Command-line tools import
the package; they do not import implementation from one another.

Install from a checkout with:

```bash
python -m pip install .
```

This provides the `areca-raid`, `areca-member`, and `areca-raid-pattern`
commands. There are no runtime Python dependencies outside the standard
library.

## Library API

Inspect one member:

```python
from areca import inspect

metadata = inspect("/path/to/member")
print(metadata.member_index)
print(metadata.volumes[0].raid_level_code)
```

Auto-assemble an array:

```python
from areca import ArecaArray

array = ArecaArray.assemble([
    "/path/to/member0",
    "/path/to/member2",
    "/path/to/member3",
])

print(array.level)
print(array.supplied_indices)
print(array.logical_bytes)
```

For a Raid Set containing multiple Volume Sets, select one by zero-based
metadata index or exact name:

```python
array = ArecaArray.assemble(member_paths, volume=1)
array = ArecaArray.assemble(member_paths, volume="MULTI-VOL-B")
```

Omitting the selector on a multi-volume member is rejected with a list of
available indices and names.

Reconstruct to a new image:

```python
array.reconstruct("recovered.img")
```

The assembler:

- parses `$RaidSD$` and `$VolumE$`;
- normalizes the member-index field and fingerprints metadata to prevent
  accidental mixing of different arrays;
- auto-detects RAID0, RAID1, RAID1+0, RAID3, or RAID5;
- validates the required surviving-member set;
- derives chunk size and logical length from metadata;
- provides degraded logical reads for the verified redundant layouts.

## Universal CLI

Inspect and auto-detect:

```bash
./areca_raid.py inspect member0 member2 member3
./areca_raid.py inspect --json member0 member2 member3
./areca_raid.py inspect --volume MULTI-VOL-B member0
```

Reconstruct to a new image:

```bash
./areca_raid.py reconstruct recovered.img member0 member2 member3
```

Select a Volume Set in any supported multi-volume Raid Set:

```bash
./areca_raid.py reconstruct recovered-b.img member0 \
  --volume MULTI-VOL-B
```

Limit reconstruction for a partial capture or test:

```bash
./areca_raid.py reconstruct recovered.img member0 member2 \
  --bytes 64MiB
```

Write the reconstructed logical array to an existing block device:

```bash
sudo ./areca_raid.py reconstruct /dev/target member0 member2 member3 \
  --i-understand-this-overwrites-the-output-device
```

This is destructive to the output device. The tool rejects mounted output
devices, requires an explicit acknowledgement, checks target size, and opens
all input members read-only.

## Active device mappings

Preview a direct device-mapper table:

```bash
sudo ./areca_raid.py dm-table /dev/member0 /dev/member2
```

Create it read-only:

```bash
sudo ./areca_raid.py create-dm arc5020-recovery \
  /dev/member0 /dev/member2
```

Direct device-mapper targets are available only where the verified layout can
be represented without custom parity code:

- RAID0: striped target;
- RAID1: linear view of one surviving mirror;
- RAID1+0: striped view over one surviving member from each mirror pair.

RAID3 and RAID5 can be reconstructed to an image or output block device, but
are not exposed as live virtual devices by this dependency-free version.

Writable active mapping is allowed only for a complete RAID0 set:

```bash
sudo ./areca_raid.py create-dm arc5020-live /dev/member0 /dev/member1 ... \
  --writable \
  --i-understand-writes-modify-member-disks
```

Writable RAID1/RAID1+0 mappings would update only selected mirrors, while
RAID3/RAID5 require parity-aware writes. Those unsafe incomplete modes are
explicitly refused.

## Supported layouts

| Layout | Required inputs |
|---|---|
| RAID0 | Every member |
| RAID1 | At least one member |
| Four-member RAID1+0 | One member from 0/1 and one from 2/3 |
| Three-/four-member RAID3 | All members or one missing |
| Four-member RAID5 | All members or one missing |

RAID0 metadata and simple round-robin striping were experimentally confirmed
on all four members using distinct LBA-addressed patterns.

Multiple Volume Sets are supported on RAID0, RAID1, RAID1+0, RAID3, and
RAID5. Packed metadata, allocation offsets, per-volume row restart, dedicated
RAID3 parity, and rotating RAID5 parity are experimentally verified.
