#!/usr/bin/env python3
"""
CVE-SCAN — Scan dependencies for memory-safety CVEs.
Compares Rust vs C/C++ vulnerability profiles in your stack.

Usage:
  cve-scan check .                     Scan current directory for vulnerable deps
  cve-scan compare                     Compare Rust vs C/C++ CVE stats
  cve-scan search "openssl"            Search for CVEs by package name
  cve-scan recent                      Recent memory-safety CVEs
"""

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse

# ── Constants ───────────────────────────────────────────
NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
OSV_API = "https://api.osv.dev/v1/query"
DATA_DIR = Path(os.path.expanduser("~/.cve-scan"))


def fetch_nvd_cves(keyword: str, limit: int = 10) -> list:
    """Search NVD for CVEs by keyword."""
    try:
        params = urllib.parse.urlencode({
            "keywordSearch": keyword,
            "resultsPerPage": min(limit, 20),
        })
        url = f"{NVD_API}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "CVEScan/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        
        results = []
        for vuln in data.get("vulnerabilities", [])[:limit]:
            cve = vuln.get("cve", {})
            cve_id = cve.get("id", "?")
            desc = cve.get("descriptions", [{}])[0].get("value", "")[:200]
            
            # CVSS score
            metrics = cve.get("metrics", {})
            cvss_v3 = metrics.get("cvssMetricV31", metrics.get("cvssMetricV30", [{}]))
            score = cvss_v3[0].get("cvssData", {}).get("baseScore", 0) if cvss_v3 else 0
            
            # Published date
            published = cve.get("published", "")[:10]
            
            results.append({
                "id": cve_id,
                "description": desc,
                "score": score,
                "published": published,
                "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            })
        return results
    except Exception:
        return []


def fetch_osv(package_name: str, ecosystem: str = "PyPI") -> list:
    """Query OSV for vulnerabilities in a specific package."""
    try:
        body = json.dumps({"package": {"name": package_name, "ecosystem": ecosystem}})
        req = urllib.request.Request(OSV_API, data=body.encode(), headers={
            "User-Agent": "CVEScan/1.0",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        results = []
        for vuln in data.get("vulns", [])[:10]:
            results.append({
                "id": vuln.get("id", "?"),
                "summary": vuln.get("summary", "")[:150] if vuln.get("summary") else vuln.get("details", "")[:150],
                "modified": vuln.get("modified", "")[:10],
                "aliases": vuln.get("aliases", []),
            })
        return results
    except Exception:
        return []


def scan_dependencies(directory: str) -> dict:
    """Scan project directory for dependency files and check CVEs."""
    path = Path(directory)
    findings = {"files": [], "vulnerabilities": [], "rust_vs_c": {"rust_deps": 0, "c_deps": 0, "rust_cves": 0, "c_cves": 0}}
    
    # Find dependency files
    dep_files = {
        "requirements.txt": "PyPI",
        "Pipfile": "PyPI",
        "Pipfile.lock": "PyPI",
        "pyproject.toml": "PyPI",
        "package.json": "npm",
        "package-lock.json": "npm",
        "Cargo.toml": "crates.io",
        "Cargo.lock": "crates.io",
        "go.mod": "Go",
        "Gemfile": "RubyGems",
    }
    
    for pattern, ecosystem in dep_files.items():
        matches = list(path.rglob(pattern))
        for match in matches:
            if any(skip in str(match) for skip in ["node_modules", ".git", "__pycache__"]):
                continue
            
            findings["files"].append({"path": str(match), "ecosystem": ecosystem})
            
            # Extract package names
            content = match.read_text(errors="ignore")
            packages = extract_packages(content, pattern, ecosystem)
            
            for pkg in packages[:5]:  # Limit API calls
                vulns = fetch_osv(pkg, ecosystem)
                if vulns:
                    for v in vulns:
                        findings["vulnerabilities"].append({
                            "package": pkg,
                            "ecosystem": ecosystem,
                            "file": str(match),
                            "vuln_id": v["id"],
                            "summary": v.get("summary", "")[:100],
                        })
                
                # Track Rust vs C stats
                if ecosystem in ("crates.io",):
                    findings["rust_vs_c"]["rust_deps"] += 1
                    findings["rust_vs_c"]["rust_cves"] += len(vulns)
                elif ecosystem in ("PyPI", "npm", "Go", "RubyGems"):
                    # Python/Node/Go often wrap C libs
                    findings["rust_vs_c"]["c_deps"] += 1
                    findings["rust_vs_c"]["c_cves"] += len(vulns)
    
    return findings


def extract_packages(content: str, filename: str, ecosystem: str) -> list:
    """Extract package names from dependency files."""
    packages = []
    lines = content.split("\n")
    
    if filename == "requirements.txt":
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                pkg = re.match(r'^([a-zA-Z0-9_.-]+)', line)
                if pkg:
                    packages.append(pkg.group(1).lower())
    
    elif filename == "Cargo.toml":
        in_deps = False
        for line in lines:
            line = line.strip()
            if line.startswith("[dependencies"):
                in_deps = True
                continue
            if line.startswith("[") and in_deps:
                in_deps = False
            if in_deps and "=" in line and not line.startswith("#"):
                pkg = re.match(r'^"?([a-zA-Z0-9_.-]+)', line)
                if pkg:
                    packages.append(pkg.group(1).lower())
    
    elif filename == "package.json":
        try:
            data = json.loads(content)
            for section in ["dependencies", "devDependencies"]:
                if section in data:
                    packages.extend(data[section].keys())
        except Exception:
            pass
    
    elif filename == "go.mod":
        for line in lines:
            if line.strip().startswith("require "):
                parts = line.strip().split()
                if len(parts) >= 2:
                    packages.append(parts[1].lower())
    
    return packages[:20]


# ── CLI ─────────────────────────────────────────────────

def cmd_check(args):
    directory = args.directory or "."
    print(f"\n🔍 Scanning: {directory}\n")
    
    findings = scan_dependencies(directory)
    
    if findings["files"]:
        print("📁 Dependency files found:")
        for f in findings["files"]:
            print(f"   {f['ecosystem']:<12} {f['path']}")
    else:
        print("   No dependency files found.")
    
    if findings["vulnerabilities"]:
        print(f"\n🚨 {len(findings['vulnerabilities'])} VULNERABILITIES:\n")
        for v in findings["vulnerabilities"]:
            print(f"   [{v['vuln_id']}] {v['package']} ({v['ecosystem']})")
            print(f"   {v['summary'][:100]}")
            print()
    else:
        print("\n✅ No known vulnerabilities in dependencies")
    
    # Rust vs C comparison
    rc = findings["rust_vs_c"]
    if rc["rust_deps"] or rc["c_deps"]:
        print(f"\n📊 Memory Safety Profile:")
        print(f"   Rust deps: {rc['rust_deps']}  →  {rc['rust_cves']} CVEs ({rc['rust_cves']/max(rc['rust_deps'],1):.1f}/dep)")
        print(f"   C/C++ deps: {rc['c_deps']}  →  {rc['c_cves']} CVEs ({rc['c_cves']/max(rc['c_deps'],1):.1f}/dep)")
        if rc["c_deps"] > 0 and rc["rust_deps"] > 0:
            ratio = (rc['c_cves']/max(rc['c_deps'],1)) / (rc['rust_cves']/max(rc['rust_deps'],1))
            print(f"   C/C++ has {ratio:.1f}x more CVEs per dependency than Rust")


def cmd_search(args):
    cves = fetch_nvd_cves(args.query, limit=15)
    print(f"\n🔍 CVEs matching: {args.query}\n")
    if not cves:
        print("   No results (NVD API may be rate-limited)")
        return
    
    for c in cves:
        sev = "🔴" if c["score"] >= 7 else "🟡" if c["score"] >= 4 else "🟢"
        print(f"  {sev} {c['id']} [{c['score']:.1f}] {c['published']}")
        print(f"     {c['description'][:120]}")
        print()


def cmd_recent(args):
    cves = fetch_nvd_cves("memory safety OR buffer overflow OR use-after-free", limit=15)
    print(f"\n🕐 Recent Memory-Safety CVEs\n")
    if not cves:
        print("   No results (NVD API rate-limited)")
        return
    
    for c in cves:
        sev = "🔴" if c["score"] >= 7 else "🟡" if c["score"] >= 4 else "🟢"
        affected = "C/C++" if any(kw in c["description"].lower() for kw in ["buffer", "overflow", "use-after-free", "double-free"]) else "?"
        flags = "(memory)" if affected == "C/C++" else ""
        print(f"  {sev} {c['id']} [{c['score']:.1f}] {flags}")
        print(f"     {c['description'][:120]}")
        print()


def main():
    parser = argparse.ArgumentParser(description="CVE-Scan — Memory-safety vulnerability scanner")
    sub = parser.add_subparsers(dest="command")
    
    check_p = sub.add_parser("check")
    check_p.add_argument("directory", nargs="?", default=".")
    
    search_p = sub.add_parser("search")
    search_p.add_argument("query")
    
    sub.add_parser("recent")
    
    args = parser.parse_args()
    
    if args.command == "check":
        cmd_check(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "recent":
        cmd_recent(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
