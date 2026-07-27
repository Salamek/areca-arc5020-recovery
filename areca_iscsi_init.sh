#!/bin/bash
TARGET='iqn.2000-01.com.abc.xyz:group-08'
PORTAL='192.168.1.235:3260'

iscsiadm -m node -T "$TARGET" -p "$PORTAL" \
  -o update -n node.session.cmds_max -v 16

iscsiadm -m node -T "$TARGET" -p "$PORTAL" \
  -o update -n node.session.queue_depth -v 1

iscsiadm -m node -T "$TARGET" -p "$PORTAL" \
  -o update -n node.session.iscsi.MaxBurstLength -v 131072

iscsiadm -m node -T "$TARGET" -p "$PORTAL" \
  -o update -n node.session.iscsi.FirstBurstLength -v 65536

iscsiadm -m node -T "$TARGET" -p "$PORTAL" --login
