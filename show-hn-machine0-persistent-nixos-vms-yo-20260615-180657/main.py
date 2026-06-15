#!/usr/bin/env python3
"""
machine0 — Persistent NixOS VMs You Control from the CLI.

A lightweight CLI tool for creating, listing, starting, stopping, and
deleting persistent virtual machines. Backed by JSON state files and
compatible with QEMU/KVM when available; falls back to simulation mode
on constrained environments (Termux, containers, etc.).

Usage:
    python3 main.py create <name>        Create a new persistent VM
    python3 main.py list                 List all VMs and their status
    python3 main.py start <name>         Start a VM
    python3 main.py stop <name>          Stop a running VM
    python3 main.py delete <name>        Delete a VM and its disk
    python3 main.py info <name>          Show detailed VM info
    python3 main.py shell <name>         Attach to a running VM console
    python3 main.py snapshot <name>      Create a snapshot of a VM
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

MACHINE0_HOME = Path.home() / ".machine0"
VM_DIR = MACHINE0_HOME / "vms"
STATE_FILE = MACHINE0_HOME / "state.json"
DISK_DIR = MACHINE0_HOME / "disks"
PID_DIR = MACHINE0_HOME / "pids"
SNAPSHOT_DIR = MACHINE0_HOME / "snapshots"

DEFAULT_MEMORY_MB = 512
DEFAULT_CPUS = 1
DEFAULT_DISK_GB = 5

# ── Helpers ──────────────────────────────────────────────────────────────────

def init_dirs() -> None:
    """Create machine0 directory structure if it doesn't exist."""
    for d in (VM_DIR, DISK_DIR, PID_DIR, SNAPSHOT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text("{}")


def load_state() -> dict:
    """Load the persistent VM state from disk."""
    init_dirs()
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_state(state: dict) -> None:
    """Atomically write VM state to disk."""
    init_dirs()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)


def check_qemu() -> bool:
    """Return True if QEMU system emulator is available."""
    return shutil.which("qemu-system-x86_64") is not None


def read_pid(vm_name: str) -> int | None:
    """Read the PID file for a VM, returning None if missing or stale."""
    pid_file = PID_DIR / f"{vm_name}.pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None
    # Check if process is alive
    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError):
        pid_file.unlink(missing_ok=True)
        return None


def vm_exists(name: str) -> bool:
    """Check whether a VM with the given name is registered."""
    state = load_state()
    return name in state


def require_vm(name: str, state: dict | None = None) -> dict:
    """Look up a VM by name; exit with error if not found."""
    if state is None:
        state = load_state()
    if name not in state:
        print(f"Error: VM '{name}' not found. Use 'list' to see available VMs.")
        sys.exit(1)
    return state[name]


# ── QEMU backend ─────────────────────────────────────────────────────────────

def _qemu_start(vm: dict) -> None:
    """Launch a VM via QEMU in the background and record its PID."""
    name = vm["name"]
    disk = DISK_DIR / f"{name}.qcow2"
    pid_file = PID_DIR / f"{name}.pid"

    cmd = [
        "qemu-system-x86_64",
        "-name", name,
        "-m", str(vm.get("memory_mb", DEFAULT_MEMORY_MB)),
        "-smp", str(vm.get("cpus", DEFAULT_CPUS)),
        "-drive", f"file={disk},format=qcow2,if=virtio",
        "-netdev", "user,id=net0",
        "-device", "virtio-net-pci,netdev=net0",
        "-nographic",
        "-daemonize",
        "-pidfile", str(pid_file),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _qemu_stop(name: str, pid: int | None) -> None:
    """Gracefully shut down a QEMU VM via monitor socket or kill."""
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 10 seconds for graceful shutdown
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                break
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# ── Simulation backend (no QEMU) ─────────────────────────────────────────────

def _sim_start(vm: dict) -> None:
    """Simulate a VM by launching a long-running Python process."""
    name = vm["name"]
    pid_file = PID_DIR / f"{name}.pid"

    sim_script = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        f"print(f'[machine0] VM {name} booted (simulation). PID: {{os.getpid()}}')\n"
        "while True:\n"
        "    print('[machine0] heartbeat — VM running...')\n"
        "    time.sleep(30)\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", sim_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))


def _sim_stop(name: str, pid: int | None) -> None:
    """Stop a simulated VM."""
    if pid is None:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_create(args: argparse.Namespace) -> None:
    """Create a new persistent VM."""
    name = args.name
    state = load_state()

    if name in state:
        print(f"Error: VM '{name}' already exists.")
        sys.exit(1)

    # Sanitize name
    if not name.replace("-", "").replace("_", "").isalnum():
        print("Error: VM name must contain only alphanumerics, hyphens, or underscores.")
        sys.exit(1)

    vm = {
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "stopped",
        "memory_mb": args.memory or DEFAULT_MEMORY_MB,
        "cpus": args.cpus or DEFAULT_CPUS,
        "disk_gb": args.disk or DEFAULT_DISK_GB,
        "backend": "qemu" if check_qemu() else "simulated",
        "source": "machine0.io",
    }

    # Create a placeholder disk file
    disk_path = DISK_DIR / f"{name}.qcow2"
    if check_qemu():
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(disk_path), f"{vm['disk_gb']}G"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        disk_path.write_text(f"# machine0 simulated disk for VM '{name}' ({vm['disk_gb']} GB)\n")

    state[name] = vm
    save_state(state)

    backend = "QEMU/KVM" if check_qemu() else "simulated"
    print(f"✅ Created VM '{name}' ({backend} backend)")
    print(f"   Memory: {vm['memory_mb']} MB  |  CPUs: {vm['cpus']}  |  Disk: {vm['disk_gb']} GB")
    print(f"   State:  {STATE_FILE}")


def cmd_list(args: argparse.Namespace) -> None:
    """List all VMs with status."""
    state = load_state()
    if not state:
        print("No VMs found. Create one with: machine0 create <name>")
        return

    backend_label = "qemu" if check_qemu() else "sim"
    print(f"{'NAME':<24} {'STATUS':<12} {'MEM':>6} {'CPU':>4}  BACKEND")
    print("-" * 60)
    for name, vm in sorted(state.items()):
        pid = read_pid(name) if vm.get("status") == "running" else None
        actual_status = "running" if pid else "stopped"
        if actual_status != vm.get("status"):
            vm["status"] = actual_status
        print(
            f"{name:<24} "
            f"{vm['status']:<12} "
            f"{vm.get('memory_mb', DEFAULT_MEMORY_MB):>4}MB "
            f"{vm.get('cpus', DEFAULT_CPUS):>4}  "
            f"{vm.get('backend', backend_label)}"
        )
    save_state(state)  # Persist any status corrections


def cmd_start(args: argparse.Namespace) -> None:
    """Start a VM."""
    state = load_state()
    vm = require_vm(args.name, state)

    pid = read_pid(args.name)
    if pid is not None:
        print(f"VM '{args.name}' is already running (PID {pid}).")
        return

    print(f"Booting '{args.name}'... ", end="", flush=True)
    try:
        if check_qemu():
            _qemu_start(vm)
        else:
            _sim_start(vm)
    except Exception as e:
        print(f"\nError: Failed to start VM: {e}")
        sys.exit(1)

    # Give it a moment to boot
    time.sleep(0.5)
    new_pid = read_pid(args.name)
    if new_pid:
        vm["status"] = "running"
        vm["last_started"] = datetime.now(timezone.utc).isoformat()
        state[args.name] = vm
        save_state(state)
        print(f"running (PID {new_pid})")
    else:
        print("failed (process did not start)")
        sys.exit(1)


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop a running VM."""
    state = load_state()
    vm = require_vm(args.name, state)

    pid = read_pid(args.name)
    if pid is None:
        print(f"VM '{args.name}' is not running.")
        return

    print(f"Stopping '{args.name}' (PID {pid})... ", end="", flush=True)
    if check_qemu():
        _qemu_stop(args.name, pid)
    else:
        _sim_stop(args.name, pid)

    # Verify it stopped
    time.sleep(1)
    if read_pid(args.name) is None:
        vm["status"] = "stopped"
        vm["last_stopped"] = datetime.now(timezone.utc).isoformat()
        state[args.name] = vm
        save_state(state)
        print("stopped")
    else:
        print("warning: VM may still be running")


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete a VM and its associated files."""
    state = load_state()
    vm = require_vm(args.name, state)

    # Stop if running
    pid = read_pid(args.name)
    if pid:
        print(f"Stopping running VM '{args.name}' first...")
        if check_qemu():
            _qemu_stop(args.name, pid)
        else:
            _sim_stop(args.name, pid)
        time.sleep(1)

    # Remove files
    for f in [
        DISK_DIR / f"{args.name}.qcow2",
        PID_DIR / f"{args.name}.pid",
    ]:
        f.unlink(missing_ok=True)

    # Remove snapshots directory
    snap_dir = SNAPSHOT_DIR / args.name
    if snap_dir.exists():
        shutil.rmtree(snap_dir)

    del state[args.name]
    save_state(state)
    print(f"🗑️  Deleted VM '{args.name}' and all associated files.")


def cmd_info(args: argparse.Namespace) -> None:
    """Show detailed information about a VM."""
    state = load_state()
    vm = require_vm(args.name, state)
    pid = read_pid(args.name)

    print(f"╔══ VM: {vm['name']}")
    print(f"╠══ Status:      {vm.get('status', 'unknown')}" + (f" (PID {pid})" if pid else ""))
    print(f"╠══ Backend:     {vm.get('backend', 'unknown')}")
    print(f"╠══ Memory:      {vm.get('memory_mb', DEFAULT_MEMORY_MB)} MB")
    print(f"╠══ CPUs:        {vm.get('cpus', DEFAULT_CPUS)}")
    print(f"╠══ Disk:        {vm.get('disk_gb', DEFAULT_DISK_GB)} GB")
    print(f"╠══ Created:     {vm.get('created', 'unknown')}")
    if vm.get("last_started"):
        print(f"╠══ Last start:  {vm['last_started']}")
    if vm.get("last_stopped"):
        print(f"╠══ Last stop:   {vm['last_stopped']}")
    print(f"╠══ Disk file:   {DISK_DIR / args.name}.qcow2")
    print(f"╚══ Source:      {vm.get('source', 'machine0.io')}")


def cmd_shell(args: argparse.Namespace) -> None:
    """Attach to a running VM's console (QEMU only)."""
    state = load_state()
    vm = require_vm(args.name, state)
    pid = read_pid(args.name)

    if not pid:
        print(f"VM '{args.name}' is not running. Start it first.")
        sys.exit(1)

    if vm.get("backend") == "simulated":
        print("Console attach is not available in simulated mode.")
        print(f"The VM is running as process {pid} on this host.")
        return

    # For real QEMU, connect to the monitor socket
    monitor = PID_DIR / f"{args.name}.monitor"
    if monitor.exists():
        subprocess.run(["nc", "-U", str(monitor)], check=False)
    else:
        print("No monitor socket found. The VM was started without one.")
        print(f"VM is running with PID {pid}.")


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Create a named snapshot of a VM."""
    state = load_state()
    vm = require_vm(args.name, state)
    snap_name = args.snapshot_name or datetime.now().strftime("snap-%Y%m%d-%H%M%S")
    snap_dir = SNAPSHOT_DIR / args.name
    snap_dir.mkdir(parents=True, exist_ok=True)

    snap_file = snap_dir / f"{snap_name}.json"
    snap_data = {
        "vm": vm,
        "taken_at": datetime.now(timezone.utc).isoformat(),
    }
    snap_file.write_text(json.dumps(snap_data, indent=2))
    print(f"📸 Snapshot '{snap_name}' saved for VM '{args.name}'")


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for machine0."""
    parser = argparse.ArgumentParser(
        prog="machine0",
        description="Persistent NixOS VMs you control from the CLI — powered by machine0.io",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  machine0 create my-vm --memory 1024 --cpus 2
  machine0 list
  machine0 start my-vm
  machine0 info my-vm
  machine0 stop my-vm
  machine0 snapshot my-vm
  machine0 delete my-vm
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True, title="commands")

    # create
    p_create = sub.add_parser("create", help="Create a new persistent VM")
    p_create.add_argument("name", help="Name for the new VM")
    p_create.add_argument("-m", "--memory", type=int, help=f"Memory in MB (default: {DEFAULT_MEMORY_MB})")
    p_create.add_argument("-c", "--cpus", type=int, help=f"Number of CPUs (default: {DEFAULT_CPUS})")
    p_create.add_argument("-d", "--disk", type=int, help=f"Disk size in GB (default: {DEFAULT_DISK_GB})")
    p_create.set_defaults(func=cmd_create)

    # list
    p_list = sub.add_parser("list", help="List all VMs and their status")
    p_list.set_defaults(func=cmd_list)

    # start
    p_start = sub.add_parser("start", help="Start a VM")
    p_start.add_argument("name", help="Name of the VM to start")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = sub.add_parser("stop", help="Stop a running VM")
    p_stop.add_argument("name", help="Name of the VM to stop")
    p_stop.set_defaults(func=cmd_stop)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a VM and its disk")
    p_delete.add_argument("name", help="Name of the VM to delete")
    p_delete.set_defaults(func=cmd_delete)

    # info
    p_info = sub.add_parser("info", help="Show detailed VM information")
    p_info.add_argument("name", help="Name of the VM")
    p_info.set_defaults(func=cmd_info)

    # shell
    p_shell = sub.add_parser("shell", help="Attach to a running VM console")
    p_shell.add_argument("name", help="Name of the running VM")
    p_shell.set_defaults(func=cmd_shell)

    # snapshot
    p_snap = sub.add_parser("snapshot", help="Create a VM snapshot")
    p_snap.add_argument("name", help="Name of the VM")
    p_snap.add_argument("snapshot_name", nargs="?", default=None, help="Optional snapshot label")
    p_snap.set_defaults(func=cmd_snapshot)

    return parser


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
