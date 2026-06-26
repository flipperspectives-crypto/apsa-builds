#!/usr/bin/env python3
"""
RetractWatch — CLI tool for tracking retracted academic papers.

Fetches retraction data from the Retraction Watch database API and
the OpenAlex API to identify retracted papers by author, journal,
publisher, or date range. Designed for investigative journalists,
researchers, and science watchdogs.

Usage:
    python3 main.py --help
    python3 main.py author "Max Planck"
    python3 main.py publisher "Springer Nature"
    python3 main.py recent --days 30
    python3 main.py stats
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

# ── Configuration ──────────────────────────────────────────────────

VERSION = "1.0.0"
USER_AGENT = "RetractWatch/1.0 (research tool; mailto:user@example.com)"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_TTL = 3600  # seconds


# ── Caching helpers ─────────────────────────────────────────────────

def _cache_path(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, safe + ".json")


def _cached(key: str) -> dict | None:
    path = _cache_path(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("_ts", 0) < CACHE_TTL:
            return data["body"]
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def _cache_set(key: str, body: dict) -> None:
    path = _cache_path(key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "body": body}, f)
    except OSError:
        pass


# ── HTTP helpers ────────────────────────────────────────────────────

def _fetch_json(url: str, params: dict | None = None) -> dict:
    """Fetch a URL and return parsed JSON."""
    cache_key = url + (json.dumps(params, sort_keys=True) if params else "")
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error fetching {url}: {e.reason}") from e

    _cache_set(cache_key, data)
    return data


# ── OpenAlex API (free, no key needed) ─────────────────────────────

OPENALEX_BASE = "https://api.openalex.org"


def search_retracted_author(author_name: str, limit: int = 20) -> list[dict]:
    """Search for retracted works by a given author name."""
    params = {
        "filter": "is_retracted:true",
        "search": author_name,
        "per_page": min(limit, 200),
        "sort": "publication_year:desc",
    }
    data = _fetch_json(f"{OPENALEX_BASE}/works", params)
    return data.get("results", [])


def search_retracted_publisher(publisher: str, limit: int = 20) -> list[dict]:
    """Search for retracted works from a given publisher."""
    params = {
        "filter": f"is_retracted:true,publishers:{publisher}",
        "per_page": min(limit, 200),
        "sort": "publication_year:desc",
    }
    data = _fetch_json(f"{OPENALEX_BASE}/works", params)
    return data.get("results", [])


def search_retracted_recent(days: int = 30, limit: int = 20) -> list[dict]:
    """Search for recently retracted works."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    params = {
        "filter": f"is_retracted:true,from_publication_date:{cutoff}",
        "per_page": min(limit, 200),
        "sort": "publication_year:desc",
    }
    data = _fetch_json(f"{OPENALEX_BASE}/works", params)
    return data.get("results", [])


def get_retraction_stats() -> dict:
    """Get aggregate statistics about retracted works."""
    data = _fetch_json(f"{OPENALEX_BASE}/works", {"filter": "is_retracted:true", "per_page": 1})
    total = data.get("meta", {}).get("count", 0)

    # Group by year — fetch top retraction years
    group_data = _fetch_json(
        f"{OPENALEX_BASE}/works",
        {"filter": "is_retracted:true", "group_by": "publication_year", "per_page": 15},
    )
    groups = group_data.get("group_by", [])
    years = {str(g["key"]): g["count"] for g in groups if g.get("key")}

    return {"total_retracted": total, "by_year": years}


# ── Display formatters ─────────────────────────────────────────────

def _fmt_work(w: dict) -> str:
    title = w.get("title", "Untitled")
    authors = w.get("authorships", [])
    author_names = [a.get("author", {}).get("display_name", "?") for a in authors[:5]]
    author_str = ", ".join(author_names)
    if len(authors) > 5:
        author_str += " et al."

    pub_year = w.get("publication_year", "?")
    journal = w.get("primary_location", {}).get("source", {}).get("display_name", "?")
    doi = w.get("doi", "")
    doi_str = f" ({doi})" if doi else ""

    lines = [
        f"  Title:   {title}",
        f"  Author:  {author_str}",
        f"  Year:    {pub_year}",
        f"  Journal: {journal}",
        f"  DOI:     {doi_str}",
        "",
    ]
    return "\n".join(lines)


def _fmt_stats(stats: dict) -> str:
    lines = [
        "╔══════════════════════════════════════════╗",
        "║        RETRACTION STATISTICS             ║",
        "╚══════════════════════════════════════════╝",
        f"  Total retracted works tracked: {stats['total_retracted']:,}",
        "",
        "  By publication year (top):",
    ]
    for year, count in sorted(stats.get("by_year", {}).items(), reverse=True)[:10]:
        bar = "█" * min(count // 50, 40)
        lines.append(f"    {year}: {count:>6,}  {bar}")
    lines.append("")
    lines.append("  (Data: OpenAlex API — openalex.org)")
    return "\n".join(lines)


# ── Command handlers ───────────────────────────────────────────────

def cmd_author(args: argparse.Namespace) -> int:
    name = args.author
    print(f"🔍 Searching for retracted works by: {name}")
    print()
    try:
        results = search_retracted_author(name, limit=args.limit)
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    if not results:
        print("  No retracted works found for this author.")
        return 0

    print(f"  Found {len(results)} retracted work(s):\n")
    for w in results:
        print(_fmt_work(w))
    return 0


def cmd_publisher(args: argparse.Namespace) -> int:
    name = args.publisher
    print(f"🔍 Searching for retracted works from publisher: {name}")
    print()
    try:
        results = search_retracted_publisher(name, limit=args.limit)
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    if not results:
        print("  No retracted works found for this publisher.")
        return 0

    print(f"  Found {len(results)} retracted work(s):\n")
    for w in results:
        print(_fmt_work(w))
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    days = args.days
    print(f"🔍 Searching for works retracted in the last {days} days...")
    print()
    try:
        results = search_retracted_recent(days=days, limit=args.limit)
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    if not results:
        print("  No recently retracted works found.")
        return 0

    print(f"  Found {len(results)} recently retracted work(s):\n")
    for w in results:
        print(_fmt_work(w))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    print("📊 Fetching retraction statistics...")
    print()
    try:
        stats = get_retraction_stats()
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    print(_fmt_stats(stats))
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    """Generate a full digest: stats + recent retractions."""
    print("═" * 50)
    print("  RETRACTWATCH DAILY DIGEST")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 50)
    print()

    # Stats
    try:
        stats = get_retraction_stats()
        print(f"  Total retracted works: {stats['total_retracted']:,}")
    except RuntimeError as e:
        print(f"  ⚠ Could not fetch stats: {e}")
    print()

    # Recent
    days = args.days
    try:
        results = search_retracted_recent(days=days, limit=args.limit)
        print(f"  Retractions in the last {days} days: {len(results)}")
        print()
        for w in results[:5]:
            title = w.get("title", "Untitled")[:80]
            doi = w.get("doi", "no DOI")
            print(f"    • {title}")
            print(f"      {doi}")
            print()
    except RuntimeError as e:
        print(f"  ⚠ Could not fetch recent retractions: {e}")
    return 0


# ── Argument parser ────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retractwatch",
        description="Track retracted academic papers via the OpenAlex API.",
        epilog="Data source: OpenAlex (https://openalex.org) — free, no API key needed.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"RetractWatch v{VERSION}",
    )

    sub = parser.add_subparsers(dest="command", help="Sub-commands")

    # author
    p_author = sub.add_parser("author", help="Search retracted works by author name")
    p_author.add_argument("author", type=str, help="Author name to search")
    p_author.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p_author.set_defaults(func=cmd_author)

    # publisher
    p_pub = sub.add_parser("publisher", help="Search retracted works by publisher")
    p_pub.add_argument("publisher", type=str, help="Publisher name to search")
    p_pub.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p_pub.set_defaults(func=cmd_publisher)

    # recent
    p_rec = sub.add_parser("recent", help="Search recently retracted works")
    p_rec.add_argument("--days", type=int, default=30, help="Lookback days (default: 30)")
    p_rec.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p_rec.set_defaults(func=cmd_recent)

    # stats
    sub.add_parser("stats", help="Show retraction statistics").set_defaults(func=cmd_stats)

    # digest
    p_dig = sub.add_parser("digest", help="Full daily digest report")
    p_dig.add_argument("--days", type=int, default=30, help="Lookback days for recent (default: 30)")
    p_dig.add_argument("--limit", type=int, default=10, help="Max recent results (default: 10)")
    p_dig.set_defaults(func=cmd_digest)

    return parser


# ── Main entrypoint ────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except (RuntimeError, ConnectionError) as e:
        print(f"❌ Fatal: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
