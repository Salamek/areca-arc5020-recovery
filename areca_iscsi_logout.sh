#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: sudo $0 TARGET PORTAL" >&2
    exit 2
fi

if [[ $EUID -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 2
fi

TARGET=$1
PORTAL=$2

iscsiadm -m node -T "$TARGET" -p "$PORTAL" --logout
