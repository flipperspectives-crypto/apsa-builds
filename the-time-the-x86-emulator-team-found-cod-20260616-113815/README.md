# emufix — Pattern-Based Binary Patcher

Inspired by the legendary x86 emulator team that found bad machine code
and *fixed it during emulation*, `emufix` is a CLI tool that scans
binary files for known-broken byte patterns and replaces them with
corrected sequences.

## What it does

- **scan** a binary for byte patterns (bad NOP sleds, INT3 spam, infinite JMP, etc.)
- **patch** occurrences with a corrected byte sequence
- **diff** to preview changes before applying
- **list** built-in patterns that represent real x86 quirks
- **export** patterns as JSON so you can build your own database

## Quick start

```bash
# List built-in patterns
python3 main.py list

# Scan a binary for a pattern
python3 main.py scan myapp.exe EB FE

# Scan using a built-in pattern name
python3 main.py scan myapp.exe jmp-self

# Preview what patching would do
python3 main.py diff myapp.exe jmp-self

# Apply the patch (creates myapp.exe.bak backup)
python3 main.py patch myapp.exe jmp-self

# Dry-run first
python3 main.py patch myapp.exe jmp-self --dry-run
```

## Built-in patterns

| Pattern               | Description                                        |
|-----------------------|----------------------------------------------------|
| `nop-sled-short`      | Overly short 2-byte NOP sled → longer harmless sled |
| `int3-spam`           | Triple INT3 (0xCC) breakpoints left in release    |
| `jmp-self`            | Infinite `JMP $-2` (EB FE) → HLT + NOP            |
| `call-pop-trampoline` | `CALL $+5` used to grab EIP → NOPs                 |
| `pusha-popa-nop`      | Pointless PUSHA/POPA pair → NOP padding            |

## Adding your own patterns

```bash
python3 main.py export -o my_patterns.json
# Edit my_patterns.json, then use the hex strings directly:
python3 main.py scan target.bin "90 90 90 90 90"
python3 main.py patch target.bin "90 90 90 90 90" "0F 1F 00"
```

## Requirements

Python 3.8+ — **no pip packages needed**, pure standard library.

## License

MIT
