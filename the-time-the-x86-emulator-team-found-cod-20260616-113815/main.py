#!/usr/bin/env python3
"""
emufix — Pattern-based binary patcher.

Inspired by the x86 emulator team that detected known-broken instruction
sequences at runtime and fixed them on the fly.  This CLI tool does the
same thing offline: scan a binary file for byte patterns (bad code) and
replace them with corrected sequences (the fix).

Usage:
  emufix scan <binary> <pattern>                # find occurrences
  emufix patch <binary> <pattern> <replacement> # apply patches
  emufix diff <binary> <pattern> <replacement>  # show what would change
  emufix list                                    # list built-in patterns
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import struct
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# ── built-in known-bad patterns ──────────────────────────────────────────────
# Format: (name, description, hex_pattern, hex_fix)
# These represent real historical x86 quirks / known bad sequences.
# When the emulator team encountered these, they patched them on the fly.

BUILTIN_PATTERNS = {
    "nop-sled-short": {
        "desc": "Overly short NOP sled (2 bytes) that some old DRM used; "
        "replace with a longer harmless sled.",
        "find": "90 90",
        "fix": "90 90 90 90 90",
    },
    "int3-spam": {
        "desc": "Sequence of 3+ INT3 (0xCC) breakpoints left in release "
        "builds; replace with NOPs.",
        "find": "CC CC CC",
        "fix": "90 90 90",
    },
    "jmp-self": {
        "desc": "Infinite JMP-to-self (EB FE) — common in old polling "
        "loops; replace with HLT + NOP.",
        "find": "EB FE",
        "fix": "F4 90",
    },
    "call-pop-trampoline": {
        "desc": "E8 00 00 00 00 (call next; pop to get EIP) — detected "
        "and replaced with NOPs when in non-executable context.",
        "find": "E8 00 00 00 00",
        "fix": "90 90 90 90 90",
    },
    "pusha-popa-nop": {
        "desc": "PUSHA / POPA pair with nothing in between — "
        "pointless; replace with equivalent NOP padding.",
        "find": "60 61",
        "fix": "90 90",
    },
}

# ── helpers ──────────────────────────────────────────────────────────────────

def _hex_to_bytes(hex_str: str) -> bytes:
    """Parse space-separated hex like '90 90 EB FE' into bytes."""
    parts = hex_str.strip().split()
    if not all(len(p) == 2 for p in parts):
        raise ValueError(f"Each hex byte must be exactly 2 chars: {hex_str!r}")
    return bytes(int(p, 16) for p in parts)


def _bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _find_all(data: bytes, pattern: bytes) -> List[int]:
    """Return list of byte offsets where *pattern* appears in *data*."""
    offsets: List[int] = []
    idx = 0
    while True:
        idx = data.find(pattern, idx)
        if idx == -1:
            break
        offsets.append(idx)
        idx += 1  # overlapping matches (e.g. CC CC CC → 2 hits)
    return offsets


def _apply_patches(data: bytearray, offsets: List[int],
                   old_len: int, new: bytes) -> bytearray:
    """Replace *old_len* bytes at each offset with *new* (pads/truncates)."""
    # Work backwards so earlier offsets stay valid.
    for off in reversed(offsets):
        data[off:off + old_len] = new
    return data


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_scan(path: Path, hex_pattern: str) -> int:
    data = path.read_bytes()
    pat = _hex_to_bytes(hex_pattern)
    offsets = _find_all(data, pat)

    print(f"File   : {path}  ({len(data)} bytes)")
    print(f"Pattern: {hex_pattern}  ({len(pat)} bytes)")
    print(f"Found  : {len(offsets)} occurrence(s)")
    for off in offsets:
        ctx_start = max(0, off - 4)
        ctx_end = min(len(data), off + len(pat) + 4)
        before = _bytes_to_hex(data[ctx_start:off])
        match_ = _bytes_to_hex(data[off:off + len(pat)])
        after = _bytes_to_hex(data[off + len(pat):ctx_end])
        print(f"  @ {off:#010x}  [{before}] **[{match_}]** [{after}]")
    return 0


def cmd_patch(path: Path, hex_find: str, hex_fix: str, *,
              dry_run: bool = False, backup: bool = True) -> int:
    data = bytearray(path.read_bytes())
    find = _hex_to_bytes(hex_find)
    fix = _hex_to_bytes(hex_fix)
    offsets = _find_all(bytes(data), find)

    if not offsets:
        print(f"No matches for pattern '{hex_find}' in {path}")
        return 1

    if dry_run:
        print(f"[DRY RUN] Would patch {len(offsets)} occurrence(s) in {path}")
        for off in offsets:
            print(f"  @ {off:#010x}: {_bytes_to_hex(find)} → {_bytes_to_hex(fix)}")
        return 0

    # Backup
    if backup:
        bak = path.with_suffix(path.suffix + ".bak")
        bak.write_bytes(data)
        print(f"Backup saved → {bak}")

    _apply_patches(data, offsets, len(find), fix)
    path.write_bytes(data)
    print(f"Patched {len(offsets)} occurrence(s) in {path}")
    return 0


def cmd_diff(path: Path, hex_find: str, hex_fix: str) -> int:
    original = path.read_bytes()
    find = _hex_to_bytes(hex_find)
    fix = _hex_to_bytes(hex_fix)
    new = bytearray(original)
    offsets = _find_all(bytes(new), find)
    _apply_patches(new, offsets, len(find), fix)

    # Produce a unified-diff-like hex view
    orig_hex = _bytes_to_hex(original)
    new_hex = _bytes_to_hex(bytes(new))
    diff = difflib.unified_diff(
        orig_hex.split(), new_hex.split(),
        fromfile=f"{path} (original)", tofile=f"{path} (patched)",
        lineterm="",
    )
    for line in diff:
        # Colorise + / - if terminal supports it
        if sys.stdout.isatty():
            if line.startswith("---") or line.startswith("+++"):
                print(f"\033[1m{line}\033[0m")
            elif line.startswith("@@"):
                print(f"\033[36m{line}\033[0m")
            elif line.startswith("+"):
                print(f"\033[32m{line}\033[0m")
            elif line.startswith("-"):
                print(f"\033[31m{line}\033[0m")
            else:
                print(line)
        else:
            print(line)

    summary = (f"\n{len(offsets)} patch(es) would change "
               f"{len(new) - len(original)} byte(s) total")
    print(summary)
    return 0


def cmd_list() -> int:
    print(f"{'PATTERN':<24} {'FIND':<24} FIX")
    print("-" * 72)
    for name, info in BUILTIN_PATTERNS.items():
        print(f"{name:<24} {info['find']:<24} {info['fix']}")
    print()
    print("Use 'emufix scan <bin> <pattern-name>' to use a built-in pattern.")
    return 0


def cmd_export(out_path: Optional[Path]) -> int:
    """Export built-in patterns as JSON so users can extend them."""
    payload = json.dumps(BUILTIN_PATTERNS, indent=2)
    if out_path:
        out_path.write_text(payload)
        print(f"Patterns exported → {out_path}")
    else:
        print(payload)
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def _resolve_pattern(candidate: str) -> str:
    """If candidate names a built-in pattern, return its 'find' string."""
    if candidate in BUILTIN_PATTERNS:
        return BUILTIN_PATTERNS[candidate]["find"]
    return candidate


def _resolve_replacement(candidate: str) -> str:
    if candidate in BUILTIN_PATTERNS:
        return BUILTIN_PATTERNS[candidate]["fix"]
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emufix",
        description="Pattern-based binary patcher — like an x86 emulator's "
                    "runtime fix, but offline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Find pattern occurrences in a binary")
    p_scan.add_argument("binary", type=Path, help="Path to the binary file")
    p_scan.add_argument("pattern", help="Hex pattern (e.g. 'EB FE') or built-in name")

    # patch
    p_patch = sub.add_parser("patch", help="Replace pattern with fix")
    p_patch.add_argument("binary", type=Path)
    p_patch.add_argument("pattern")
    p_patch.add_argument("replacement", nargs="?", default=None,
                         help="Hex fix, or built-in name (auto-pairs find+fix)")
    p_patch.add_argument("--dry-run", action="store_true")
    p_patch.add_argument("--no-backup", action="store_true",
                         help="Skip creating a .bak backup")

    # diff
    p_diff = sub.add_parser("diff", help="Show what patching would change")
    p_diff.add_argument("binary", type=Path)
    p_diff.add_argument("pattern")
    p_diff.add_argument("replacement", nargs="?", default=None)

    # list
    sub.add_parser("list", help="List built-in patterns")

    # export
    p_exp = sub.add_parser("export", help="Export patterns as JSON")
    p_exp.add_argument("-o", "--out", type=Path, default=None,
                       help="Output file (stdout if omitted)")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return cmd_list()

    if args.command == "export":
        return cmd_export(args.out)

    if args.command == "scan":
        binary: Path = args.binary
        if not binary.is_file():
            print(f"Error: '{binary}' is not a file", file=sys.stderr)
            return 1
        pattern = _resolve_pattern(args.pattern)
        return cmd_scan(binary, pattern)

    if args.command == "patch":
        binary = args.binary
        if not binary.is_file():
            print(f"Error: '{binary}' is not a file", file=sys.stderr)
            return 1

        find = _resolve_pattern(args.pattern)
        if args.replacement is None:
            fix = _resolve_replacement(args.pattern)  # single built-in name
        else:
            fix = _resolve_replacement(args.replacement)

        return cmd_patch(binary, find, fix,
                         dry_run=args.dry_run,
                         backup=not args.no_backup)

    if args.command == "diff":
        binary = args.binary
        if not binary.is_file():
            print(f"Error: '{binary}' is not a file", file=sys.stderr)
            return 1

        find = _resolve_pattern(args.pattern)
        if args.replacement is None:
            fix = _resolve_replacement(args.pattern)
        else:
            fix = _resolve_replacement(args.replacement)

        return cmd_diff(binary, find, fix)

    return 0


if __name__ == "__main__":
    sys.exit(main())
