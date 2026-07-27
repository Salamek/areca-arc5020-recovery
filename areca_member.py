#!/usr/bin/env python3
"""Inspect ARC-5020 member metadata and optionally map validated RAID1."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict

from areca.metadata import (
    ArecaError,
    GPT_MAGIC,
    RAID_MAGIC,
    SECTOR_SIZE,
    VOLUME_MAGIC,
    VOLUME_RECORD_SIZE,
    create_loop,
    inspect,
    print_human,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="member block device or raw image")
    parser.add_argument("--json", action="store_true", help="emit inspection JSON")
    parser.add_argument(
        "--create-loop",
        action="store_true",
        help="create a partition-scanning loop mapping (root required)",
    )
    parser.add_argument(
        "--writable-loop",
        action="store_true",
        help="make the loop writable (unsafe; requires --create-loop)",
    )
    args = parser.parse_args()
    if args.writable_loop and not args.create_loop:
        parser.error("--writable-loop requires --create-loop")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = inspect(args.device)
        if args.json:
            print(json.dumps(asdict(result), indent=2))
        else:
            print_human(result)
        if args.create_loop:
            print(create_loop(result, writable=args.writable_loop))
        return 0
    except (ArecaError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
