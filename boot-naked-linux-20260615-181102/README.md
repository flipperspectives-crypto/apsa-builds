# Boot Naked Linux

Generate a minimal initramfs for booting Linux with **nothing but a shell** —
no systemd, no udev, no dbus, no bloat. Just the kernel, `/init`, and you.

## What It Does

| Command | Purpose |
|---------|---------|
| `scaffold` | Creates a minimal root filesystem skeleton with a bare `/init` script |
| `pack`    | Packs the rootfs into a gzipped cpio initramfs ready for your bootloader |
| `inspect` | Lists the contents of an existing initramfs archive |
| `info`    | Prints bootloader config reference (GRUB, SYSLINUX, QEMU) |

## Requirements

- Python 3.8+ (stdlib only — **zero pip dependencies**)
- `cpio` and `gzip` on your PATH
- A Linux kernel (to actually boot, not needed to build)

## Quick Start

```bash
# 1. Scaffold a minimal rootfs
python3 main.py scaffold

# 2. Install busybox into rootfs/bin/ (one-time)
cp "$(command -v busybox)" rootfs/bin/
chroot rootfs /bin/busybox --install -s /bin

# 3. Pack into initramfs
python3 main.py pack

# 4. Boot it!
qemu-system-x86_64 -kernel /boot/vmlinuz-$(uname -r) \
    -initrd initramfs-naked.gz -nographic -append "console=ttyS0"
```

## Commands

### scaffold

```bash
python3 main.py scaffold [--rootfs <dir>] [--busybox-installer]
```

Creates a minimal directory tree under `./rootfs` (or `--rootfs`):

```
rootfs/
├── init              # PID 1 script (executable)
├── bin/ sbin/
├── dev/              # null, console, tty device nodes
├── etc/              # passwd, hostname
├── proc/ sys/ tmp/
└── usr/bin/ usr/sbin/
```

### pack

```bash
python3 main.py pack [--rootfs <dir>] [-o <output.gz>]
```

Packs the rootfs into a gzipped newc-format cpio archive.

### inspect

```bash
python3 main.py inspect initramfs-naked.gz
```

Lists the files inside an existing initramfs archive.

### info

```bash
python3 main.py info
```

Prints copy-paste-ready bootloader configs (GRUB 2, SYSLINUX, QEMU).

## Why "Naked"?

Most Linux distributions boot with hundreds of megabytes of userspace.
"Naked" booting strips everything away — your kernel hands PID 1 directly
to a shell script that mounts `/proc`, `/sys`, `/dev`, and `/tmp`, then
spawns a shell. That's it. Great for:

- Learning how Linux boot *actually* works
- Embedded systems with severe space constraints
- Rescue / recovery environments
- Container-like isolation without a container runtime

## License

MIT
