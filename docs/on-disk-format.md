# ARC-5020 on-disk format findings

These fields and layouts were derived experimentally from an ARC-5020 running
firmware `V1.50 2012-03-05`. Unknown controller families and firmware versions
must not be assumed compatible.

## Member metadata

Metadata uses 512-byte sectors:

```text
member LBA 1: $RaidSD$
member LBA 2–7: $VolumE$ records
member LBA 520: start of logical/member data
```

Decoded `$RaidSD$` fields:

| Offset | Type | Meaning |
|---:|---|---|
| `+0x08` | LE32 | Member count |
| `+0x0c` | LE32 | Duplicate/related member-count word |
| `+0x54` | LE32 | Zero-based member index |
| `+0x60` | LE32 | Per-member Raid Set capacity in sectors |
| `+0x68` | ASCII | Raid Set name |

Decoded `$VolumE$` fields:

| Offset | Type | Meaning |
|---:|---|---|
| `+0x08` | LE32 | Logical volume sectors |
| `+0x14` | LE32 | Duplicate logical sector count |
| `+0x28` | LE16 | Stripe/chunk size in 512-byte sectors |
| `+0x2a` | LE16 | Duplicate stripe/chunk size |
| `+0x2c` | U8 | RAID-level code |
| `+0x2d` | U8 | Duplicate RAID-level code |
| `+0x34` | ASCII | Volume Set name |

Observed RAID-level codes:

| Code | Meaning |
|---:|---|
| `0` | RAID0 |
| `1` + 2 members | RAID1 |
| `1` + 4 members | RAID1+0 |
| `2` | RAID3 |
| `3` | RAID5 |

Stripe fields were independently validated with 32 KiB (`64` sectors) and
64 KiB (`128` sectors) RAID1+0 arrays. RAID3 uses a fixed value of 8 sectors,
or 4 KiB.

## RAID1

Both members contain the complete logical volume beginning at member LBA 520.
Member indices distinguish the copies. Single-member ext4 recovery and known
file checksums were verified.

## RAID1+0

For the tested four-member layout:

```text
mirror pair A: indices 0 and 1
mirror pair B: indices 2 and 3
stripe across mirror pairs
```

Pair A stores even logical stripes and pair B stores odd logical stripes.
This was verified with both 32 KiB and 64 KiB stripe configurations.

For logical sector `L`, with stripe size `C` sectors:

```text
stripe number      S = L // C
mirror group         = S % 2
packed member LBA    = 520 + (S // 2) * C + (L % C)
```

## RAID3

Three- and four-member arrays were tested:

```text
indices 0 through N-2: ordered data chunks
index N-1:             dedicated XOR parity
chunk size:            4 KiB
```

Every tested parity row matched the XOR of all data members. Recovery with
each individual member omitted was verified for both member counts.

## RAID5

The tested four-member layout is left-symmetric:

```text
row 0: data 0,1,2; parity 3
row 1: data 3,0,1; parity 2
row 2: data 2,3,0; parity 1
row 3: data 1,2,3; parity 0
```

Parity moves from the highest index downward. Logical data begins immediately
after parity and wraps around. All affected rows passed XOR validation, and
recovery with each member omitted was verified.

## Evidence and limitations

The raw captures are intentionally excluded from Git because they are large
and may contain residual disk data. Their hashes, experiment chronology, and
intermediate observations remain in the [research log](research-log.md).

Automatic tools deliberately reject unsupported or inconsistent metadata
instead of guessing. The LBA-520 offset is experimentally established for the
tested ARC-5020 layouts; it has not been decoded from a metadata field.
