#!/usr/bin/env python3
"""
Boot Naked Linux — generate a minimal initramfs for bare-metal Linux boot.

"Naked Linux" means booting the kernel directly into a shell with zero
userspace bloat: no systemd, no udev, no dbus. Just /bin/sh and you.

This tool scaffolds a minimal root filesystem, writes a bare init script,
and packs it into a gzipped cpio archive ready for your bootloader.

Usage:
    python3 main.py scaffold   # create a minimal rootfs tree
    python3 main.py pack       # pack rootfs into initramfs.gz
    python3 main.py inspect    # peek inside an existing initramfs
    python3 main.py info       # print bootloader config reference
"""

import argparse
import os
import shutil
import stat
import sys
import textwrap
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INIT_SCRIPT = textwrap.dedent("""\
    #!/bin/sh
    # ── Boot Naked Linux · minimal init ───────────────────────────────────
    # This script is PID 1.  It mounts essential virtual filesystems, then
    # drops you into a root shell.  No daemons, no service manager, no fuss.

    echo "╔══════════════════════════════════════════╗"
    echo "║       BOOT NAKED LINUX                  ║"
    echo "║       Kernel: $(uname -r)"
    echo "║       Arch:   $(uname -m)"
    echo "╚══════════════════════════════════════════╝"

    # Mount core virtual filesystems
    mount -t proc     proc     /proc     2>/dev/null
    mount -t sysfs    sysfs    /sys      2>/dev/null
    mount -t devtmpfs devtmpfs /dev      2>/dev/null
    mount -t tmpfs    tmpfs    /tmp      2>/dev/null

    # Set hostname
    hostname naked 2>/dev/null || echo "naked" > /proc/sys/kernel/hostname

    echo ""
    echo "  You are now running the most minimal Linux userspace possible."
    echo "  Available commands: $(ls /bin /sbin 2>/dev/null | tr '\\n' ' ')"
    echo ""
    echo "  Type 'exit' or press Ctrl-Alt-Del to reboot."
    echo ""

    # Hand off to a shell; if it exits, restart it
    setsid /bin/cttyhack /bin/sh || setsid /bin/sh

    echo "init: shell exited — rebooting..."
    reboot -f 2>/dev/null
    sleep 2
    # Final fallback: tell kernel to restart
    echo b > /proc/sysrq-trigger 2>/dev/null
    exit 0
""")

BUSYBOX_INSTALL_NOTE = textwrap.dedent("""\
    # ── BusyBox install helper ────────────────────────────────────────────
    # Run this inside the rootfs to install BusyBox symlinks:
    #
    #   cd /path/to/rootfs
    #   cp "$(command -v busybox)" bin/busybox
    #   chroot . /bin/busybox --install -s /bin
    #
    # Or if busybox is statically linked:
    #   cd /path/to/rootfs && chroot . /bin/busybox --install -s /bin
""")

BOOTLOADER_REFERENCE = textwrap.dedent("""\
    # ── Bootloader config reference ───────────────────────────────────────
    #
    # SYSLINUX / EXTLINUX (syslinux.cfg):
    #   LABEL naked
    #       LINUX /vmlinuz
    #       INITRD /initramfs-naked.gz
    #       APPEND console=ttyS0 quiet
    #
    # GRUB 2 (grub.cfg):
    #   menuentry "Naked Linux" {
    #       linux  /vmlinuz console=tty0 quiet
    #       initrd /initramfs-naked.gz
    #   }
    #
    # QEMU quick-test:
    #   qemu-system-x86_64 -kernel /boot/vmlinuz-$(uname -r) \\
    #       -initrd initramfs-naked.gz -nographic -append "console=ttyS0"
    #
    # Minimal kernel config items needed:
    #   CONFIG_BLK_DEV_INITRD=y
    #   CONFIG_RD_GZIP=y
    #   CONFIG_DEVTMPFS=y
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str, executable: bool = False):
    path.write_text(content.lstrip("\n"))
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scaffold(rootfs_dir: Path, *, with_busybox_installer: bool = False):
    """Create a minimal root filesystem skeleton."""
    dirs = [
        "bin", "dev", "etc", "proc", "root", "sbin", "sys", "tmp", "usr/bin", "usr/sbin",
    ]
    _ensure_dir(rootfs_dir)
    for d in dirs:
        _ensure_dir(rootfs_dir / d)

    # Essential device nodes (devtmpfs handles most, but these are fallbacks)
    dev = rootfs_dir / "dev"
    for node, perms, major, minor in (
        ("null",   0o666, 1, 3),
        ("console", 0o600, 5, 1),
        ("tty",     0o666, 5, 0),
    ):
        node_path = dev / node
        if not node_path.exists():
            try:
                os.mknod(node_path, stat.S_IFCHR | perms, os.makedev(major, minor))
            except (PermissionError, OSError):
                # On some systems/containers mknod is restricted; not fatal
                pass

    # /etc/inittab — kept empty; our /init handles everything
    (rootfs_dir / "etc" / "inittab").write_text("# Naked Linux — no inittab needed\n")
    (rootfs_dir / "etc" / "hostname").write_text("naked\n")
    (rootfs_dir / "etc" / "passwd").write_text("root::0:0:root:/root:/bin/sh\n")

    # The init script (PID 1)
    _write_text(rootfs_dir / "init", INIT_SCRIPT, executable=True)

    # Optional busybox install helper
    if with_busybox_installer:
        _write_text(rootfs_dir / "install-busybox.sh", BUSYBOX_INSTALL_NOTE, executable=True)

    # Summary
    print(f"✅ Scaffolded minimal rootfs at {rootfs_dir}")
    print(f"   Directories:  {len(dirs)}")
    print(f"   Init script:  init")
    print()
    print("   Next steps:")
    print(f"   1. Install busybox:   cp $(command -v busybox) {rootfs_dir}/bin/")
    print(f"   2. Create symlinks:   chroot {rootfs_dir} /bin/busybox --install -s /bin")
    print(f"   3. Pack:              python3 main.py pack --rootfs {rootfs_dir}")


def _cpio_pad(size: int) -> bytes:
    """CPIO newc format: align to 4-byte boundaries."""
    return b"\x00" * ((4 - (size % 4)) % 4)


def _cpio_newc_header(
    inode: int, mode: int, uid: int, gid: int,
    nlink: int, mtime: int, filesize: int,
    dev_major: int, dev_minor: int, rdev_major: int, rdev_minor: int,
    namesize: int,
) -> bytes:
    """Build a CPIO newc (SVR4 without CRC) header: 110 bytes + name + padding."""
    header = (
        f"070701"
        f"{inode:08x}"
        f"{mode:08x}"
        f"{uid:08x}"
        f"{gid:08x}"
        f"{nlink:08x}"
        f"{mtime:08x}"
        f"{filesize:08x}"
        f"{dev_major:08x}"
        f"{dev_minor:08x}"
        f"{rdev_major:08x}"
        f"{rdev_minor:08x}"
        f"{namesize:08x}"
        f"00000000"  # checksum (ignored)
    )
    return header.encode("ascii")


def _pack_cpio_archive(rootfs_dir: Path, archive_fh) -> int:
    """Write a CPIO newc archive of rootfs_dir to archive_fh.  Returns entry count."""
    count = 0

    for entry in sorted(rootfs_dir.rglob("*"), key=lambda p: str(p)):
        rel = str(entry.relative_to(rootfs_dir))
        if rel == ".":
            continue
        name = f"./{rel}"
        stat_info = entry.lstat()
        namesize = len(name) + 1  # include NUL terminator

        # Determine mode & filetype
        if entry.is_symlink():
            mode = 0o120777
            target = os.readlink(entry)
            filesize = len(target.encode("utf-8"))
            content = target.encode("utf-8")
        elif entry.is_dir():
            mode = 0o040755
            filesize = 0
            content = b""
        elif stat.S_ISCHR(stat_info.st_mode) or stat.S_ISBLK(stat_info.st_mode):
            mode = stat_info.st_mode & 0o777
            if stat.S_ISCHR(stat_info.st_mode):
                mode |= 0o020000
            else:
                mode |= 0o060000
            filesize = 0
            content = b""
            rdev = os.major(stat_info.st_rdev), os.minor(stat_info.st_rdev)
        else:
            mode = 0o100755 if (stat_info.st_mode & 0o111) else 0o100644
            filesize = stat_info.st_size
            with open(entry, "rb") as fh:
                content = fh.read()

        dev_major = os.major(stat_info.st_dev) if hasattr(os, "major") else 0
        dev_minor = os.minor(stat_info.st_dev) if hasattr(os, "minor") else 0
        rdev_major = 0
        rdev_minor = 0
        if stat.S_ISCHR(stat_info.st_mode) or stat.S_ISBLK(stat_info.st_mode):
            rdev_major = os.major(stat_info.st_rdev)
            rdev_minor = os.minor(stat_info.st_rdev)

        hdr = _cpio_newc_header(
            inode=stat_info.st_ino,
            mode=mode,
            uid=stat_info.st_uid,
            gid=stat_info.st_gid,
            nlink=stat_info.st_nlink,
            mtime=int(stat_info.st_mtime),
            filesize=filesize,
            dev_major=dev_major,
            dev_minor=dev_minor,
            rdev_major=rdev_major,
            rdev_minor=rdev_minor,
            namesize=namesize,
        )
        archive_fh.write(hdr)
        archive_fh.write(name.encode("ascii") + b"\x00")
        archive_fh.write(_cpio_pad(110 + namesize))
        if content:
            archive_fh.write(content)
            archive_fh.write(_cpio_pad(filesize))
        count += 1

    # Trailer: "TRAILER!!!" entry (name = "TRAILER!!!", filesize=0)
    trailer_name = b"TRAILER!!!"
    trailer_ns = len(trailer_name) + 1
    tr_hdr = _cpio_newc_header(0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, trailer_ns)
    archive_fh.write(tr_hdr)
    archive_fh.write(trailer_name + b"\x00")
    archive_fh.write(_cpio_pad(110 + trailer_ns))
    count += 1
    return count


def cmd_pack(rootfs_dir: Path, output: Path):
    """Pack a rootfs directory into a gzipped cpio initramfs."""
    import gzip
    import io

    if not (rootfs_dir / "init").exists():
        print(f"⚠️  No 'init' found in {rootfs_dir} — the kernel needs /init as PID 1.")
        print("   Run 'scaffold' first, or create your own init script.")
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            sys.exit(1)

    output = output.resolve()
    rootfs_dir = rootfs_dir.resolve()

    print(f"📦 Packing {rootfs_dir} → {output} …")

    # Build cpio archive in memory, then gzip
    buf = io.BytesIO()
    count = _pack_cpio_archive(rootfs_dir, buf)
    cpio_data = buf.getvalue()
    print(f"   {count} entries in cpio archive ({_human_size(len(cpio_data))} raw)")

    with gzip.open(output, "wb", compresslevel=9) as gz:
        gz.write(cpio_data)

    size = output.stat().st_size
    print(f"✅ Packed initramfs: {output} ({_human_size(size)})")
    print()
    print("   Boot with QEMU:")
    print(f"   qemu-system-x86_64 -kernel /boot/vmlinuz-$(uname -r) \\")
    print(f"       -initrd {output} -nographic -append 'console=ttyS0'")


def cmd_inspect(archive: Path):
    """Peek inside an initramfs archive (pure Python)."""
    import gzip
    import io

    if not archive.exists():
        print(f"❌ Archive not found: {archive}")
        sys.exit(1)

    print(f"🔍 Inspecting {archive} …\n")

    if archive.name.endswith(".gz"):
        with gzip.open(archive, "rb") as gz:
            data = gz.read()
    else:
        data = archive.read_bytes()

    # Parse CPIO newc entries
    pos = 0
    entries = 0
    while pos + 110 <= len(data):
        magic = data[pos:pos + 6]
        if magic != b"070701":
            break
        hdr = data[pos:pos + 110]
        namesize = int(hdr[94:102], 16)
        filesize = int(hdr[54:62], 16)
        mode = int(hdr[14:22], 16)
        mtime = int(hdr[46:54], 16)
        pos += 110

        # Read name
        name = data[pos:pos + namesize]
        name = name.rstrip(b"\x00").decode("ascii", errors="replace")
        pos += namesize
        pos += (4 - ((110 + namesize) % 4)) % 4  # header padding

        if name == "TRAILER!!!":
            break

        # Read file data
        pos += filesize
        pos += (4 - (filesize % 4)) % 4  # data padding
        entries += 1

        from datetime import datetime
        ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        fmode = mode & 0o170000  # extract file type bits
        type_char = "d" if fmode == 0o040000 else ("l" if fmode == 0o120000 else "-")
        print(f"   {type_char} {mode:07o} {filesize:>8} {ts}  {name}")

    print(f"\n   {entries} entries total")


def cmd_info():
    """Print bootloader / kernel config reference."""
    print(BOOTLOADER_REFERENCE)


def _human_size(n: int) -> str:
    size: float = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="naked-linux",
        description="Boot Naked Linux — generate minimal initramfs images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python3 main.py scaffold
              python3 main.py scaffold --rootfs myrootfs --busybox-installer
              python3 main.py pack --rootfs rootfs --output initramfs-naked.gz
              python3 main.py inspect initramfs-naked.gz
              python3 main.py info
        """),
    )
    sub = parser.add_subparsers(dest="command", help="sub-command to run")

    # scaffold
    p_scaffold = sub.add_parser("scaffold", help="create minimal rootfs skeleton")
    p_scaffold.add_argument(
        "--rootfs", type=Path, default=Path("rootfs"),
        help="target rootfs directory (default: ./rootfs)",
    )
    p_scaffold.add_argument(
        "--busybox-installer", action="store_true",
        help="include a busybox install helper script",
    )

    # pack
    p_pack = sub.add_parser("pack", help="pack rootfs into gzipped initramfs")
    p_pack.add_argument(
        "--rootfs", type=Path, default=Path("rootfs"),
        help="rootfs directory to pack (default: ./rootfs)",
    )
    p_pack.add_argument(
        "--output", "-o", type=Path, default=Path("initramfs-naked.gz"),
        help="output file (default: initramfs-naked.gz)",
    )

    # inspect
    p_inspect = sub.add_parser("inspect", help="list contents of an initramfs archive")
    p_inspect.add_argument(
        "archive", type=Path,
        help="initramfs archive to inspect (.gz or .cpio)",
    )

    # info
    sub.add_parser("info", help="print bootloader config reference")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cwd = Path.cwd()

    if args.command == "scaffold":
        cmd_scaffold(args.rootfs, with_busybox_installer=args.busybox_installer)

    elif args.command == "pack":
        cmd_pack(args.rootfs, args.output)

    elif args.command == "inspect":
        cmd_inspect(args.archive)

    elif args.command == "info":
        cmd_info()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
