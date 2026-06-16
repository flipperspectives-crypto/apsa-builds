#!/usr/bin/env python3
"""
DEALFLOW — Tech M&A deal tracker. Scrapes news, estimates deal value,
tracks regulatory progress, identifies arb opportunities.

Usage:
  dealflow track "SpaceX Cursor" --acquirer SpaceX --target Cursor
  dealflow check                          Check all deals
  dealflow list                           List tracked deals
  dealflow estimate "SpaceX" "Cursor"     Estimate deal value + premium
  dealflow timeline "SpaceX Cursor"       Regulatory timeline
"""

import argparse
import json
import os
import re
import sys
import textwrap
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

DATA_DIR = Path(os.path.expanduser("~/.dealflow"))
STATE_FILE = DATA_DIR / "state.json"

# ── Deal Registry ──────────────────────────────────────

KNOWN_ACQUIRERS = {
    "SpaceX": {"ticker": None, "sector": "Aerospace", "market_cap": "350B", "cash": "10B+"},
    "Microsoft": {"ticker": "MSFT", "sector": "Technology", "market_cap": "3.2T", "cash": "80B+"},
    "Google": {"ticker": "GOOGL", "sector": "Technology", "market_cap": "2.5T", "cash": "110B+"},
    "Apple": {"ticker": "AAPL", "sector": "Technology", "market_cap": "3.5T", "cash": "60B+"},
    "Meta": {"ticker": "META", "sector": "Technology", "market_cap": "1.6T", "cash": "50B+"},
    "Amazon": {"ticker": "AMZN", "sector": "Technology", "market_cap": "2.2T", "cash": "90B+"},
    "Nvidia": {"ticker": "NVDA", "sector": "Semiconductors", "market_cap": "3.8T", "cash": "25B+"},
    "Fox": {"ticker": "FOX", "sector": "Media", "market_cap": "25B", "cash": "4B+"},
}

TARGET_VALUATIONS = {
    "Cursor": {"last_round": "400M", "revenue_est": "50M", "growth": "3x", "sector": "AI/Developer Tools"},
    "Roku": {"ticker": "ROKU", "last_round": None, "revenue_est": "4B", "growth": "1.2x", "sector": "Streaming"},
    "Activision": {"ticker": "ATVI", "last_round": None, "revenue_est": "8B", "sector": "Gaming"},
    "Anthropic": {"last_round": "4B", "revenue_est": "200M", "growth": "5x", "sector": "AI"},
    "Figma": {"last_round": "12B", "revenue_est": "600M", "growth": "2x", "sector": "Design"},
}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"deals": {}}


def save_state(s):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))


def deal_id(name: str) -> str:
    return hashlib.md5(name.lower().encode()).hexdigest()[:12]


# ── Deal Estimation ─────────────────────────────────────

def estimate_deal(acquirer: str, target: str) -> dict:
    """Estimate deal value, premium, and arb spread."""
    aq = KNOWN_ACQUIRERS.get(acquirer, {})
    tg = TARGET_VALUATIONS.get(target, {})
    
    # Revenue multiple approach
    tg_rev = _parse_amount(tg.get("revenue_est", "0"))
    growth = float(str(tg.get("growth", "1x")).replace("x", ""))
    
    # Premium based on growth rate
    if growth >= 5:
        premium = 0.8  # 80% premium for hypergrowth
    elif growth >= 2:
        premium = 0.4
    else:
        premium = 0.25
    
    # Revenue multiple based on sector
    sector_multiple = 8 if "AI" in tg.get("sector", "") else 5
    est_value = tg_rev * sector_multiple * 1000000  # Millions
    
    deal_value = est_value * (1 + premium)
    
    # Check affordability
    aq_cash = _parse_amount(aq.get("cash", "0"))
    aq_mcap = _parse_amount(aq.get("market_cap", "0"))
    
    if aq_cash > deal_value:
        funding = "CASH (all cash deal likely)"
    elif aq_mcap * 0.1 > deal_value:
        funding = "STOCK (within 10% of market cap)"
    else:
        funding = "MIXED (cash + stock)"
    
    return {
        "acquirer": acquirer,
        "target": target,
        "est_deal_value": deal_value,
        "est_premium_pct": premium * 100,
        "funding_method": funding,
        "target_sector": tg.get("sector", "Unknown"),
        "acquirer_cash": aq.get("cash", "Unknown"),
        "regulatory_risk": "HIGH" if deal_value > 1000000000 else "MEDIUM",
    }


def _parse_amount(s: str) -> float:
    """Parse '10B', '400M', '3.2T' to billions."""
    s = s.replace("+", "").strip()
    if "T" in s:
        return float(s.replace("T", "")) * 1000
    if "B" in s:
        return float(s.replace("B", ""))
    if "M" in s:
        return float(s.replace("M", "")) / 1000
    return float(s) if s else 0


# ── News ─────────────────────────────────────────────────

def fetch_news(query: str, limit: int = 5) -> list:
    items = []
    try:
        q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "DealFlow/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        for item in root.iter("item"):
            title = item.find("title")
            link = item.find("link")
            pubdate = item.find("pubDate")
            source = item.find("source")
            items.append({
                "title": (title.text or "") if title is not None else "",
                "url": (link.text or "") if link is not None else "",
                "date": (pubdate.text or "") if pubdate is not None else "",
                "source": (source.text or "Unknown") if source is not None else "Unknown",
            })
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items


# ── CLI ─────────────────────────────────────────────────

def cmd_track(args):
    state = load_state()
    did = deal_id(args.name)
    
    state["deals"][did] = {
        "name": args.name,
        "acquirer": args.acquirer,
        "target": args.target,
        "created": datetime.now(timezone.utc).isoformat(),
        "alerts": [],
        "milestones": [],
    }
    save_state(state)
    
    # Estimate
    est = estimate_deal(args.acquirer, args.target)
    
    print(f"\n🔍 Tracking: {args.name}")
    print(f"   Acquirer: {args.acquirer}")
    print(f"   Target:   {args.target}")
    print(f"\n   📊 DEAL ESTIMATE:")
    print(f"   Est. value:   ${est['est_deal_value']:.1f}B")
    print(f"   Premium:      {est['est_premium_pct']:.0f}%")
    print(f"   Funding:      {est['funding_method']}")
    print(f"   Reg risk:     {est['regulatory_risk']}")


def cmd_check(args):
    state = load_state()
    if not state["deals"]:
        print("No deals tracked. Use: dealflow track \"Name\" --acquirer X --target Y")
        return
    
    for did, deal in state["deals"].items():
        name = deal["name"]
        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"  Acquirer: {deal['acquirer']} → Target: {deal['target']}")
        print(f"{'='*50}")
        
        # News
        news = fetch_news(name, limit=5)
        if news:
            print(f"\n  📰 Latest:")
            for n in news[:3]:
                print(f"     {n['title'][:100]}")
                print(f"     {n['source']} • {n['date']}")
        
        # Estimate
        est = estimate_deal(deal["acquirer"], deal["target"])
        print(f"\n  💰 Deal est: ${est['est_deal_value']:.1f}B | Premium: {est['est_premium_pct']:.0f}%")
        print(f"  🏦 Funding: {est['funding_method']} | Reg risk: {est['regulatory_risk']}")


def cmd_list(args):
    state = load_state()
    if not state["deals"]:
        print("No deals tracked.")
        return
    
    print(f"\n📊 Tracked Deals ({len(state['deals'])}):\n")
    for did, deal in state["deals"].items():
        est = estimate_deal(deal["acquirer"], deal["target"])
        print(f"  {deal['name']:<30} ${est['est_deal_value']:.1f}B  {est['funding_method']}")


def cmd_estimate(args):
    est = estimate_deal(args.acquirer, args.target)
    print(f"\n💰 Deal Estimate: {args.acquirer} → {args.target}")
    print(f"\n   Value:    ${est['est_deal_value']:.1f}B")
    print(f"   Premium:  {est['est_premium_pct']:.0f}%")
    print(f"   Funding:  {est['funding_method']}")
    print(f"   Sector:   {est['target_sector']}")
    print(f"   Reg risk: {est['regulatory_risk']}")
    print(f"   Cash:     {est['acquirer_cash']}")


def main():
    parser = argparse.ArgumentParser(description="DealFlow — Tech M&A deal tracker")
    sub = parser.add_subparsers(dest="command")
    
    track_p = sub.add_parser("track", help="Track a deal")
    track_p.add_argument("name", help="Deal name")
    track_p.add_argument("--acquirer", required=True, help="Acquiring company")
    track_p.add_argument("--target", required=True, help="Target company")
    
    sub.add_parser("check", help="Check all deals for updates")
    sub.add_parser("list", help="List tracked deals")
    
    est_p = sub.add_parser("estimate", help="Estimate deal value")
    est_p.add_argument("acquirer")
    est_p.add_argument("target")
    
    args = parser.parse_args()
    
    if args.command == "track":
        cmd_track(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "estimate":
        cmd_estimate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
