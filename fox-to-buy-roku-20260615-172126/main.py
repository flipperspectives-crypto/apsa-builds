#!/usr/bin/env python3
"""
DEALWATCH — Track mergers, acquisitions, and regulatory filings.
Monitors news sources, SEC EDGAR, and FCC filings for deal status changes.

Usage:
  dealwatch track "Fox Roku"        Track a deal by name
  dealwatch list                     Show tracked deals
  dealwatch check                    Check all deals for updates
  dealwatch alert "Deal name"        Set up alert keywords
"""

import argparse
import json
import os
import sys
import time
import hashlib
import textwrap
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# ── Config ──────────────────────────────────────────────
DATA_DIR = Path(os.path.expanduser("~/.dealwatch"))
STATE_FILE = DATA_DIR / "state.json"


def load_state() -> dict:
    """Load or create state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"deals": {}, "last_check": None}


def save_state(state: dict) -> None:
    """Persist state atomically."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.rename(STATE_FILE)


def deal_id(name: str) -> str:
    return hashlib.md5(name.lower().encode()).hexdigest()[:12]


# ── News Sources ────────────────────────────────────────

def fetch_google_news(query: str, max_results: int = 10) -> list:
    """Scrape Google News RSS for deal mentions."""
    items = []
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "DealWatch/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        for item in root.iter("item"):
            title = item.find("title")
            link = item.find("link")
            pubdate = item.find("pubDate")
            items.append({
                "title": title.text if title is not None else "",
                "url": link.text if link is not None else "",
                "date": pubdate.text if pubdate is not None else "",
            })
            if len(items) >= max_results:
                break
    except Exception as e:
        items.append({"title": f"[News fetch error: {e}]", "url": "", "date": ""})
    return items


def fetch_hn_search(query: str, max_results: int = 5) -> list:
    """Search HN Algolia for deal mentions."""
    items = []
    try:
        url = f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(query)}&tags=story&hitsPerPage={max_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "DealWatch/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for hit in data.get("hits", []):
            items.append({
                "title": hit.get("title", ""),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "date": hit.get("created_at", ""),
                "points": hit.get("points", 0),
            })
    except Exception as e:
        pass
    return items


def fetch_sec_edgar(company_name: str) -> list:
    """Check SEC EDGAR for recent filings by company name."""
    filings = []
    try:
        # SEC EDGAR full-text search
        url = f"https://efts.sec.gov/LATEST/search-index?q={urllib.parse.quote(company_name)}&dateRange=custom&startdt=2026-06-01&enddt=2026-06-15&category=form-cat1"
        req = urllib.request.Request(url, headers={
            "User-Agent": "DealWatch/1.0 (contact@example.com)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        for hit in data.get("hits", {}).get("hits", [])[:5]:
            src = hit.get("_source", {})
            filings.append({
                "title": src.get("display_names", ["Unknown"])[0],
                "form": src.get("file_type", "?"),
                "date": src.get("file_date", ""),
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={urllib.parse.quote(company_name)}",
            })
    except Exception:
        pass
    return filings


# ── Alert Logic ─────────────────────────────────────────

TRIGGER_WORDS = [
    "approved", "blocked", "rejected", "cleared", "regulatory",
    "antitrust", "FTC", "DOJ", "investigation", "lawsuit",
    "terminated", "cancelled", "closed", "completed", "finalized",
    "merger", "acquisition", "buyout", "takeover", "tender offer",
    "shareholder vote", "proxy", "filing", "8-K", "S-4", "13D",
]


def scan_for_alerts(articles: list, deal_name: str) -> list:
    """Scan articles for alert-worthy keywords."""
    alerts = []
    name_lower = deal_name.lower()
    for art in articles:
        text = (art.get("title", "") + " " + art.get("url", "")).lower()
        triggers = [w for w in TRIGGER_WORDS if w.lower() in text]
        if triggers and any(term in text for term in name_lower.split()):
            alerts.append({
                **art,
                "triggers": triggers,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
    return alerts


# ── Commands ─────────────────────────────────────────────

def cmd_track(name: str, args) -> None:
    """Add a deal to track."""
    state = load_state()
    did = deal_id(name)
    
    if did in state["deals"]:
        print(f"Already tracking: {name}")
        return
    
    state["deals"][did] = {
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(),
        "keywords": args.keywords.split(",") if args.keywords else [name],
        "alerts": [],
        "article_ids": set(),
    }
    save_state(state)
    print(f"🔍 Now tracking: {name}")
    print(f"   Keywords: {state['deals'][did]['keywords']}")
    
    # Do initial check
    cmd_check_one(did, state)


def cmd_list(args) -> None:
    """List tracked deals."""
    state = load_state()
    if not state["deals"]:
        print("📭 No deals tracked. Use: dealwatch track \"Deal Name\"")
        return
    
    print(f"\n📊 Tracked Deals ({len(state['deals'])}):\n")
    for did, deal in state["deals"].items():
        alerts = len(deal.get("alerts", []))
        alert_str = f"🔴 {alerts} alerts" if alerts else "✅ no alerts"
        print(f"  {deal['name']:<40} {alert_str}")
    print()


def cmd_check_one(did: str, state: dict) -> None:
    """Check one deal for new info."""
    deal = state["deals"][did]
    name = deal["name"]
    
    print(f"\n🔎 Checking: {name}")
    
    all_articles = []
    for kw in deal["keywords"]:
        print(f"   News: {kw}...", end=" ", flush=True)
        articles = fetch_google_news(kw)
        print(f"{len(articles)} results")
        all_articles.extend(articles)
    
    # HN search
    print(f"   HN: {name}...", end=" ", flush=True)
    hn_articles = fetch_hn_search(name)
    print(f"{len(hn_articles)} results")
    all_articles.extend(hn_articles)
    
    # SEC check
    print(f"   SEC: {name.split()[0]}...", end=" ", flush=True)
    sec_filings = fetch_sec_edgar(name.split()[0])
    print(f"{len(sec_filings)} filings")
    all_articles.extend(sec_filings)
    
    # Deduplicate
    seen_urls = deal.get("article_ids", set())
    new_articles = []
    for art in all_articles:
        url_hash = hashlib.md5(art.get("url", "").encode()).hexdigest()[:8]
        if url_hash not in seen_urls:
            seen_urls.add(url_hash)
            new_articles.append(art)
    
    deal["article_ids"] = seen_urls
    
    # Scan for alerts
    alerts = scan_for_alerts(new_articles, name)
    if alerts:
        print(f"\n   🚨 {len(alerts)} NEW ALERTS:")
        for a in alerts:
            print(f"      [{', '.join(a['triggers'][:3])}] {a['title'][:100]}")
            print(f"       {a['url']}")
        deal["alerts"].extend(alerts)
    else:
        if new_articles:
            print(f"   📰 {len(new_articles)} new articles (no triggers)")
        else:
            print(f"   ✅ No new information")
    
    deal["last_checked"] = datetime.now(timezone.utc).isoformat()


def cmd_check(args) -> None:
    """Check all tracked deals for updates."""
    state = load_state()
    if not state["deals"]:
        print("📭 No deals tracked. Use: dealwatch track \"Deal Name\"")
        return
    
    for did in state["deals"]:
        cmd_check_one(did, state)
    
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    
    total_alerts = sum(len(d.get("alerts", [])) for d in state["deals"].values())
    print(f"\n📊 Check complete. {total_alerts} total alerts across {len(state['deals'])} deals.")


def cmd_remove(name: str, args) -> None:
    """Stop tracking a deal."""
    state = load_state()
    did = deal_id(name)
    if did in state["deals"]:
        del state["deals"][did]
        save_state(state)
        print(f"🗑️  Stopped tracking: {name}")
    else:
        print(f"❌ Not tracking: {name}")


def main():
    parser = argparse.ArgumentParser(
        description="DealWatch — Track M&A, regulatory filings, and deal news",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              dealwatch track "Fox Roku"
              dealwatch track "Microsoft Activision" --keywords "MSFT,ATVI,merger"
              dealwatch list
              dealwatch check
              dealwatch remove "Fox Roku"
        """),
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # track
    track_p = sub.add_parser("track", help="Track a deal")
    track_p.add_argument("name", help="Deal name")
    track_p.add_argument("--keywords", help="Comma-separated search keywords", default=None)

    # list
    sub.add_parser("list", help="List tracked deals")

    # check
    sub.add_parser("check", help="Check all deals for updates")

    # remove
    remove_p = sub.add_parser("remove", help="Stop tracking a deal")
    remove_p.add_argument("name", help="Deal name to remove")

    args = parser.parse_args()

    if args.command == "track":
        cmd_track(args.name, args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "remove":
        cmd_remove(args.name, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
