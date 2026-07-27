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

for command in iscsiadm readlink awk; do
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

if ! iscsiadm -m node -T "$TARGET" -p "$PORTAL" -o show >/dev/null 2>&1; then
    echo "No node record found; running SendTargets discovery at $PORTAL"
    iscsiadm -m discovery -t sendtargets -p "$PORTAL"
fi

# These negotiation limits produced a stable session with ARC-5020 V1.50.
update_node node.session.cmds_max 16
update_node node.session.queue_depth 1
update_node node.session.iscsi.MaxBurstLength 131072
update_node node.session.iscsi.FirstBurstLength 65536

find_session_id() {
    iscsiadm -m session 2>/dev/null |
        awk -v target="$TARGET" -v portal="$PORTAL" '
            $4 == target && index($3, portal ",") == 1 {
                gsub(/^\[/, "", $2)
                gsub(/\]$/, "", $2)
                print $2
            }
        '
}

mapfile -t session_ids < <(find_session_id)
if (( ${#session_ids[@]} == 0 )); then
    iscsiadm -m node -T "$TARGET" -p "$PORTAL" --login
elif (( ${#session_ids[@]} == 1 )); then
    echo "Target already logged in through $PORTAL (session ${session_ids[0]})."
else
    echo "Multiple matching sessions already exist; refusing ambiguity." >&2
    printf '  session %s\n' "${session_ids[@]}" >&2
    exit 1
fi

if command -v udevadm >/dev/null 2>&1; then
    udevadm settle
fi

session=
for _ in {1..30}; do
    mapfile -t session_ids < <(find_session_id)
    if (( ${#session_ids[@]} == 1 )); then
        session=/sys/class/iscsi_session/session${session_ids[0]}
        break
    fi
    if (( ${#session_ids[@]} > 1 )); then
        echo "Multiple matching sessions found; refusing ambiguity." >&2
        printf '  session %s\n' "${session_ids[@]}" >&2
        exit 1
    fi
    sleep 1
done

if [[ -z $session ]]; then
    echo "No session appeared for target $TARGET through $PORTAL." >&2
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
