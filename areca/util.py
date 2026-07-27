"""Small dependency-free helpers shared by Areca tools."""

from __future__ import annotations


def parse_size(value: str) -> int:
    suffixes = {
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
    }
    lowered = value.lower()
    for suffix, multiplier in suffixes.items():
        if lowered.endswith(suffix):
            return int(lowered[: -len(suffix)]) * multiplier
    return int(value)


def parse_volume_selector(value: str) -> int | str:
    """Parse a CLI Volume Set selector as an index or exact name."""
    return int(value) if value.isdecimal() else value
