# ARC-5020 research log

This is the chronological investigation log from which the project tools and
concise documentation were derived. It preserves experimental details,
hardware identifiers, command output, hashes, and intermediate conclusions.
For normal use, start with the project [README](../README.md).

Investigate an Areca ARC-5020 external RAID enclosure on my local network and determine whether its partially documented iSCSI functionality can actually export a Volume Set.

Device details:

* Model: Areca ARC-5020
* IP address: `192.168.1.235`
* Firmware currently installed: `V1.50 2012-03-05`
* Latest known official firmware available locally: `V1.46 2009/5/18`
* The origin of V1.50 is uncertain; it was likely installed during an earlier
  attempt to enable iSCSI.
* Working assumption: V1.46 and V1.50 are likely similar in the components
  relevant to this investigation, but this should be verified where firmware
  differences could affect a conclusion.
* Management interfaces:

  * Web interface
  * Telnet interface, but Telnet opens a proprietary TUI similar to the web interface, not a shell
* Ethernet management works
* TCP port `3260` is open
* Firmware exposes this configuration page:

```text
iSCSI Configuration
iSCSI TargetNode Base Name:
iqn.2000-01.com.abc.xyz:group

iSCSI Port Number:
3260
```

Areca originally promised iSCSI support in a future firmware 2.0 release, but that firmware apparently never became publicly available. The current firmware may contain a partial or hidden iSCSI implementation.

The management menu contains:

```text
Raid Set Functions
- Create Raid Set
- Delete Raid Set
- Expand Raid Set
- Offline Raid Set
- Rename Raid Set
- Activate Raid Set
- Create Hot Spare
- Delete Hot Spare
- Rescue Raid Set

VolumeSet Functions
- Create Volume Set
- Delete Volume Set
- Modify Volume Set
- Check Volume Set
- Schedule Volume Check
- Stop Volume Set Check

Physical Drives
- Create Pass Through
- Modify Pass Through
- Delete Pass Through
- Identify Drive

System Controls
- System Config
- iSCSI Config
- EtherNet Config
- Alert By Mail Config
- SNMP Configuration
- NTP Configuration
- View Events/Mute Beeper
- Generate Test Event
- Clear Event Buffer
- Modify Password
- Upgrade Firmware
- Shutdown Controller
- Restart Controller
```

Current storage state:

* A RAID Set and Volume Set have now been created.
* The Volume Set completed background initialization.
* Before the RAID Set and Volume Set existed, iSCSI discovery returned no targets.
* After initialization completed, the controller was restarted and SendTargets
  discovery was tested again.
* Discovery still returned `iscsiadm: No portals found`; initialization and a
  controller restart therefore did not cause a target to be advertised.

Observed iSCSI behavior:

```bash
iscsiadm -m discovery -t sendtargets -p 192.168.1.235 -d 8
```

Important debug output:

```text
connected to discovery address 192.168.1.235
discovery session to 192.168.1.235:3260 starting iSCSI login

SessionType=Discovery
HeaderDigest=None
DataDigest=None
ErrorRecoveryLevel=0
MaxRecvDataSegmentLength=32768

TargetPortalGroupTag=1
login response status 0000
discovery login success to 192.168.1.235

SendTargets=All

received text response, 0 data bytes
iscsiadm: No portals found
```

Interpretation:

* The service on port 3260 is a real iSCSI implementation.
* Discovery login succeeds.
* It negotiates valid iSCSI parameters.
* It returns a valid but empty response to `SendTargets=All`.
* No targets are currently advertised.

Stage 3 web-interface and manual findings:

* The live web interface was inspected read-only after Volume Set
  initialization and restart.
* System Information confirms firmware and BOOT ROM
  `V1.50 2012-03-05`, a 400 MHz Marvell 88F5182 processor, and 128 MB
  memory.
* The healthy Volume Set is currently assigned to `SATA/0`. Its information
  page reports `SATA/0`, `Normal`, and `Current SATA Xfer Mode: Not Linked`.
* The second-stage Modify Volume Set form exposes channel choices `SATA`,
  `USB`, and `SATA&USB`, plus drive numbers 0 through 15. Its help text labels
  4 through 15 reserved for the visible eSATA and USB modes, but the official
  ARC-5020 v2.0 manual documents the missing iSCSI interpretation.
* Official ARC-5020 v2.0 manual:
  `https://www.areca.us/support/download/5BaySubSystem/Manual_Spec/ARC-5020_Manual.zip`
* The manual defines the host mapping as:

  * Channel 0 (`SATA`): eSATA uses drive numbers 0 through 3.
  * Channel 1 (`USBiA`, displayed as `USB` in the web form): USB 2.0 uses
    drive numbers 0 through 7; iSCSI/AoE uses drive numbers 8 through 15.
  * The eight iSCSI target nodes are named `BaseName-xx`, where `xx` is
    8 through 15, and each target uses LUN 0.

* Therefore the former `SATA/0` assignment was not in the iSCSI export range
  and explained why SendTargets returned an empty response.
* Read-only SCSI INQUIRY/login probes against the documented names
  `iqn.2000-01.com.abc.xyz:group-08` through
  `iqn.2000-01.com.abc.xyz:group-15`, LUN 0, all failed while no Volume Set
  was assigned to drive number 8 through 15.
* The Volume Set was subsequently modified from `SATA/0` to channel `USB`,
  drive number `8`. SendTargets then immediately advertised:

  ```text
  192.168.1.235:3260,1 iqn.2000-01.com.abc.xyz:group-08
  ```

* A read-only SCSI INQUIRY to LUN 0 succeeded and returned:

  ```text
  Peripheral Device Type: DIRECT_ACCESS
  Vendor: Areca
  Product: ARC-5020-VOL#00
  Revision: R001
  ```

* This confirms that firmware V1.50 has a usable iSCSI target implementation,
  target `iqn.2000-01.com.abc.xyz:group-08`, portal
  `192.168.1.235:3260`, portal group tag 1, and LUN 0.
* A Debian open-iscsi initiator successfully logged in and attached the LUN:

  ```text
  scsi 7:0:0:0: Direct-Access Areca ARC-5020-VOL#00 R001 PQ: 0 ANSI: 5
  sd 7:0:0:0: [sdi] 1953124864 512-byte logical blocks: (1000 GB/931 GiB)
  sd 7:0:0:0: [sdi] Write Protect is off
  sd 7:0:0:0: [sdi] Write cache: enabled, read cache: enabled,
               doesn't support DPO or FUA
  sd 7:0:0:0: [sdi] Attached SCSI disk
  ```

* At that time the device node was `/dev/sdi`; this name is not guaranteed to
  remain stable across reconnects or reboots. Use a filesystem UUID, PARTUUID,
  or another persistent `/dev/disk/by-*` identifier for future mounting.
* Read-only inspection with `lsblk -f`, `blkid`, and `fdisk -l` found no
  partition table, filesystem signature, label, or UUID. The exported LUN is
  currently a blank 999,999,930,368-byte block device (1,953,124,864 logical
  sectors of 512 bytes).
* The target reports volatile write caching but no Force Unit Access (FUA)
  support. Before trusting it with important data, verify flush/barrier
  behavior and the enclosure's protection against power loss. Do not disable
  filesystem barriers merely for performance.
* The official manual indicates that a physical disk configured as an Areca
  `Pass-Through Disk` has the same Host Channel and Drive Number attributes as
  a Volume Set, and refers to the Volume Set mapping rules for those fields.
  Consequently, an unused physical disk could likely be exported individually
  over iSCSI by creating it as a pass-through disk on channel `USB` with drive
  number 8 through 15. This has not been tested, because both installed disks
  are members of the current RAID Set and removing them would be destructive.
* Although individual iSCSI pass-through disks may be technically possible,
  they are poor ZFS candidates: the ARC-5020 remains an intervening storage
  controller, reports write cache without FUA, may obscure native drive error
  and SMART behavior, and puts all disks behind one controller/network failure
  domain. Prefer ZFS on disks attached to a true HBA/JBOD path.
* A sustained write test exposed a serious firmware iSCSI protocol bug. During
  a roughly 10 GB copy, the Linux initiator repeatedly reported invalid
  Ready-To-Transfer (R2T) PDUs, for example:

  ```text
  invalid R2T with data len 12288 at offset 1044480
  and total length 1048576
  detected conn error (1006)
  ```

  The requested R2T range exceeds the command's total transfer length, so the
  initiator rejects it and resets the connection. Repeated recovery attempts
  failed, the SCSI device was taken offline, writes returned
  `DID_TRANSPORT_DISRUPTED`, and ext4 aborted its journal and remounted
  read-only. This is evidence that discovery/login and small I/O work, but
  firmware V1.50 is not reliable with the initiator's default large-I/O and
  burst negotiation. Test conservative `MaxBurstLength`, block request size,
  queue depth, and command-count limits before treating the target as usable.
* Parameters captured after the failure:

  ```text
  Negotiated:
    MaxRecvDataSegmentLength: 262144
    MaxXmitDataSegmentLength: 65536
    FirstBurstLength: 0
    MaxBurstLength: 262144
    ImmediateData: No
    InitialR2T: Yes
    MaxOutstandingR2T: 1

  Initiator/block layer:
    node.session.cmds_max: 128
    node.session.queue_depth: 32
    /sys/block/sdi/queue/max_sectors_kb: 1280
    /sys/block/sdi/queue/max_hw_sectors_kb: 32767
    /sys/block/sdi/queue/nr_requests: 226
    /sys/block/sdi/device/queue_depth: 32
  ```

  The malformed R2Ts occurred near the end of commands around 1 MiB or
  larger. The next compatibility test should begin with 128 KiB maximum block
  requests, queue depth 1, 16 maximum commands, and a 128 KiB negotiated
  MaxBurstLength, then relax one limit at a time only after sustained writes
  and checksum verification succeed.
* After clearing the wedged iSCSI state, reconnecting with conservative
  settings, and keeping the filesystem unmounted, `e2fsck -f /dev/sdi1`
  successfully recovered the ext4 journal. It corrected mismatched free-block
  and free-inode counters:

  ```text
  ARC5020_TEST: ***** FILE SYSTEM WAS MODIFIED *****
  ARC5020_TEST: 22/61038592 files, 4117769/244140288 blocks
  ```

  No inode, directory-structure, or connectivity repairs were reported in
  that pass. Run a second forced check until it completes without modifying
  the filesystem before mounting it again.
* The conservative reconnect was verified successfully:

  ```text
  iSCSI Connection State: LOGGED IN
  iSCSI Session State: LOGGED_IN
  LUN state: running
  MaxBurstLength: 131072
  InitialR2T: Yes
  ImmediateData: No
  /sys/block/sdi/queue/max_sectors_kb: 128
  /sys/block/sdi/device/queue_depth: 1
  ```

  These runtime sysfs limits must be reapplied after every LUN attachment
  unless automated with an appropriate device rule or login script.
* With that conservative profile active, both a 1 GiB write/checksum test and
  a subsequent 10 GiB write/checksum test completed successfully without the
  earlier R2T failure. This is initial evidence that limiting request/burst
  size avoids the V1.50 firmware bug. Longer-duration mixed-I/O and reconnect
  tests are still required before calling the workaround production-safe.

RAID1 member recovery findings:

* One RAID1 member was cleanly removed and attached directly to Linux as a
  kernel-read-only disk. It was identified as `SAMSUNG HD103SI`, serial
  `S1Y5J90B205357`, capacity 1,000,204,886,016 bytes.
* Member LBA 0 is not the start of the exported Volume Set. It still contains
  an older DOS partition table with two type-0x07 partitions; these apparent
  `/dev/sdc1` and `/dev/sdc2` devices are unrelated to the current iSCSI
  Volume Set and must not be mounted.
* Areca metadata starts at physical byte `0x200` with signature `$RaidSD$`.
  Volume metadata begins at byte `0x400` with signature `$VolumE$` and embeds
  `ARC-5020-VOL#00`.
* The GPT signature written to exported-volume byte 512 was found at member
  byte 266,752. Therefore the exported Volume Set begins at member byte
  266,240, which is exactly 520 physical sectors:

  ```text
  member byte offset = 520 * 512 = 266240
  member byte 266752 - volume byte 512 = 266240
  ```

* This offset is independently confirmed by the ext4 label. `ARC5020_TEST`
  occurs at member byte 1,315,960, exactly 266,240 bytes after its expected
  location within the exported disk/partition.
* Preliminary recovery method: expose a read-only 999,999,930,368-byte loop
  device backed by the member beginning at offset 266,240, scan its GPT, and
  mount its first partition with `ro,noload`. Verify known file checksums
  before considering the recovery method confirmed.

Reboot/resume checkpoint (2026-07-26):

* Investigation is paused immediately before creating the offset loop device.
* The removed RAID1 member is:

  ```text
  Model:  SAMSUNG HD103SI
  Serial: S1Y5J90B205357
  Size:   1,000,204,886,016 bytes
  ```

* It appeared as `/dev/sdc` before reboot, but the device name must not be
  assumed after reboot. Resolve it by serial through `/dev/disk/by-id` or
  `lsblk`.
* The physical disk was kernel-read-only before reboot, but that flag and the
  temporary device ACL do not survive reboot.
* Loop setup failed only because the running Arch kernel
  `7.1.2-arch3-1` had no matching `loop` module in `/lib/modules`. The source
  disk and calculated offset were not the cause. Reboot into a kernel with its
  matching modules, then continue as follows:

  ```bash
  uname -r
  ls /usr/lib/modules
  lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,RO,MOUNTPOINTS

  DISK=/dev/disk/by-id/ata-SAMSUNG_HD103SI_S1Y5J90B205357
  readlink -f "$DISK"

  sudo blockdev --setro "$DISK"
  sudo blockdev --getro "$DISK"       # must print 1
  sudo modprobe loop

  sudo losetup --find --show \
    --read-only \
    --partscan \
    --offset 266240 \
    --sizelimit 999999930368 \
    "$DISK"
  ```

* After `losetup` returns (expected `/dev/loop0`), do not mount the member's
  original apparent partitions. Inspect the translated device first:

  ```bash
  lsblk -f /dev/loop0
  sudo fdisk -l /dev/loop0
  ```

* Expected result: a GPT with the ext4 partition labelled `ARC5020_TEST`.
  Only then mount the translated partition without journal replay:

  ```bash
  sudo mkdir -p /mnt/arc5020-member
  sudo mount -o ro,noload /dev/loop0p1 /mnt/arc5020-member
  sudo sha256sum -c /mnt/arc5020-member/test-1GiB.sha256
  sudo sha256sum -c /mnt/arc5020-member/test-10GiB.sha256
  ```

* If both checksums pass, single-member RAID1 recovery via a fixed
  266,240-byte (520-sector) offset is confirmed.

Post-reboot recovery verification:

* After rebooting into Arch kernel `7.1.5-arch1-1`, loop support worked and
  the member was mapped at the calculated 266,240-byte offset with the
  exported-volume size limit.
* The translated GPT/ext4 partition was mounted separately and the recovered
  1 GiB test file produced:

  ```text
  Expected: 8c2ed95f537b8d3b69ce48f2c3981f62875facef52c493d4d696c365d9d123d7
  Actual:   8c2ed95f537b8d3b69ce48f2c3981f62875facef52c493d4d696c365d9d123d7
  ```

  This proves that the 520-sector offset recovers actual Volume Set file data
  correctly from this single RAID1 member.
* The recovered 10 GiB test file also matched:

  ```text
  Expected: 732377e7f4a2abdc13ddfa1eb4c9c497fd2a2b294674d056cf51581b47dd586d
  Actual:   732377e7f4a2abdc13ddfa1eb4c9c497fd2a2b294674d056cf51581b47dd586d
  ```

* Conclusion: for this ARC-5020 V1.50 RAID1 Volume Set, either member contains
  an independently recoverable byte-for-byte copy of the exported logical
  volume beginning at member sector 520. Mapping exactly
  999,999,930,368 bytes from that offset reconstructs the iSCSI disk, including
  its GPT, ext4 filesystem, and verified file contents. Preserve the first 520
  sectors and the member tail because they contain Areca metadata, but exclude
  them from the reconstructed logical volume.

Automated member inspection and mapping:

* `areca_member.py` is an experimental, standard-library-only Python utility
  for this metadata family. It opens the source read-only for inspection.
* Detection requires both of the observed Areca signatures at their expected
  locations:

  ```text
  member LBA 1: $RaidSD$
  member LBA 2..7: $VolumE$
  ```

* Validated metadata fields for this member:

  * Raid record `+0x08`, little-endian 32-bit: member count (`2`).
  * Raid record `+0x54`, little-endian 32-bit: zero-based member index.
    Comparison of both RAID1 members found `0` on the Samsung member and `1`
    on the Seagate member; this was the only difference in the two 1 KiB Areca
    metadata areas.
  * Raid record `+0x60`, little-endian 32-bit: Raid Set capacity in sectors
    (`1,953,125,376`).
  * Volume record `+0x08`, little-endian 32-bit: exported logical length in
    sectors (`1,953,124,864`).
  * Volume record `+0x14`: duplicate logical sector count used as a
    consistency check.
  * Volume record `+0x28` and `+0x2a`, little-endian 16-bit: duplicate stripe
    size fields in 512-byte sectors. Both were `0x0080` for the 64 KiB RAID10
    and changed to `0x0040` when the otherwise equivalent array was recreated
    with a 32 KiB stripe. RAID1 also retains this configured value even though
    it does not use striping.
    The 32 KiB metadata reference is:

    ```text
    samples/raid10-32k/member0-S1Y5J90B205357-first-4KiB.bin
    SHA256 25160cfb281147800b0e54fed18a23552853767546425559c292ab8306c29629
    ```
  * Volume record `+0x2c` and `+0x2d`: duplicate RAID-level/family code bytes.
    The controlled 32 KiB comparison found `01 01` on RAID1+0 and `00 00` on
    RAID0. A two-member RAID1 sample also contains `01 01`, so code `1`
    denotes the RAID1 family. This ARC-5020 firmware offers no RAID1E option,
    so code `1` plus two members identifies RAID1 and code `1` plus four
    members identifies RAID1+0. Controlled four-member RAID3 and RAID5
    samples contain `02 02` and `03 03`, respectively. The complete observed
    mapping is therefore code `0` = RAID0, code `1` = RAID1 family, code `2`
    = RAID3, and code `3` = RAID5. The metadata references are:

    ```text
    samples/raid0-32k/member0-S1Y5J90B205357-first-4KiB.bin
    SHA256 1786a0ef0f5d3ed82b6a17e2aa355818e4cf4fdb404660d54df3dba85908315d

    samples/raid5-32k/member0-S1Y5J90B205357-first-4KiB.bin
    SHA256 73b9c46338c65af54b042f709239321b6431c9ff4852928e79b1b44ba28e8160

    samples/raid3/member0-S1Y5J90B205357-first-4KiB.bin
    SHA256 b9e9ea6d29bc481c48109d765b1f21ffb152571cf917c26bcad3fa85ab768d07
    ```

    RAID3 has no user-selectable stripe size in the ARC-5020 UI. Its duplicate
    stripe fields contain `0x0008`, indicating the controller's fixed
    8-sector/4 KiB RAID3 stripe unit.
  * Raid Set name at Raid record `+0x68`; Volume Set name at Volume record
    `+0x34`.

* The member offset is not blindly hard-coded. The utility scans for a valid
  primary GPT header, reads its `current_lba`, and derives:

  ```text
  volume start = GPT member LBA - GPT current_lba
  ```

  It then validates bounds, the logical MBR signature, metadata sector counts,
  and warns if the result differs from the independently observed Areca
  520-sector convention.
* Inspect a member or image:

  ```bash
  ./areca_member.py /dev/sdX
  ./areca_member.py --json /dev/sdX
  ```

* Create a partition-scanning, read-only loop mapping:

  ```bash
  sudo ./areca_member.py --create-loop /dev/sdX
  ```

  The utility prints the created `/dev/loopN`. A writable mapping requires the
  explicit `--writable-loop` option.
* Safety/compatibility limits:

  * Automatic loop creation currently requires exactly one Volume record and
    the observed ARC-5020 RAID1 code `0x80`.
  * RAID0/3/5/10/1E, multiple Volume Sets, non-GPT logical disks, other Areca
    controller families, endianness variants, and damaged metadata are not
    yet supported.
  * Unknown layouts are inspected where possible but mapping is refused rather
    than guessed.
  * Tests are in `test_areca_member.py` and run with:

    ```bash
    python -m unittest discover -s tests -v
    ```

RAID layout experiment samples:

* RAID1 member A was captured before changing the array:

  ```text
  Model:  SAMSUNG HD103SI
  Serial: S1Y5J90B205357
  Size:   1,000,204,886,016 bytes
  ```

* Binary samples:

  ```text
  samples/raid1/S1Y5J90B205357-first-1MiB.bin
  SHA256 8944b3dffb3e788ba674bf55c19f60d7823a01cac364d97aa87bb781c625ff32

  samples/raid1/S1Y5J90B205357-last-1MiB.bin
  SHA256 30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58
  ```

  Both files are exactly 1,048,576 bytes. The final 1 MiB is all zeroes, as
  indicated by the standard SHA-256 digest for 1 MiB of zero bytes.
* RAID1 member B was captured:

  ```text
  Model:  ST1000DM003-1ER162
  Serial: Z4Y2MREM
  Size:   1,000,204,886,016 bytes

  samples/raid1/Z4Y2MREM-first-1MiB.bin
  SHA256 1961877b6de01bae1cf249c9b1604f01da5e3632f01bafcd6920988871561b2a

  samples/raid1/Z4Y2MREM-last-1MiB.bin
  SHA256 5df3047665042c44e2bcfb298d94f8c281463ce4ace81a4b134ec891adc4bd2c
  ```

* Comparing physical bytes 512 through 1535 (the two Areca metadata sectors)
  found exactly one difference: Raid record `+0x54` is `0` on member A and
  `1` on member B. This identifies the field as the zero-based member index.
* Comparing the remainder of the first 1 MiB beginning at the recovered
  logical-volume offset showed identical data on both RAID1 members.
* The final 1 MiB differs because these disks preserve unrelated historical
  data outside the Areca logical volume; no Areca tail signature was found
  there. Tail contents must not be used to infer current array data.

Four-disk RAID10 experiment:

| Expected member index | Physical channel | Capacity | Model | Serial |
|---:|---|---:|---|---|
| 0 | IDE Ch01 / top | 1000.2 GB | SAMSUNG HD103SI | S1Y5J90B205357 |
| 1 | IDE Ch02 | 1000.2 GB | ST1000DM003-1ER162 | Z4Y2MREM |
| 2 | IDE Ch03 | 2000.4 GB | ST2000DM008-2FR102 | ZK20914S |
| 3 | IDE Ch04 / bottom | 2000.4 GB | ST2000DM008-2FR102 | ZK2094Y2 |

* Test Volume Set: roughly 200 GB, 64 KiB stripe, `USB/8`, with no
  filesystem initially. A raw logical-LBA-encoded pattern will be used to
  identify stripe placement and mirror pairing.
* The firmware's exact RAID-level label is `Raid 1+0`.
* The four-disk test array/Volume Set is currently initializing; progress was
  2% when first reported.
* Initialization subsequently completed and the Volume Set reports ready for
  the raw RAID10 layout test.
* The Arch analysis host now has open-iscsi `2.1.12`, so further iSCSI work can
  run locally instead of on the separate Debian host. `iscsid` must first be
  started with root privileges on this host.
* The initialized RAID10 LUN was attached locally as `/dev/sdc`:

  ```text
  Target: iqn.2000-01.com.abc.xyz:group-08
  Product/model: ARC5020-R10TEST (truncated in lsblk output)
  Logical size: 199,999,619,072 bytes
  MaxBurstLength: 131072
  InitialR2T: Yes
  MaxOutstandingR2T: 1
  ```
* `raid_pattern.py` generates a destructive raw test pattern in which every
  512-byte sector contains sixteen validated copies of its logical LBA,
  complement, and XOR check value. It writes in 128 KiB chunks to remain
  compatible with the ARC-5020 iSCSI workaround. Its `scan` mode will later
  report the logical-LBA runs found on each physical member capture.
* Before writing, apply:

  ```bash
  echo 128 > /sys/block/sdc/queue/max_sectors_kb
  echo 1 > /sys/block/sdc/device/queue_depth
  ```

* Planned raw pattern length is 256 MiB, sufficient to cover 2,048 complete
  64 KiB stripes while keeping sequential member captures small.
* The 256 MiB pattern was written successfully and verified through the iSCSI
  LUN:

  ```text
  SHA256 df604eced653044f225f9f7c2b88870c7211d5b3c88c4681a6a983c1d782e4a9
  pattern verified
  ```

  This digest describes the complete logical pattern stream before RAID10
  striping. It can be regenerated deterministically by `raid_pattern.py`.
* RAID10 member index 0 was captured:

  ```text
  samples/raid10/member0-S1Y5J90B205357-first-512MiB.bin
  SHA256 85a1bd3fbde1e469d80280bbde406868f970071e1a98070bc610c0f27fe1bf27
  ```

  Its first pattern sector is at physical member LBA 520. From there it holds
  2,048 runs of 128 sectors (64 KiB) each. The runs begin with logical LBAs
  `0, 256, 512, 768, ...`, so member 0 contains the even-numbered logical
  stripes, packed contiguously.
* RAID10 member index 1 was captured:

  ```text
  samples/raid10/member1-Z4Y2MREM-first-512MiB.bin
  SHA256 922e45f84925f8b7df90555d5e57ef30675d5923cb70676a8c2d77c8d44f4970
  ```

  It has the same 2,048 logical-LBA runs as member 0. The entire 128 MiB
  patterned member-data region, physical LBAs 520 through 262663 inclusive,
  compares byte-for-byte identical on members 0 and 1; its SHA-256 is
  `57172d7ba39ac3ba4fb98c9158e9f65508f259b3f1045ddc70d8a41ad963618d`
  on both. This establishes member indices 0 and 1 as a mirror pair. Their
  complete 512 MiB sample hashes differ as expected because the Areca member
  index in metadata differs and sectors outside the written test area retain
  unrelated prior contents.
* RAID10 member index 2 was captured:

  ```text
  samples/raid10/member2-ZK20914S-first-512MiB.bin
  SHA256 1c7a0aebc1b886114610ab9645c464e3c35b223752156c2a0ff44d660be80a90
  ```

  It also has 2,048 contiguous 128-sector runs beginning at physical member
  LBA 520, but their logical LBAs are `128, 384, 640, 896, ...`. Member 2
  therefore contains the odd-numbered 64 KiB logical stripes. The SHA-256 of
  its complete 128 MiB patterned member-data region is
  `a5af0e85f4254eefeaf4dee163224ad3217f8dec8029c33ed268c3e37aae2f3d`.
  Together with the member 0/1 result, this shows that the ARC-5020 stripes
  across two mirror groups: `(0,1)` and `(2,3)`. Member 3 remains to be
  captured to confirm the second mirror pair directly.
* RAID10 member index 3 was captured:

  ```text
  samples/raid10/member3-ZK2094Y2-first-512MiB.bin
  SHA256 88c2e6dcfbd94febbe5cafb7b367454b34591ad7282f40e5817bfe681be53e3f
  ```

  It has the same odd-stripe logical-LBA runs as member 2. The complete
  128 MiB patterned member-data regions on members 2 and 3 compare
  byte-for-byte identical and both have SHA-256
  `a5af0e85f4254eefeaf4dee163224ad3217f8dec8029c33ed268c3e37aae2f3d`.
  This directly confirms the second mirror pair.
* The observed ARC-5020 four-member `Raid 1+0`, 64 KiB-stripe layout is:

  ```text
  mirror pair A: member indices 0 and 1
                 logical stripes 0, 2, 4, ... (logical LBAs 0, 256, 512, ...)
  mirror pair B: member indices 2 and 3
                 logical stripes 1, 3, 5, ... (logical LBAs 128, 384, 640, ...)
  physical data start on every member: LBA 520
  stripe unit: 128 sectors / 64 KiB
  ```

  A reconstructed logical sector at LBA `L` can therefore be located using
  stripe number `S = L // 128`, mirror group `S % 2`, and packed member LBA
  `520 + (S // 2) * 128 + (L % 128)`. Either member in the selected mirror
  group is a valid source when healthy.

Offline RAID10 reconstruction:

* `areca_raid10.py` implements the observed four-member layout. It inspects
  every input read-only and requires consistent Raid Set/Volume Set metadata,
  four-member RAID1-family code `0x80`, unique member indices, and at least one
  member from each mirror pair. It refuses ambiguous or same-pair-only input.
* Reconstruct an ordinary image from any healthy `0/1` member and any healthy
  `2/3` member:

  ```bash
  ./areca_raid10.py reconstruct recovered.img /path/member0 /path/member2
  ```

  `--bytes 256MiB` can limit reconstruction for testing or partial captures.
  The output path must not already exist.
* The four 512 MiB samples were tested in every valid pair combination:
  `0+2`, `0+3`, `1+2`, and `1+3`. Every reconstructed 256 MiB image passed
  sector-by-sector `raid_pattern.py verify` and produced the original logical
  pattern digest:

  ```text
  SHA256 df604eced653044f225f9f7c2b88870c7211d5b3c88c4681a6a983c1d782e4a9
  ```

* With two complete physical members connected, preview the device-mapper
  table without changing the system:

  ```bash
  sudo ./areca_raid10.py dm-table /dev/disk/by-id/member-from-0-or-1 \
    /dev/disk/by-id/member-from-2-or-3
  ```

  For this test array the resulting target is equivalent to:

  ```text
  0 390624256 striped 2 128 <even-pair-device> 520 <odd-pair-device> 520
  ```

* Create the validated mapping read-only:

  ```bash
  sudo ./areca_raid10.py create-dm arc5020-recovery \
    /dev/disk/by-id/member-from-0-or-1 \
    /dev/disk/by-id/member-from-2-or-3
  ```

  This uses `dmsetup create --readonly`; the resulting path is
  `/dev/mapper/arc5020-recovery`. Inspect and mount filesystems read-only.
  Remove it afterward with `sudo dmsetup remove arc5020-recovery`.
* Current safety boundary: the LBA-520 data offset is experimentally
  established for this ARC-5020 configuration. Stripe size is decoded from
  the duplicate 16-bit sector counts at Volume record `+0x28/+0x2a`, which
  were validated against both 64 KiB and 32 KiB configurations. The utility
  still supports only the observed four-member RAID1+0 metadata family and
  does not claim support for other Areca RAID10 member counts or models.

Planned recovery-tool experiments:

1. RAID3 data-layout experiment (completed):

   * Reinstall all four disks in their original channel order and allow the
     array and Volume Set to become ready.
   * Export the Volume Set through iSCSI on USB/8.
   * Apply the known ARC-5020 initiator limits before writing:

     ```bash
     echo 128 > /sys/block/sdX/queue/max_sectors_kb
     echo 1 > /sys/block/sdX/device/queue_depth
     ```

   * Write and verify a 64 MiB deterministic raw pattern with
     `raid_pattern.py`.
   * Shut the enclosure down and capture the first 64 MiB from all four
     members sequentially, preserving model, serial, channel, member index,
     and SHA-256 for each image.
   * Determine the dedicated parity member, data-disk order, actual 4 KiB
     chunk geometry, parity calculation, and whether the data offset remains
     member LBA 520.
   * Implement and test `areca_raid3.py`, including reconstruction when a data
     member is unavailable.

   Current progress:

   * The reassembled approximately 200 GB RAID3 Volume Set was exported as
     `/dev/sdc`.
   * Runtime iSCSI limits were confirmed at `max_sectors_kb=128` and
     `queue_depth=1`; the device was running and unmounted.
   * A 64 MiB deterministic pattern was written and verified through the
     logical iSCSI LUN:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     pattern verified
     ```

   * Next checkpoint: shut down the enclosure and capture the first 64 MiB of
     member indices 0, 1, 2, and 3 sequentially.
   * RAID3 member index 0 was captured:

     ```text
     samples/raid3-layout/member0-S1Y5J90B205357-first-64MiB.bin
     SHA256 0cdb13d679077cd99aea03c8f71a67ff468515b785f5315324c39a6a36921907
     ```

     Pattern data starts at member LBA 520. Member 0 contains contiguous
     8-sector/4 KiB chunks for logical LBAs `0-7, 24-31, 48-55, ...`, making
     it the first data member in each three-data-member RAID3 row. The scan
     found 5,462 runs and 43,696 pattern sectors.
   * RAID3 member index 1 was captured:

     ```text
     samples/raid3-layout/member1-Z4Y2MREM-first-64MiB.bin
     SHA256 7cf5c48c248cd0f0f98db22dcb78af05679d492c8ecefa5a32e90ab3b10395b8
     ```

     It contains 8-sector chunks for logical LBAs
     `8-15, 32-39, 56-63, ...`, so member 1 is the second data member in each
     row. The scan found 5,461 complete runs and 43,688 pattern sectors; the
     one-run difference from member 0 is the expected boundary effect from a
     64 MiB logical stream that is not an exact multiple of a full
     three-member row.
   * RAID3 member index 2 was captured:

     ```text
     samples/raid3-layout/member2-ZK20914S-first-64MiB.bin
     SHA256 9331f6cac7870167ef4d5c8666d380ee11a158b48b191db8dc02e4d3d5f75cff
     ```

     It contains 8-sector chunks for logical LBAs
     `16-23, 40-47, 64-71, ...`, confirming member 2 as the third data member.
     The scan found 5,461 complete runs and 43,688 pattern sectors.
   * RAID3 member index 3 was captured:

     ```text
     samples/raid3-layout/member3-ZK2094Y2-first-64MiB.bin
     SHA256 e7a521a4350677ac8e44fcc9222056f1c34e75eaee28c92b2315fb71e9b33fdf
     ```

     For every one of the 5,462 captured rows, its 4 KiB block is exactly
     `member0 XOR member1 XOR member2`; there were zero mismatches. Member 3
     is therefore the fixed dedicated parity disk. XOR of the deliberately
     structured test sectors can itself satisfy `raid_pattern.py` record
     checks, so apparent decoded runs on this member are not data placement;
     row-wise XOR is the authoritative role test.

   Confirmed four-member RAID3 row layout:

   ```text
   member 0: logical 4 KiB data chunk 0
   member 1: logical 4 KiB data chunk 1
   member 2: logical 4 KiB data chunk 2
   member 3: XOR parity of members 0, 1, and 2
   member data offset: LBA 520
   logical bytes per row: 12 KiB
   ```

   * `areca_raid3.py` reconstructs this layout into an ordinary image. It
     validates matching single-volume four-member metadata, duplicate RAID3
     code `2`, duplicate chunk-size fields, and unique member indices.
     Inputs are opened read-only and the output path must not already exist.
   * Use all four members:

     ```bash
     ./areca_raid3.py recovered.img member0 member1 member2 member3
     ```

     Or supply any three members. If a data member is absent, its 4 KiB block
     is reconstructed from the other two data members and dedicated parity.
     If parity is absent, members 0-2 are read directly.
   * The captured 64 MiB pattern was reconstructed and verified in all five
     cases: all members present, and each of indices 0, 1, 2, or 3 omitted in
     turn. Every output passed sector-by-sector verification and had the
     original logical digest:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     ```

   * Automated RAID3 tests cover normal reconstruction, each missing data
     member, and missing parity. The complete suite currently has 10 passing
     tests.

2. RAID5 data-layout experiment (completed):

   * Create an otherwise controlled four-member RAID5 Volume Set, preferably
     around 200 GB, with a known selectable stripe size.
   * Write and verify the same 64 MiB logical-LBA pattern through iSCSI.
   * Capture the first 64 MiB of every member sequentially.
   * Determine parity rotation, data-disk order, left/right and
     symmetric/asymmetric layout, member offset, and degraded reconstruction
     behavior.
   * Implement and test `areca_raid5.py`, including reconstruction with any
     one member missing.

   Current progress:

   * The approximately 200 GB, four-member, 32 KiB-stripe RAID5 Volume Set
     was exported through iSCSI as `/dev/sdc`.
   * The safe runtime limits were confirmed at `max_sectors_kb=128` and
     `queue_depth=1`; the LUN was running and unmounted.
   * A 64 MiB deterministic pattern was written and verified:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     pattern verified
     ```

   * Next checkpoint: shut down the enclosure and capture the first 64 MiB of
     member indices 0 through 3 sequentially.
   * RAID5 member index 0 was captured:

     ```text
     samples/raid5-layout/member0-S1Y5J90B205357-first-64MiB.bin
     SHA256 524a437f75ccc93e8954b7947346bbde258cec443a81d88e9e53a606da69121a
     ```

     Its 32 KiB physical chunks show a four-row cycle with three data chunks
     followed by one XOR-derived chunk. The initial apparent logical-LBA
     sequence is `0, 256, 512, 512, 768, 1024, 1280, 1280, ...`; repeated
     fourth values are parity artifacts of the structured test pattern, not
     duplicate logical data. All members are required to establish rotation
     direction and data ordering.
   * RAID5 member index 1 was captured:

     ```text
     samples/raid5-layout/member1-Z4Y2MREM-first-64MiB.bin
     SHA256 ac8f218be67576d8a14fa44e08ae2860a5fe6e3c45905b7535621f9985690db9
     ```

     Its initial apparent logical values are
     `64, 320, 576, 576, 832, 1088, 1344, 1344, ...`. These remain ambiguous
     until all four members are available because XOR parity can decode as a
     valid pattern value. Final role selection will use both row-wise XOR and
     coverage of each expected consecutive logical stripe.
   * RAID5 member index 2 was captured:

     ```text
     samples/raid5-layout/member2-ZK20914S-first-64MiB.bin
     SHA256 642bed7bd7a5b2ae8f877917343fa08d8f3bd8538ce2d5143b8cb8052c96b0d2
     ```

     Combining members 0-2 identifies a left-symmetric candidate layout:

     ```text
     row 0: data 0,1,2; parity 3
     row 1: data 3,0,1; parity 2
     row 2: data 2,3,0; parity 1
     row 3: data 1,2,3; parity 0
     ```

     Parity rotates from the highest member index downward, while logical data
     begins on the member immediately following parity and wraps around.
     Member 3 remains to confirm this across all captured rows.
   * RAID5 member index 3 was captured:

     ```text
     samples/raid5-layout/member3-ZK2094Y2-first-64MiB.bin
     SHA256 faffccb79e9ed0f2b9a37107430f6c3a9bb280f5428e46c0fc46d31538fc4825
     ```

     Across all 683 rows affected by the 64 MiB logical write,
     `member0 XOR member1 XOR member2 XOR member3` was zero with no
     mismatches. Its logical sequence completes the left-symmetric layout.
   * `areca_raid5.py` reconstructs the observed four-member layout into an
     ordinary image. It validates matching metadata, unique member indices,
     duplicate RAID5 code `3`, and the duplicate stripe-size fields. Inputs
     are opened read-only and the output path must not already exist.
   * Use all members or any three:

     ```bash
     ./areca_raid5.py recovered.img member0 member1 member2 member3
     ./areca_raid5.py recovered.img member0 member2 member3
     ```

     A missing data chunk is recovered by XORing all three surviving chunks
     in its row. A missing parity chunk requires no reconstruction for logical
     reads.
   * Real captures were reconstructed with all members and with each of
     indices 0, 1, 2, and 3 omitted in turn. Every 64 MiB result passed
     sector-by-sector verification and reproduced the original logical
     digest:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     ```

   * Automated RAID5 tests cover the four-row left-symmetric rotation and all
     single-member omissions. The complete project suite currently has 12
     passing tests.

3. Three-member RAID3 validation (completed):

   * Create a three-member RAID3 array with the same approximately 200 GB
     logical size. RAID3 uses the controller's fixed 4 KiB chunk.
   * Write and verify a 64 MiB deterministic logical-LBA pattern through
     iSCSI, then capture the first 64 MiB of all three members sequentially.
   * Test the expected generalized layout:

     ```text
     member indices 0 through N-2: ordered data chunks
     highest member index N-1:     dedicated XOR parity
     ```

     For three members this predicts indices 0 and 1 as data and index 2 as
     parity, with 8 KiB of logical data per row.
   * Verify every captured parity row by XOR, reconstruct the original logical
     digest with each member omitted in turn, and generalize
     `areca_raid3.py` to supported member counts only after the evidence
     passes.

   Current progress:

   * A three-member, approximately 200 GB RAID3 Volume Set was exported as
     `/dev/sdc` with logical size `199,999,619,072` bytes.
   * The LUN was running, unmounted, and using `max_sectors_kb=128` and
     `queue_depth=1`.
   * A 64 MiB deterministic pattern was written and verified:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     pattern verified
     ```

   * Next checkpoint: shut down and capture the first 64 MiB of member
     indices 0, 1, and 2 sequentially.
   * Three-member RAID3 member index 0 was captured:

     ```text
     samples/raid3-3disk-layout/member0-S1Y5J90B205357-first-64MiB.bin
     SHA256 98c873843f1b537eb6c0197e36d20cbbe14480ec7676a371b40ef6fd21ee410e
     ```

     It contains 8-sector chunks for logical LBAs
     `0-7, 16-23, 32-39, ...`: the first data chunk in each two-data-member
     row. The scan found 8,192 runs and 65,536 pattern sectors.
   * Three-member RAID3 member index 1 was captured:

     ```text
     samples/raid3-3disk-layout/member1-Z4Y2MREM-first-64MiB.bin
     SHA256 7f9a3f8a122ce88746616e91f8b41a95e88b7c7596f44212681761063f533ad6
     ```

     It contains logical LBAs `8-15, 24-31, 40-47, ...`, confirming the
     second data position. The scan also found 8,192 runs and 65,536 pattern
     sectors.
   * Three-member RAID3 member index 2 was captured:

     ```text
     samples/raid3-3disk-layout/member2-ZK20914S-first-64MiB.bin
     SHA256 f7ca3a6e2d4c586c3b55ec36555899985bffeb749e6d9eef5e82b1b93b801343
     ```

     All 8,192 captured rows satisfy
     `member2 = member0 XOR member1`, with zero mismatches. This confirms the
     generalized ARC-5020 RAID3 convention for both tested member counts:
     indices `0` through `N-2` are ordered data and highest index `N-1` is
     dedicated parity.
   * `areca_raid3.py` now supports experimentally verified member counts 3
     and 4. It derives the data-member count from metadata and tolerates any
     one missing member.
   * The real three-member captures reconstructed the original 64 MiB pattern
     with all members and with indices 0, 1, and 2 omitted in turn. Every case
     passed sector verification and reproduced:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     ```

     The prior four-member captures were regression-tested successfully.
     The complete project suite currently has 13 passing tests.

4. RAID10 dynamic-stripe regression (completed):

   * Recreate four-member RAID1+0 with a 32 KiB stripe.
   * Write and verify a 64 MiB pattern.
   * Capture sufficient data from one member in indices 0/1 and one member in
     indices 2/3.
   * Reconstruct with `areca_raid10.py` and confirm the exact logical pattern
     digest. This validates that reconstruction uses the decoded
     `+0x28/+0x2a` stripe fields rather than the original 64 KiB constant.

   Current progress:

   * A four-member, approximately 200 GB RAID1+0 Volume Set with 32 KiB stripe
     was exported as `/dev/sdc`, logical size `199,999,619,072` bytes.
   * The LUN was running, unmounted, and using `max_sectors_kb=128` and
     `queue_depth=1`.
   * A 64 MiB deterministic pattern was written and verified:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     pattern verified
     ```

   * Next checkpoint: shut down and capture one member from indices 0/1 and
     one from indices 2/3, preferably indices 0 and 2.
   * 32 KiB RAID10 member index 0 was captured:

     ```text
     samples/raid10-32k-layout/member0-S1Y5J90B205357-first-40MiB.bin
     SHA256 1a287fc4b5a7ced62cbfc190e7d6c84a7f33d098cd164321a03c5f9b412a8711
     ```

     The parser reports a 64-sector/32 KiB stripe. The member contains 1,024
     contiguous 64-sector pattern runs for even logical stripes, beginning at
     logical LBAs `0, 128, 256, 384, ...`.
   * 32 KiB RAID10 member index 2 was captured:

     ```text
     samples/raid10-32k-layout/member2-ZK20914S-first-40MiB.bin
     SHA256 d498ce163f10566de0c3b11ef4d89aa6d618a0755132a0e63c907ecb30d7b7cb
     ```

     It contains 1,024 contiguous 64-sector runs for odd logical stripes,
     beginning at logical LBAs `64, 192, 320, 448, ...`.
   * `areca_raid10.py` reconstructed a 64 MiB image from members 0 and 2 using
     the decoded 64-sector stripe fields. The image passed sector-by-sector
     pattern verification and reproduced the original logical digest:

     ```text
     SHA256 a19a47fc2ee7b0c591fc980e96bb9c5a2f8fac68f95de7f09b0d4db31fc6c39b
     ```

     This proves reconstruction is driven by the metadata stripe size and
     works for both experimentally tested 32 KiB and 64 KiB RAID1+0 layouts.

5. Physical two-member recovery test, once two SATA/eSATA connections are
   available:

   * Attach one healthy RAID10 member from indices 0/1 and one from 2/3.
   * Preview the generated `dmsetup` table, create the mapping read-only, and
     verify the filesystem and known checksums through
     `/dev/mapper/arc5020-recovery`.
   * Keep all recovery mappings and filesystem mounts read-only until their
     geometry and contents have been verified.

* That mapping change may remove the Volume Set from eSATA exposure. Do not
  apply it while eSATA is mounted or performing I/O. Confirm the host is
  disconnected/unmounted first, then retest discovery and direct login.

A manually created node using the configured base IQN failed to log in:

```bash
iscsiadm -m node \
  -o new \
  -T iqn.2000-01.com.abc.xyz:group \
  -p 192.168.1.235

iscsiadm -m node \
  -T iqn.2000-01.com.abc.xyz:group \
  -p 192.168.1.235 \
  --login
```

Result:

```text
Logging in to target iqn.2000-01.com.abc.xyz:group
initiator reported error:
19 - encountered non-retryable iSCSI login failure
```

The configured IQN is labelled “TargetNode Base Name,” so it may not be the complete generated target IQN. The firmware may append a Volume Set number, LUN number, RAID Set ID, MAC address, or another suffix.

Goals:

1. Wait for or verify completion of Volume Set initialization.
2. Retry SendTargets discovery.
3. Restart the Areca controller and retry discovery.
4. Determine whether a target IQN appears automatically after initialization or reboot.
5. Inspect the web and Telnet interfaces for hidden options related to:

   * enabling iSCSI
   * exporting a Volume Set
   * LUN mapping
   * target mapping
   * host access
   * ACLs
   * CHAP authentication
6. Query all useful local services and protocols exposed by the device.
7. Capture and analyze iSCSI traffic if useful.
8. Determine why direct login to the base IQN fails.
9. Determine whether the iSCSI implementation is usable, unfinished, disabled, or merely awaiting configuration.
10. Avoid destructive changes to existing data unless explicitly approved.

Useful commands:

```bash
nmap -Pn -sV -sC -p- 192.168.1.235
```

```bash
iscsiadm -m discovery \
  -t sendtargets \
  -p 192.168.1.235 \
  -d 8
```

```bash
iscsiadm -m node
```

```bash
iscsiadm -m session
```

```bash
tcpdump -i any -s 0 \
  -w areca-iscsi.pcap \
  host 192.168.1.235 and port 3260
```

Potentially inspect the pcap with `tshark`:

```bash
tshark -r areca-iscsi.pcap -Y iscsi -V
```

Look specifically for:

* iSCSI Login Response status class/detail
* `TargetName`
* `TargetAddress`
* `TargetPortalGroupTag`
* `SendTargets`
* authentication failures
* invalid target-name responses

Also test whether discovery behavior changes while the Volume Set is:

* initializing
* fully initialized
* activated
* offline
* restarted

Do not blindly guess large numbers of IQN suffixes. Prefer obtaining the target name from:

* SendTargets
* web/Telnet configuration
* HTTP requests or page source
* firmware files
* packet captures
* SNMP
* management APIs

Web interface investigation:

* Mirror or inspect relevant HTML, JavaScript, forms, CGI endpoints, and HTTP requests.
* Search downloaded content for:

  * `iscsi`
  * `TargetNode`
  * `TargetName`
  * `LUN`
  * `VolumeSet`
  * `mapping`
  * `export`
  * `iqn`
  * `3260`
* Check for hidden form fields, unlinked pages, commented options, and JavaScript-disabled controls.
* Do not brute-force authentication.

Firmware investigation, if a firmware image is locally available:

* Identify its format with `file`, `binwalk`, `strings`, and entropy checks.
* Extract it non-destructively.
* Search for:

  * `SendTargets`
  * `TargetPortalGroupTag`
  * `TargetNode`
  * `iscsi`
  * `iqn.`
  * `ietd`
  * `iscsitarget`
  * `tgtd`
  * `targetd`
  * `LUN`
  * `VolumeSet`
* Identify whether the target daemon is standard Linux software or an Areca proprietary binary.
* Search for hidden CGI routes or configuration files that create target nodes.

SNMP may also expose Volume Set or iSCSI information:

```bash
snmpwalk -v2c -c public 192.168.1.235
```

Only run that if the default community is appropriate and authorized.

Important safety constraints:

* This is an authorized device on my LAN.
* Prefer read-only inspection.
* Do not delete or recreate the newly created RAID Set or Volume Set.
* Do not overwrite disks or filesystems.
* Do not factory-reset the enclosure.
* Do not upgrade or downgrade firmware.
* Do not modify hidden settings without first explaining the exact change and risk.
* Save command output and findings in a structured log.

Final output should include:

* whether a usable iSCSI target was found
* the discovered IQN, portal, and LUNs
* exact commands needed to connect
* whether the target survives reboot
* whether the Volume Set is simultaneously exposed over eSATA and iSCSI
* any authentication or ACL requirements
* evidence supporting whether the implementation is complete, incomplete, or disabled
* safe next steps

The management password is intentionally omitted from public documentation
and retained locally in the ignored `PRIVATE_NOTES.md`.

## Multiple Volume Sets

A two-member RAID1 Raid Set was created with equal-sized Volume Sets named
`MULTI-VOL-A` and `MULTI-VOL-B`, exported as host drives 8 and 9.

- `$VolumE$` records are packed into 128-byte slots at member bytes 1024 and
  1152.
- Duplicate LE32 fields at record offsets `+0x0c` and `+0x18` contained 0 and
  3815.
- Each allocation unit is 512 sectors.
- The physical RAID1 member formula is
  `520 + allocation_offset * 512` sectors.
- Distinct 16 MiB patterns written through both iSCSI LUNs were recovered
  exactly at member LBAs 520 and 1,953,800.
- Record byte `+0x2f` held host drives 8/9 and `+0x33` held Volume Set
  indices 0/1.

The library and universal CLI select multi-volume RAID1 Volume Sets by index
or exact name. RAID1+0 support was added after the follow-up experiment below;
other RAID levels remain blocked until validated.

End-to-end reconstruction was then verified from physical member 0:

- `MULTI-VOL-A` reconstructed 16 MiB with pattern base 0 and passed
  `raid_pattern.py verify`;
- `MULTI-VOL-B` reconstructed 16 MiB with pattern base 1,000,000 and passed
  `raid_pattern.py verify`.

This validates metadata selection, allocation-offset translation, and logical
data reads for both Volume Sets independently.

### RAID1+0 follow-up

A four-member RAID1+0 with a 32 KiB stripe was tested with two Volume Sets:

- Volume 0: 1,952,768 logical sectors, allocation value 0;
- Volume 1: 3,905,536 logical sectors, allocation value 1908;
- predicted and observed Volume 1 member start: LBA 977,416
  (byte 500,436,992).

On member 0, each Volume Set began with logical stripes from mirror pair 0/1.
On member 2, each began with the following stripes from mirror pair 2/3.
Both streams restarted their RAID1+0 stripe numbering at the selected
Volume Set's physical start. This validates multi-volume RAID1+0
reconstruction and direct mapping.

### RAID0 follow-up

A four-member RAID0 with a 64 KiB stripe was tested with two Volume Sets:

- Volume 0: 39,061,504 logical sectors, allocation value 0;
- Volume 1: 7,811,072 logical sectors, allocation value 19,074;
- predicted and observed Volume 1 member start: LBA 9,766,408
  (byte 5,000,400,896).

Distinct 16 MiB patterns were written through both iSCSI LUNs. All four
physical members showed the expected round-robin stripe order. Both Volume
Sets restarted at member 0, and both began exactly at their metadata-derived
physical offsets. This provides hardware validation for simple RAID0 mapping
and multi-volume RAID0 reconstruction/direct mapping.

### RAID3 follow-up

A four-member RAID3 with its fixed 4 KiB chunk was tested with two Volume
Sets:

- Volume 0: 1,952,256 logical sectors, allocation value 0;
- Volume 1: 3,906,048 logical sectors, allocation value 1272;
- predicted and observed Volume 1 member start: LBA 651,784
  (byte 333,713,408).

Members 0, 1, and 2 contained the expected ordered data chunks, and each
Volume Set restarted row numbering at member 0. Member 3's dedicated parity
was independently verified as the XOR of all three expected data chunks for
multiple rows at both Volume Set offsets. This validates multi-volume RAID3
reconstruction, including degraded reads.

### RAID5 follow-up

A four-member RAID5 with a 64 KiB stripe was tested with two Volume Sets:

- Volume 0: 1,952,256 logical sectors, allocation value 0;
- Volume 1: 3,906,048 logical sectors, allocation value 1272;
- predicted and observed Volume 1 member start: LBA 651,784
  (byte 333,713,408).

Distinct 16 MiB patterns were written through both iSCSI LUNs. Every physical
member was verified for eight rows at each Volume Set offset, covering two
complete parity rotations. All data chunks and rotating parity chunks matched
the expected left-symmetric layout. Each Volume Set restarted at RAID5 row
zero. This validates multi-volume RAID5 reconstruction, including degraded
reads.
