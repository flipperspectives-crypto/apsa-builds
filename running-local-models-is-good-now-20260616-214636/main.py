#!/usr/bin/env python3
"""local-model-capability-scanner — check if your machine is ready to run local LLMs.

Inspired by "Running local models is good now" (Vicki Boykis, 2026).
Scans for frameworks (llama.cpp, ollama, vllm, mlx, pytorch, transformers),
reports system specs, and produces a readiness score.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

VERSION = "1.0.0"


def run(cmd: list[str], timeout: float = 10) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return ""


def check_command(name: str, version_flag: str = "--version") -> dict[str, Any]:
    """Check if a CLI tool is installed and get its version."""
    path = shutil.which(name)
    if not path:
        return {"installed": False, "path": None, "version": None}
    version = run([name, version_flag], timeout=5)
    if not version:
        version = run([name, "-v"], timeout=5)
    return {"installed": True, "path": path, "version": version or "unknown"}


def check_python_package(name: str) -> dict[str, Any]:
    """Check if a Python package is importable."""
    try:
        __import__(name)
        import importlib.metadata
        try:
            ver = importlib.metadata.version(name)
        except Exception:
            ver = "installed"
        return {"installed": True, "version": ver}
    except ImportError:
        return {"installed": False, "version": None}


def get_system_info() -> dict[str, Any]:
    """Gather system specifications."""
    info: dict[str, Any] = {
        "os": platform.system(),
        "os_version": platform.version() or platform.release(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "ram_mb": None,
    }
    # Try to get RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    info["ram_mb"] = round(kb / 1024)
                    break
    except Exception:
        pass
    # Try platform-specific RAM detection
    if info["ram_mb"] is None:
        if sys.platform == "darwin":
            mem = run(["sysctl", "-n", "hw.memsize"])
            if mem and mem.isdigit():
                info["ram_mb"] = int(mem) // (1024 * 1024)
    return info


def scan_frameworks() -> list[dict[str, Any]]:
    """Discover installed local-model frameworks."""
    frameworks = []

    # llama.cpp
    llama = check_command("llama-cli")
    if not llama["installed"]:
        llama = check_command("main", version_flag="--version")  # legacy name
    frameworks.append({"name": "llama.cpp", **llama})

    # ollama
    ollama = check_command("ollama")
    if ollama["installed"]:
        models = run(["ollama", "list"], timeout=10)
        ollama["models"] = models.split("\n") if models else []
    else:
        ollama["models"] = []
    frameworks.append({"name": "ollama", **ollama})

    # vLLM
    vllm = check_python_package("vllm")
    frameworks.append({"name": "vLLM (Python)", **vllm})

    # MLX (Apple Silicon)
    mlx = check_python_package("mlx")
    frameworks.append({"name": "MLX (Python, Apple)", **mlx})

    # PyTorch
    torch = check_python_package("torch")
    if torch["installed"]:
        try:
            import torch as _t
            torch["cuda"] = _t.cuda.is_available()
            torch["mps"] = hasattr(_t.backends, "mps") and _t.backends.mps.is_available()
        except Exception:
            torch["cuda"] = False
            torch["mps"] = False
    else:
        torch["cuda"] = False
        torch["mps"] = False
    frameworks.append({"name": "PyTorch (Python)", **torch})

    # Transformers
    hf = check_python_package("transformers")
    frameworks.append({"name": "HuggingFace Transformers", **hf})

    # llama-cpp-python
    lcpp = check_python_package("llama_cpp")
    frameworks.append({"name": "llama-cpp-python", **lcpp})

    # exo
    exo = check_python_package("exo")
    frameworks.append({"name": "exo (distributed)", **exo})

    return frameworks


def compute_readiness(system: dict, frameworks: list[dict]) -> dict[str, Any]:
    """Compute a readiness score and recommendations."""
    score = 0
    details = []

    # CPU + RAM baseline
    ram = system.get("ram_mb", 0) or 0
    if ram >= 16000:
        score += 30
        details.append("✅ 16+ GB RAM — comfortable for 7B models")
    elif ram >= 8000:
        score += 20
        details.append("⚠️  8-16 GB RAM — can run quantized 7B models")
    else:
        score += 5
        details.append("❌ <8 GB RAM — very limited; try 1-3B quantized models")

    if system.get("cpu_count", 0) >= 6:
        score += 10
        details.append("✅ Multi-core CPU (6+)")
    else:
        score += 5
        details.append("⚠️  Few CPU cores")

    # Framework presence
    installed = [f for f in frameworks if f["installed"]]
    if len(installed) >= 3:
        score += 25
        details.append("✅ Multiple frameworks installed — rich ecosystem")
    elif len(installed) >= 1:
        score += 15
        details.append("⚠️  At least one framework available")
    else:
        score += 2
        details.append("❌ No frameworks installed — install ollama or llama.cpp")

    for fw in installed:
        details.append(f"   📦 {fw['name']}: {fw.get('version', 'unknown')}")

    # GPU acceleration
    has_gpu = any(
        f.get("cuda") or f.get("mps") or f.get("name") == "MLX (Python, Apple)" and f["installed"]
        for f in installed
    )
    if has_gpu:
        score += 20
        details.append("✅ GPU acceleration available")
    else:
        if system.get("architecture", "") in ("arm64", "aarch64") and system.get("os") == "Darwin":
            score += 10
            details.append("⚠️  Apple Silicon without MLX — install MLX for best perf")

    # Cap
    score = min(score, 100)

    tier = "gold" if score >= 70 else "silver" if score >= 40 else "bronze"
    return {"score": score, "tier": tier, "details": details}


def generate_report(
    system: dict[str, Any],
    frameworks: list[dict[str, Any]],
    readiness: dict[str, Any],
    output_format: str = "text",
) -> str:
    """Produce the final report."""
    if output_format == "json":
        return json.dumps({
            "system": system,
            "frameworks": [
                {k: v for k, v in f.items() if k != "models"}
                for f in frameworks
            ],
            "readiness": readiness,
            "generated_by": f"local-model-scanner v{VERSION}",
        }, indent=2)

    # Plain text report
    lines = []
    lines.append("╔══════════════════════════════════╗")
    lines.append("║  LOCAL MODEL READINESS REPORT   ║")
    lines.append("╚══════════════════════════════════╝")
    lines.append(f"  Score: {readiness['score']}/100  [{readiness['tier'].upper()}]")
    lines.append("")
    lines.append("── System ──")
    lines.append(f"  OS:      {system['os']} {system['os_version']}")
    lines.append(f"  Arch:    {system['architecture']}")
    lines.append(f"  Python:  {system['python_version']}")
    lines.append(f"  CPU:     {system['cpu_count']} cores")
    ram_str = f"{system['ram_mb']} MB" if system['ram_mb'] else "unknown"
    lines.append(f"  RAM:     {ram_str}")
    lines.append("")
    lines.append("── Frameworks ──")
    for fw in frameworks:
        status = "✓" if fw["installed"] else "✗"
        ver = fw.get("version") or "-"
        lines.append(f"  {status} {fw['name']:30s} {ver}")
        if fw.get("cuda"):
            lines.append("       CUDA available")
        if fw.get("mps"):
            lines.append("       MPS available")
        if fw.get("models"):
            for m in fw["models"][:5]:
                if m.strip():
                    lines.append(f"       └─ {m.strip()}")
    lines.append("")
    lines.append("── Assessment ──")
    for detail in readiness["details"]:
        lines.append(f"  {detail}")
    lines.append("")
    lines.append("── Quick Start ──")
    ollama_ok = any(f["name"] == "ollama" and f["installed"] for f in frameworks)
    llama_ok = any(f["name"] == "llama.cpp" and f["installed"] for f in frameworks)

    if ollama_ok:
        lines.append("  You have ollama! Try:")
        lines.append("    ollama run llama3.2    # 3B model")
        lines.append("    ollama run phi4        # 14B model")
    elif llama_ok:
        lines.append("  You have llama.cpp! Download a GGUF and run:")
        lines.append("    llama-cli -m model.gguf -p 'Hello'")
    else:
        lines.append("  Install ollama (easiest):")
        lines.append("    curl -fsSL https://ollama.com/install.sh | sh")
        lines.append("    ollama pull llama3.2")
        lines.append("    ollama run llama3.2")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"local-model-capability-scanner v{VERSION} — "
                    "Check if your machine is ready for local LLMs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  # Full text report
  python main.py --json           # JSON output
  python main.py --frameworks     # List only framework status
  python main.py --version        # Show version

Inspired by: "Running local models is good now"
  https://vickiboykis.com/2026/06/15/running-local-models-is-good-now/
        """,
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output report as JSON instead of plain text"
    )
    parser.add_argument(
        "--frameworks", action="store_true",
        help="Show only framework scan results"
    )
    parser.add_argument(
        "--version", action="store_true",
        help=f"Show version (v{VERSION}) and exit"
    )
    args = parser.parse_args()

    if args.version:
        print(f"local-model-capability-scanner v{VERSION}")
        sys.exit(0)

    system = get_system_info()

    if args.frameworks:
        frameworks = scan_frameworks()
        for fw in frameworks:
            status = "INSTALLED" if fw["installed"] else "MISSING"
            ver = fw.get("version") or "-"
            print(f"  [{status:10s}] {fw['name']:30s} {ver}")
        sys.exit(0)

    frameworks = scan_frameworks()
    readiness = compute_readiness(system, frameworks)
    output_format = "json" if args.json else "text"
    report = generate_report(system, frameworks, readiness, output_format)
    print(report)


if __name__ == "__main__":
    main()
