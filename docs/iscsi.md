# ARC-5020 iSCSI operation

The ARC-5020 firmware tested here is `V1.50 2012-03-05`. Its iSCSI target is
functional, but Volume Sets must be mapped to the correct host-channel range.

## Export mapping

In the web interface, modify the Volume Set and assign:

```text
Channel: USB
Drive:   8 through 15
```

The `USB` channel represents both USB and the firmware's network-storage
range. Drives 8–15 map to eight iSCSI targets:

```text
<TargetNode Base Name>-08
...
<TargetNode Base Name>-15
```

Each target exports LUN 0. A Volume Set mapped to USB/8 was discovered as:

```text
iqn.2000-01.com.abc.xyz:group-08
```

Discover and log in with:

```bash
sudo ./areca_iscsi_discover.sh 192.168.1.235:3260
sudo ./areca_iscsi.sh \
  iqn.2000-01.com.abc.xyz:group-08 \
  192.168.1.235:3260
```

Adapt the IP address and base IQN to your enclosure.

## Required Linux initiator limits

Firmware V1.50 emits invalid R2T ranges during large writes with normal Linux
initiator defaults. This caused transport resets, I/O errors, and an aborted
ext4 journal. The tested stable profile is:

```text
node.session.cmds_max = 16
node.session.queue_depth = 1
node.session.iscsi.MaxBurstLength = 131072
node.session.iscsi.FirstBurstLength = 65536
runtime max_sectors_kb = 128
runtime queue_depth = 1
```

The repository scripts apply the persistent and runtime portions:

```bash
sudo ./areca_iscsi.sh \
  iqn.2000-01.com.abc.xyz:group-08 \
  192.168.1.235:3260
```

`areca_iscsi.sh` accepts the target IQN and portal as arguments, finds the
block device belonging to the resulting sysfs iSCSI session, and applies both
runtime block queue limits automatically. It also prints the detected device
path and the applied values.

Always verify the target identity printed by the script. Device names can
change after logout, reboot, or USB member attachment.

Inspect the negotiated session with:

```bash
iscsiadm -m session -P 3
```

The stable tested negotiation included:

```text
InitialR2T: Yes
ImmediateData: No
MaxOutstandingR2T: 1
MaxBurstLength: 131072
```

## Logout and stale devices

Log out normally:

```bash
iscsiadm -m session
sudo ./areca_iscsi_logout.sh \
  iqn.2000-01.com.abc.xyz:group-08 \
  192.168.1.235:3260
```

If a powered-down target leaves a stale local SCSI disk, first verify that it
is not mounted, then remove only that device:

```bash
findmnt /dev/sdX
echo 1 | sudo tee /sys/block/sdX/device/delete
```

## Caveats

- The target reports write caching but no FUA support.
- Do not disable filesystem barriers.
- Treat default large-I/O settings as unsafe on this firmware.
- The tested implementation uses one target per mapped Volume Set and LUN 0.
- This project is not affiliated with or supported by Areca.

Full discovery output and the protocol-failure investigation are retained in
the [research log](research-log.md).
