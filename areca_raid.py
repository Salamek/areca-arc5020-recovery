#!/usr/bin/env python3
"""Universal ARC-5020 array detection, reconstruction, and mapping tool."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys

from areca import ArecaArray, ArecaError, RaidLevel, parse_size


def summary(array: ArecaArray) -> dict[str, object]:
    return {
        "raid_level": array.level.value,
        "member_count": array.member_count,
        "supplied_indices": array.supplied_indices,
        "missing_indices": [
            index
            for index in range(array.member_count)
            if index not in array.members
        ],
        "logical_sectors": array.volume.sectors,
        "logical_bytes": array.logical_bytes,
        "volume_index": array.volume_index,
        "volume_name": array.volume.name,
        "volume_count": len(array.volumes),
        "stripe_sectors": array.chunk_sectors,
        "stripe_bytes": array.chunk_bytes,
        "member_data_offset_sectors": array.data_offset_sectors,
        "maximum_reconstructable_bytes": array.maximum_reconstructable_bytes(),
        "members": {
            str(index): member.path for index, member in sorted(array.members.items())
        },
    }


def assert_output_device_unused(path: str) -> None:
    """Reject mounted descendants and active stacked block consumers."""
    try:
        completed = subprocess.run(
            ["lsblk", "--json", "--paths", "--output", "NAME,TYPE,MOUNTPOINTS", path],
            check=True,
            text=True,
            capture_output=True,
        )
        tree = json.loads(completed.stdout)["blockdevices"]
    except (OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise ArecaError(f"cannot determine whether output device is in use: {error}")

    def walk(nodes: list[dict[str, object]], root: bool = False) -> None:
        for node in nodes:
            mounts = [value for value in (node.get("mountpoints") or []) if value]
            if mounts:
                raise ArecaError(
                    f"refusing output with mounted filesystem at {node.get('name')}: "
                    f"{mounts}"
                )
            kind = str(node.get("type") or "")
            if not root and kind not in ("disk", "part"):
                raise ArecaError(
                    f"refusing output with active {kind} consumer: {node.get('name')}"
                )
            walk(node.get("children") or [], root=False)

    walk(tree, root=True)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)

    inspect_cmd = commands.add_parser(
        "inspect", help="auto-detect and validate an array"
    )
    inspect_cmd.add_argument("members", nargs="+")
    inspect_cmd.add_argument("--json", action="store_true")
    inspect_cmd.add_argument("--volume", help="Volume Set index or exact name")

    reconstruct = commands.add_parser(
        "reconstruct", help="write the logical array to an image or block device"
    )
    reconstruct.add_argument("output")
    reconstruct.add_argument("members", nargs="+")
    reconstruct.add_argument("--bytes", type=parse_size)
    reconstruct.add_argument("--volume", help="Volume Set index or exact name")
    reconstruct.add_argument(
        "--i-understand-this-overwrites-the-output-device",
        action="store_true",
        help="required when OUTPUT is a block device",
    )

    table = commands.add_parser(
        "dm-table", help="print a direct device-mapper table when supported"
    )
    table.add_argument("members", nargs="+")
    table.add_argument("--volume", help="Volume Set index or exact name")

    create = commands.add_parser(
        "create-dm", help="create a direct active device when supported"
    )
    create.add_argument("name")
    create.add_argument("members", nargs="+")
    create.add_argument("--volume", help="Volume Set index or exact name")
    create.add_argument(
        "--writable",
        action="store_true",
        help="allow writes (currently supported only for complete RAID0)",
    )
    create.add_argument(
        "--i-understand-writes-modify-member-disks",
        action="store_true",
    )
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        volume_selector = args.volume
        if volume_selector is not None and volume_selector.isdecimal():
            volume_selector = int(volume_selector)
        array = ArecaArray.assemble(args.members, volume=volume_selector)

        if args.command == "inspect":
            data = summary(array)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(f"RAID level: {array.level.value}")
                print(
                    f"Members: {array.supplied_indices} "
                    f"of {array.member_count} expected"
                )
                print(
                    f"Logical size: {array.logical_bytes} bytes "
                    f"({array.volume.sectors} sectors)"
                )
                print(
                    f"Volume Set: {array.volume_index} "
                    f"({array.volume.name or '<unnamed>'})"
                )
                print(
                    f"Stripe/chunk: {array.chunk_bytes} bytes "
                    f"({array.chunk_sectors} sectors)"
                )
                print(
                    f"Member data offset: {array.data_offset_sectors} sectors"
                )
            return 0

        if args.command == "reconstruct":
            output_is_block = False
            try:
                output_is_block = stat.S_ISBLK(os.stat(args.output).st_mode)
            except FileNotFoundError:
                pass
            if output_is_block:
                resolved = os.path.realpath(args.output)
                input_paths = {
                    os.path.realpath(member.path) for member in array.members.values()
                }
                if resolved in input_paths:
                    raise ArecaError("an input member cannot also be the output device")
                assert_output_device_unused(resolved)
                if not args.i_understand_this_overwrites_the_output_device:
                    raise ArecaError(
                        "block-device output requires "
                        "--i-understand-this-overwrites-the-output-device"
                    )
            length = array.reconstruct(
                args.output,
                args.bytes,
                allow_block_device=args.i_understand_this_overwrites_the_output_device,
            )
            print(
                f"reconstructed {array.level.value} ({length} bytes) "
                f"into {args.output}"
            )
            return 0

        table = array.dm_table()
        if args.command == "dm-table":
            print(table)
            return 0

        if args.writable:
            if not args.i_understand_writes_modify_member_disks:
                raise ArecaError(
                    "--writable requires "
                    "--i-understand-writes-modify-member-disks"
                )
            if array.level != RaidLevel.RAID0:
                raise ArecaError(
                    "writable direct mapping is currently limited to complete RAID0; "
                    "mirror/parity write consistency is not implemented"
                )
        command = ["dmsetup", "create", args.name]
        if not args.writable:
            command.append("--readonly")
        command.extend(["--table", table])
        subprocess.run(command, check=True)
        print(f"/dev/mapper/{args.name}")
        return 0
    except (ArecaError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
