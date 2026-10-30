"""Read-only ROM identification and structural compatibility diagnostics.

Recognizing a translation does not authorize using an incompatible recipe.
Reports contain identifiers and mismatch counts, never game payload bytes.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import zlib

from .rom import ROM_SIZE, SUPPORTED_SHA1, CHINESE_SHA1

CHINESE_NAME = "FireRed Simplified Chinese v20230724 (电光一闪23333)"


def inspect_rom(path: str | Path, *, compare: bool = False) -> dict:
    path = Path(path)
    size = path.stat().st_size
    if size != ROM_SIZE:
        raise ValueError("Expected an exact 16 MiB FireRed ROM for inspection.")
    data = path.read_bytes()
    if len(data) != ROM_SIZE:
        raise ValueError("ROM changed while being read.")
    sha1 = hashlib.sha1(data).hexdigest()
    report = {
        "size": size,
        "sha1": sha1,
        "sha256": hashlib.sha256(data).hexdigest(),
        "game_code": data[0xac:0xb0].decode("ascii", "replace"),
        "revision": data[0xbc],
        "profile": ("firered-usa-rev0" if sha1 == SUPPORTED_SHA1 else
                    "firered-zh-cn-20230724" if sha1 == CHINESE_SHA1 else "unknown"),
        "native_supported": sha1 == SUPPORTED_SHA1,
    }
    if sha1 == CHINESE_SHA1:
        report["name"] = CHINESE_NAME
        report["status"] = "Native Chinese text/font/code adaptation required; not a supported data-pack input yet."
    elif sha1 != SUPPORTED_SHA1:
        report["status"] = "Unknown revision or modification; native compatibility has not been established."
    if compare:
        from .build import default_recipe
        from .recipe import load_recipe, execute
        recipe = load_recipe(default_recipe(SUPPORTED_SHA1))
        matched = 0
        changed = []
        for entry in recipe["entries"]:
            try:
                payload = execute(entry["ops"], data, entry["size"])
                matches = len(payload) == entry["size"] and zlib.crc32(payload) == entry["crc32"]
            except (ValueError, IndexError):
                matches = False
            if matches:
                matched += 1
            else:
                changed.append(entry["path"])
        report["comparison"] = {
            "total": len(recipe["entries"]), "matched": matched, "changed": len(changed),
            "changed_paths": changed,
            "categories": dict(Counter("/".join(p.split("/")[:2]) for p in changed)),
        }
    return report
