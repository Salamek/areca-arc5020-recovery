#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: sudo $0 PORTAL" >&2
    exit 2
fi

if [[ $EUID -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 2
fi

iscsiadm -m discovery -t sendtargets -p "$1"
