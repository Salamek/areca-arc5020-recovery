#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /dev/sdX" >&2
  exit 2
fi

DEVICE=$(readlink -f -- "$1")
if [[ ! -b "$DEVICE" ]]; then
  echo "Not a block device: $1" >&2
  exit 2
fi

DEVICE_NAME=$(basename -- "$DEVICE")
QUEUE_PATH="/sys/block/$DEVICE_NAME/queue/max_sectors_kb"
DEPTH_PATH="/sys/block/$DEVICE_NAME/device/queue_depth"

if [[ ! -w "$QUEUE_PATH" || ! -w "$DEPTH_PATH" ]]; then
  echo "Queue controls are unavailable or not writable for $DEVICE" >&2
  exit 2
fi

echo 128 > "$QUEUE_PATH"
echo 1 > "$DEPTH_PATH"

echo "$DEVICE: max_sectors_kb=$(<"$QUEUE_PATH"), queue_depth=$(<"$DEPTH_PATH")"
