#!/usr/bin/env bash
#
# Log in to an ARC-5020 iSCSI target and apply the conservative queue limits
# needed to avoid the controller's invalid-R2T failure.

set -euo pipefail

usage() {
    echo "Usage: sudo $0 TARGET PORTAL" >&2
    echo "Example: sudo $0 iqn.2000-01.com.abc.xyz:group-08 192.168.1.235:3260" >&2
}

if [[ $# -ne 2 ]]; then
    usage
    exit 2
fi

if [[ $EUID -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 2
fi

TARGET=$1
PORTAL=$2

for command in iscsiadm readlink; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command not found: $command" >&2
        exit 2
    fi
done

update_node() {
    local name=$1
    local value=$2
    iscsiadm -m node -T "$TARGET" -p "$PORTAL" \
        -o update -n "$name" -v "$value"
}

# These negotiation limits produced a stable session with ARC-5020 V1.50.
update_node node.session.cmds_max 16
update_node node.session.queue_depth 1
update_node node.session.iscsi.MaxBurstLength 131072
update_node node.session.iscsi.FirstBurstLength 65536

if iscsiadm -m session 2>/dev/null | grep -Fq -- "$TARGET"; then
    echo "Target already has a logged-in session: $TARGET"
else
    iscsiadm -m node -T "$TARGET" -p "$PORTAL" --login
fi

if command -v udevadm >/dev/null 2>&1; then
    udevadm settle
fi

find_session() {
    local session_path
    local target_name

    for session_path in /sys/class/iscsi_session/session*; do
        [[ -d $session_path ]] || continue
        [[ -r $session_path/targetname ]] || continue
        IFS= read -r target_name < "$session_path/targetname"
        if [[ $target_name == "$TARGET" ]]; then
            printf '%s\n' "$session_path"
        fi
    done
}

session=
for _ in {1..30}; do
    mapfile -t sessions < <(find_session)
    if (( ${#sessions[@]} == 1 )); then
        session=${sessions[0]}
        break
    fi
    if (( ${#sessions[@]} > 1 )); then
        echo "Multiple sessions found for target $TARGET; refusing ambiguity." >&2
        printf '  %s\n' "${sessions[@]}" >&2
        exit 1
    fi
    sleep 1
done

if [[ -z $session ]]; then
    echo "No sysfs session appeared for target $TARGET." >&2
    exit 1
fi

devices=()
for _ in {1..30}; do
    devices=()
    shopt -s nullglob
    for block_path in "$session"/device/target*/*:*:*:*/block/*; do
        device=/dev/$(basename -- "$block_path")
        [[ -b $device ]] && devices+=("$(readlink -f -- "$device")")
    done
    shopt -u nullglob
    (( ${#devices[@]} > 0 )) && break
    sleep 1
done

if (( ${#devices[@]} == 0 )); then
    echo "Session is logged in, but no block device appeared for $TARGET." >&2
    exit 1
fi

for device in "${devices[@]}"; do
    device_name=$(basename -- "$device")
    queue_path=/sys/block/$device_name/queue/max_sectors_kb
    depth_path=/sys/block/$device_name/device/queue_depth

    if [[ ! -w $queue_path || ! -w $depth_path ]]; then
        echo "Queue controls are unavailable or not writable for $device." >&2
        exit 1
    fi

    echo 128 > "$queue_path"
    echo 1 > "$depth_path"

    echo "$TARGET -> $device"
    echo "  max_sectors_kb=$(<"$queue_path")"
    echo "  queue_depth=$(<"$depth_path")"
done
