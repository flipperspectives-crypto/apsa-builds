#!/usr/bin/env python3
"""
M&A RADAR — Real-time merger & acquisition intelligence dashboard.
Integrates DealWatch state, SEC EDGAR filings, stock prices, court dockets.

Usage:
  ma-radar                           Start dashboard on :8090
  ma-radar track "Fox Roku"          Track a deal (also loads into DealWatch)
  ma-radar list                      List tracked deals
  ma-radar check                     Check all deals for new intel
  ma-radar filings AAPL              View recent SEC filings for a ticker
  ma-radar price TSLA                Get current stock price
  ma-radar --port 8080               Custom dashboard port
"""

import argparse
import json
import os
import sys
import time
import hashlib
import textwrap
import re
from datetime import datetime, timezone
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# ── Constants ───────────────────────────────────────────
DATA_DIR = Path(os.path.expanduser("~/.maradar"))
STATE_FILE = DATA_DIR / "state.json"
DEALWATCH_STATE = Path(os.path.expanduser("~/.dealwatch/state.json"))
DEFAULT_PORT = 8090
SEC_UA = "MARadar/1.0 (flipperspectives@github.io)"

# ── State ───────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"deals": {}}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.rename(STATE_FILE)


def load_dealwatch() -> dict:
    if DEALWATCH_STATE.exists():
        return json.loads(DEALWATCH_STATE.read_text())
    return {"deals": {}}


def deal_id(name: str) -> str:
    return hashlib.md5(name.lower().encode()).hexdigest()[:12]


# ── Company/Ticker Mapping ──────────────────────────────

COMPANY_TICKERS_CACHE = {}
TICKERS_CACHE_FILE = DATA_DIR / "company_tickers.json"

# Built-in fallback for common M&A stocks (ticker -> CIK)
BUILTIN_TICKERS = {
    "AAPL": "0000320193", "MSFT": "0000789019", "GOOGL": "0001652044",
    "AMZN": "0001018724", "META": "0001326801", "TSLA": "0001318605",
    "NVDA": "0001045810", "NFLX": "0001065280", "DIS": "0001744489",
    "FOX": "0001754301", "FOXA": "0001754301", "ROKU": "0001428439",
    "ATVI": "0000718877", "CRM": "0001108524", "TWTR": "0001418091",
    "JPM": "0000019617", "BAC": "0000070858", "WFC": "0000072971",
    "V": "0001403161", "MA": "0001141391", "PYPL": "0001633917",
    "INTC": "0000050863", "AMD": "0000002488", "QCOM": "0000804328",
}


def load_company_tickers() -> dict:
    """Load SEC company_tickers, with local cache and built-in fallback."""
    global COMPANY_TICKERS_CACHE
    if COMPANY_TICKERS_CACHE:
        return COMPANY_TICKERS_CACHE
    
    # Try local cache first
    if TICKERS_CACHE_FILE.exists():
        try:
            cache = json.loads(TICKERS_CACHE_FILE.read_text())
            age = time.time() - cache.get("_fetched_at", 0)
            if age < 86400:  # 24h cache
                COMPANY_TICKERS_CACHE = cache.get("tickers", {})
                return COMPANY_TICKERS_CACHE
        except Exception:
            pass
    
    # Try SEC API
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        req = urllib.request.Request(url, headers={
            "User-Agent": SEC_UA,
            "Accept": "application/json",
            "Host": "www.sec.gov",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        for v in data.values():
            ticker = v["ticker"].upper()
            COMPANY_TICKERS_CACHE[ticker] = {
                "cik": str(v["cik_str"]).zfill(10),
                "name": v["title"],
            }
        # Cache to disk
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TICKERS_CACHE_FILE.write_text(json.dumps({
            "tickers": COMPANY_TICKERS_CACHE,
            "_fetched_at": time.time(),
        }))
    except Exception:
        pass
    
    # Fall back to built-in
    if not COMPANY_TICKERS_CACHE:
        for ticker, cik in BUILTIN_TICKERS.items():
            COMPANY_TICKERS_CACHE[ticker] = {"cik": cik, "name": ticker}
    
    return COMPANY_TICKERS_CACHE


def ticker_to_cik(ticker: str) -> str:
    """Get CIK for a ticker."""
    tickers = load_company_tickers()
    entry = tickers.get(ticker.upper())
    if entry:
        return entry["cik"]
    return ""


# ── SEC EDGAR ───────────────────────────────────────────

def fetch_sec_filings(ticker: str, limit: int = 10) -> list:
    """Fetch recent SEC filings for a ticker via EDGAR RSS feed."""
    cik = ticker_to_cik(ticker)
    if not cik:
        return []
    
    filings = []
    cik_stripped = cik.lstrip("0")
    
    try:
        # Use SEC EDGAR RSS — more reliable than submissions API
        url = f"https://data.sec.gov/rss?cik={cik_stripped}&type=3,4,5,8-K,10-K,10-Q,S-4,13D&count={limit}"
        req = urllib.request.Request(url, headers={
            "User-Agent": SEC_UA,
            "Accept": "application/xml",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
        
        # Parse RSS XML
        root = ET.fromstring(raw)
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            date_el = item.find("pubDate") or item.find("{http://www.w3.org/2005/Atom}updated")
            
            title = title_el.text if title_el is not None else ""
            link = link_el.text if link_el is not None else ""
            date_str = date_el.text if date_el is not None else ""
            
            # Extract form type from title (e.g. "8-K - Tesla, Inc.")
            form_match = re.match(r'([\w/-]+)', title)
            form = form_match.group(1) if form_match else "?"
            
            if form not in ("3", "4", "5"):
                filings.append({
                    "ticker": ticker.upper(),
                    "form": form,
                    "date": date_str[:10] if date_str else "",
                    "description": title[title.find(" - ")+3:] if " - " in title else title,
                    "url": link,
                })
        
        return filings[:limit]
    except Exception:
        pass
    
    # Fallback: try submissions API
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        req = urllib.request.Request(url, headers={
            "User-Agent": SEC_UA,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        descs = recent.get("primaryDocDescription", [])
        accessions = recent.get("accessionNumber", [])
        
        for i in range(min(limit, len(forms))):
            acc = accessions[i].replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{docs[i]}"
            filings.append({
                "ticker": ticker.upper(),
                "form": forms[i],
                "date": dates[i],
                "description": descs[i] if i < len(descs) else "",
                "url": filing_url,
            })
    except Exception:
        pass
    
    return filings


def search_sec_form(form_type: str, ticker: str = None, limit: int = 5) -> list:
    """Search for specific SEC forms (8-K, S-4, 13D, etc.)"""
    results = []
    if ticker:
        filings = fetch_sec_filings(ticker, limit=50)
        return [f for f in filings if f["form"] == form_type][:limit]
    return results


# ── Stock Prices ────────────────────────────────────────

def fetch_stock_price(ticker: str) -> dict:
    """Get current stock price via Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "MARadar/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        
        result = data["chart"]["result"][0]
        meta = result["meta"]
        quotes = result["indicators"]["quote"][0]
        
        # Current price
        current = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("previousClose", current)
        change = current - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        
        # 5-day prices
        timestamps = result.get("timestamp", [])
        closes = quotes.get("close", [])
        prices_5d = [
            {"date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
             "close": round(c, 2)}
            for ts, c in zip(timestamps[-5:], closes[-5:])
            if c is not None
        ]
        
        return {
            "ticker": ticker.upper(),
            "price": round(current, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "prev_close": round(prev_close, 2),
            "high": round(meta.get("regularMarketDayHigh", 0), 2),
            "low": round(meta.get("regularMarketDayLow", 0), 2),
            "volume": meta.get("regularMarketVolume", 0),
            "currency": meta.get("currency", "USD"),
            "prices_5d": prices_5d,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)[:100]}


# ── Court Dockets ───────────────────────────────────────

def fetch_court_dockets(query: str, limit: int = 5) -> list:
    """Search CourtListener for merger-related dockets."""
    try:
        q = urllib.parse.quote(f"{query} merger OR acquisition OR antitrust")
        url = f"https://www.courtlistener.com/api/rest/v4/dockets/?q={q}&order_by=dateFiled desc"
        req = urllib.request.Request(url, headers={"User-Agent": "MARadar/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        results = []
        for d in data.get("results", [])[:limit]:
            results.append({
                "title": d.get("caseName", "Unknown"),
                "court": d.get("court", ""),
                "date": d.get("dateFiled", ""),
                "docket_number": d.get("docketNumber", ""),
                "url": f"https://www.courtlistener.com{d.get('absolute_url', '')}",
            })
        return results
    except Exception:
        return []


# ── Deal Intelligence ───────────────────────────────────

def check_deal(deal_name: str, tickers: list = None) -> dict:
    """Full intel sweep for a deal."""
    intel = {
        "name": deal_name,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "filings": [],
        "prices": [],
        "dockets": [],
    }
    
    # If tickers provided, pull filings + prices
    if tickers:
        for t in tickers:
            filings = fetch_sec_filings(t, limit=5)
            if filings:
                intel["filings"].extend(filings)
            price = fetch_stock_price(t)
            if "error" not in price:
                intel["prices"].append(price)
    
    # Court dockets
    intel["dockets"] = fetch_court_dockets(deal_name, limit=5)
    
    return intel


def scan_for_material_events(filings: list) -> list:
    """Flag material M&A filings: 8-K item 1.01, S-4, 13D, SC 13G, SC TO-T"""
    material_forms = {"8-K", "S-4", "13D", "SC 13D", "SC 13G", "SC TO-T", "SC TO-C",
                      "425", "14D-9", "PREM14A", "DEFM14A"}
    alerts = []
    for f in filings:
        if f["form"] in material_forms:
            alerts.append({
                "ticker": f["ticker"],
                "form": f["form"],
                "date": f["date"],
                "description": f["description"],
                "url": f["url"],
            })
    return alerts


# ── News (Google News RSS) ──────────────────────────────

def fetch_news(query: str, limit: int = 8) -> list:
    """Scrape Google News for deal mentions."""
    items = []
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "MARadar/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        for item in root.iter("item"):
            title = item.find("title")
            link = item.find("link")
            pubdate = item.find("pubDate")
            source = item.find("source")
            items.append({
                "title": title.text if title is not None else "",
                "url": link.text if link is not None else "",
                "date": pubdate.text if pubdate is not None else "",
                "source": source.text if source is not None else "Unknown",
            })
            if len(items) >= limit:
                break
    except Exception:
        pass
    return items


# ── Deal Management ─────────────────────────────────────

def cmd_track(name: str, tickers_str: str = None) -> None:
    """Track a deal with optional ticker symbols."""
    state = load_state()
    did = deal_id(name)
    
    tickers = [t.strip().upper() for t in tickers_str.split(",")] if tickers_str else []
    
    if did in state["deals"]:
        # Update tickers
        existing = set(state["deals"][did].get("tickers", []))
        existing.update(tickers)
        state["deals"][did]["tickers"] = list(existing)
        print(f"Updated: {name} (tickers: {', '.join(existing)})")
    else:
        state["deals"][did] = {
            "name": name,
            "tickers": tickers,
            "created": datetime.now(timezone.utc).isoformat(),
            "last_intel": None,
        }
        print(f"🔍 Tracking: {name}")
        if tickers:
            print(f"   Tickers: {', '.join(tickers)}")
    
    save_state(state)
    
    # Also add to DealWatch for backward compat
    dw_state = load_dealwatch()
    if did not in dw_state.get("deals", {}):
        dw_state.setdefault("deals", {})[did] = {
            "name": name,
            "created": datetime.now(timezone.utc).isoformat(),
            "keywords": [name] + tickers,
            "alerts": [],
            "article_ids": [],
        }
        DEALWATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        DEALWATCH_STATE.write_text(json.dumps(dw_state, indent=2, default=str))


def cmd_list() -> None:
    """List tracked deals."""
    state = load_state()
    if not state["deals"]:
        print("📭 No deals tracked. Use: ma-radar track \"Deal Name\" --tickers AAPL,MSFT")
        return
    
    print(f"\n📊 M&A Radar — {len(state['deals'])} Deals\n")
    for did, deal in state["deals"].items():
        tickers = ", ".join(deal.get("tickers", [])) or "none"
        last = deal.get("last_intel", "never")
        if last and last != "never":
            try:
                last = datetime.fromisoformat(last).strftime("%b %d %H:%M")
            except:
                pass
        print(f"  {deal['name']:<35} [{tickers:<15}] last: {last}")
    print()


def cmd_check() -> None:
    """Check all tracked deals for intel."""
    state = load_state()
    if not state["deals"]:
        print("📭 No deals tracked.")
        return
    
    all_alerts = []
    
    for did, deal in state["deals"].items():
        name = deal["name"]
        tickers = deal.get("tickers", [])
        
        print(f"\n🔎 {name}")
        
        if tickers:
            # SEC filings
            for t in tickers:
                filings = fetch_sec_filings(t, limit=5)
                if filings:
                    print(f"   📄 {t}: {len(filings)} filings")
                    for f in filings[:3]:
                        print(f"      [{f['form']}] {f['date']} {f['description'][:60]}")
                    
                    material = scan_for_material_events(filings)
                    if material:
                        for m in material:
                            print(f"      🚨 MATERIAL: [{m['form']}] {m['description']}")
                            all_alerts.append({**m, "deal": name})
            
            # Stock prices
            for t in tickers:
                price = fetch_stock_price(t)
                if "error" not in price:
                    arrow = "📈" if price["change"] >= 0 else "📉"
                    print(f"   💰 {t}: ${price['price']} {arrow} {price['change_pct']:+.1f}%")
        
        # News
        news = fetch_news(name, limit=3)
        if news:
            print(f"   📰 {len(news)} news items")
            for n in news[:2]:
                print(f"      {n['title'][:100]}")
        
        # Court dockets
        dockets = fetch_court_dockets(name, limit=3)
        if dockets:
            print(f"   ⚖️  {len(dockets)} court dockets")
            for d in dockets[:2]:
                print(f"      {d['title'][:80]}")
        
        # Save intel timestamp
        deal["last_intel"] = datetime.now(timezone.utc).isoformat()
    
    save_state(state)
    
    if all_alerts:
        print(f"\n🚨 {len(all_alerts)} MATERIAL EVENTS DETECTED:")
        for a in all_alerts:
            print(f"   [{a['form']}] {a['deal']} — {a['description']}")


def cmd_filings(ticker: str) -> None:
    """View recent SEC filings for a ticker."""
    filings = fetch_sec_filings(ticker, limit=15)
    if not filings:
        print(f"❌ No filings found for {ticker}")
        return
    
    print(f"\n📄 SEC Filings — {ticker.upper()}\n")
    for f in filings:
        print(f"  [{f['form']:<8}] {f['date']}  {f['description'][:60]}")
    print(f"\n  Showing {len(filings)} filings — open full URLs in browser")


def cmd_price(ticker: str) -> None:
    """Get stock price."""
    price = fetch_stock_price(ticker)
    if "error" in price:
        print(f"❌ {price['error']}")
        return
    
    arrow = "▲" if price["change"] >= 0 else "▼"
    color = "\033[32m" if price["change"] >= 0 else "\033[31m"
    print(f"\n💰 {ticker.upper()} {color}${price['price']} {arrow} {price['change']:+.2f} ({price['change_pct']:+.1f}%)\033[0m")
    print(f"   Day: ${price['low']} — ${price['high']}  |  Vol: {price['volume']:,}  |  Prev close: ${price['prev_close']}")


def cmd_remove(name: str) -> None:
    """Stop tracking a deal."""
    state = load_state()
    did = deal_id(name)
    if did in state["deals"]:
        del state["deals"][did]
        save_state(state)
        print(f"🗑️  Stopped tracking: {name}")
    else:
        print(f"❌ Not tracking: {name}")


# ── Dashboard HTML ──────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M&A Radar</title>
<style>
  :root {
    --bg: #0a0e14;
    --card: #12161e;
    --border: #1e2430;
    --text: #c9d1d9;
    --muted: #6e7681;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --orange: #d2991d;
    --purple: #a371f7;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    line-height: 1.5;
    padding: 20px;
    min-height: 100vh;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    flex-wrap: wrap;
    gap: 12px;
  }
  h1 { font-size: 1.6rem; }
  h1 span { color: var(--orange); }
  .status-bar {
    display: flex;
    gap: 16px;
    font-size: 0.8rem;
    color: var(--muted);
  }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
  .status-dot.live { background: var(--green); }
  
  .layout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: auto auto;
    gap: 16px;
  }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
  
  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  .panel-title { font-weight: 600; font-size: 0.95rem; }
  .panel-badge {
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--border);
    color: var(--muted);
  }
  
  .deal-card {
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 8px;
    transition: border-color 0.2s;
  }
  .deal-card:hover { border-color: var(--accent); }
  .deal-name { font-weight: 600; margin-bottom: 4px; }
  .deal-tickers { font-size: 0.8rem; color: var(--accent); margin-bottom: 6px; }
  .deal-meta { font-size: 0.75rem; color: var(--muted); display: flex; gap: 12px; }
  
  .filing-row {
    display: grid;
    grid-template-columns: 60px 1fr 120px;
    gap: 8px;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
    align-items: center;
  }
  .filing-row:last-child { border: none; }
  .form-badge {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-align: center;
  }
  .form-8-K, .form-S-4, .form-13D, .form-SC { background: #f8514920; color: var(--red); }
  .form-10-K, .form-10-Q { background: #58a6ff20; color: var(--accent); }
  .form-4, .form-3 { background: #d2991d20; color: var(--orange); }
  .form-other { background: #a371f720; color: var(--purple); }
  
  .price-ticker {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.9rem;
  }
  .price-ticker:last-child { border: none; }
  .price-up { color: var(--green); }
  .price-down { color: var(--red); }
  
  .docket-row {
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
  }
  .docket-row:last-child { border: none; }
  .docket-court { font-size: 0.75rem; color: var(--muted); }
  
  .news-item {
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
  }
  .news-item:last-child { border: none; }
  .news-item a { color: var(--accent); text-decoration: none; }
  .news-item a:hover { text-decoration: underline; }
  .news-source { font-size: 0.75rem; color: var(--muted); }
  
  .alert-banner {
    background: #f8514920;
    border: 1px solid var(--red);
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 0.85rem;
  }
  .alert-banner .alert-count { color: var(--red); font-weight: 700; }
  
  .empty-state {
    text-align: center;
    padding: 40px 20px;
    color: var(--muted);
  }
  
  .full-width { grid-column: 1 / -1; }
</style>
</head>
<body>
  <header>
    <h1>📡 M&amp;A <span>Radar</span></h1>
    <div class="status-bar">
      <span><span class="status-dot live"></span> Live</span>
      <span id="clock">--</span>
    </div>
  </header>
  
  <div id="alerts"></div>
  
  <div class="layout">
    <div class="panel full-width">
      <div class="panel-header">
        <span class="panel-title">🎯 Tracked Deals</span>
        <span class="panel-badge" id="deal-count">0</span>
      </div>
      <div id="deals"></div>
    </div>
    
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">📄 SEC Filings</span>
        <span class="panel-badge" id="filing-count">0</span>
      </div>
      <div id="filings"></div>
    </div>
    
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">💰 Stock Prices</span>
      </div>
      <div id="prices"></div>
    </div>
    
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">⚖️ Court Dockets</span>
        <span class="panel-badge" id="docket-count">0</span>
      </div>
      <div id="dockets"></div>
    </div>
    
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">📰 News Feed</span>
        <span class="panel-badge" id="news-count">0</span>
      </div>
      <div id="news"></div>
    </div>
  </div>
  
  <script>
    let data = {deals:[], filings:[], prices:[], dockets:[], news:[], alerts:[]};
    
    async function refresh() {
      try {
        const resp = await fetch('/api/state');
        data = await resp.json();
        render();
      } catch(e) {
        console.error('Fetch failed:', e);
      }
      document.getElementById('clock').textContent = new Date().toLocaleTimeString();
    }
    
    function formClass(form) {
      if (!form) return 'form-other';
      if (/^(8-K|S-4|13D|SC)/.test(form)) return 'form-8-K, form-S-4, form-13D, form-SC'.split(', ').find(c => new RegExp(c.replace('form-','').replace(',','')).test(form)) || 'form-8-K';
      if (/^(10-K|10-Q)/.test(form)) return 'form-10-K';
      if (/^[34]$/.test(form)) return 'form-4';
      return 'form-other';
    }
    
    function render() {
      // Alerts
      const alertsDiv = document.getElementById('alerts');
      if (data.alerts && data.alerts.length) {
        alertsDiv.innerHTML = `<div class="alert-banner">🚨 <span class="alert-count">${data.alerts.length} material events</span> detected in the last 24h</div>`;
      } else {
        alertsDiv.innerHTML = '';
      }
      
      // Deals
      document.getElementById('deal-count').textContent = data.deals.length;
      document.getElementById('deals').innerHTML = data.deals.length
        ? data.deals.map(d => `
          <div class="deal-card">
            <div class="deal-name">${esc(d.name)}</div>
            <div class="deal-tickers">${(d.tickers||[]).join(', ') || 'no tickers'}</div>
            <div class="deal-meta">
              <span>Created: ${fmtDate(d.created)}</span>
              <span>Intel: ${d.last_intel ? fmtDate(d.last_intel) : 'never'}</span>
            </div>
          </div>`).join('')
        : '<div class="empty-state">No deals tracked. Use: ma-radar track "Name" --tickers AAPL,MSFT</div>';
      
      // Filings
      document.getElementById('filing-count').textContent = data.filings.length;
      document.getElementById('filings').innerHTML = data.filings.length
        ? data.filings.map(f => `
          <div class="filing-row">
            <span class="form-badge ${formClass(f.form)}">${f.form}</span>
            <span>${esc(f.description||f.ticker)} <a href="${f.url||'#'}" target="_blank" style="color:var(--accent);font-size:0.8rem">↗</a></span>
            <span style="color:var(--muted);text-align:right">${f.date}</span>
          </div>`).join('')
        : '<div class="empty-state">No filings loaded. Add tickers to deals.</div>';
      
      // Prices
      document.getElementById('prices').innerHTML = data.prices.length
        ? data.prices.map(p => {
            const cls = p.change >= 0 ? 'price-up' : 'price-down';
            const arrow = p.change >= 0 ? '▲' : '▼';
            return `<div class="price-ticker">
              <span><strong>${p.ticker}</strong> <span style="color:var(--muted);font-size:0.8rem">${p.currency||'USD'}</span></span>
              <span class="${cls}">$${p.price} ${arrow} ${p.change_pct > 0 ? '+' : ''}${p.change_pct}%</span>
            </div>`;
          }).join('')
        : '<div class="empty-state">No prices loaded</div>';
      
      // Dockets
      document.getElementById('docket-count').textContent = data.dockets.length;
      document.getElementById('dockets').innerHTML = data.dockets.length
        ? data.dockets.map(d => `
          <div class="docket-row">
            <div><a href="${d.url||'#'}" target="_blank" style="color:var(--accent)">${esc(d.title)}</a></div>
            <div class="docket-court">${d.court||''} • ${d.docket_number||''} • ${d.date||''}</div>
          </div>`).join('')
        : '<div class="empty-state">No court dockets found</div>';
      
      // News
      document.getElementById('news-count').textContent = data.news.length;
      document.getElementById('news').innerHTML = data.news.length
        ? data.news.map(n => `
          <div class="news-item">
            <div><a href="${n.url||'#'}" target="_blank">${esc(n.title)}</a></div>
            <div class="news-source">${n.source||''} • ${n.date||''}</div>
          </div>`).join('')
        : '<div class="empty-state">No news items</div>';
    }
    
    function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
    function fmtDate(d) {
      if (!d) return '';
      try { return new Date(d).toLocaleDateString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}); }
      catch { return d; }
    }
    
    refresh();
    setInterval(refresh, 60000); // 1 minute
  </script>
</body>
</html>"""


# ── HTTP Server ─────────────────────────────────────────

class RadarHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html(DASHBOARD_HTML)
        elif self.path == "/api/state":
            self._serve_state()
        elif self.path == "/api/refresh":
            self._refresh_all()
        elif self.path == "/health":
            self._serve_json({"status": "ok", "deals": len(load_state().get("deals", {}))})
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
    
    def _serve_html(self, content: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content.encode())
    
    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())
    
    def _serve_state(self):
        state = load_state()
        deals_list = list(state.get("deals", {}).values())
        
        # Collect filings, prices, dockets, news for all deals
        all_filings = []
        all_prices = []
        all_dockets = []
        all_news = []
        all_alerts = []
        
        for deal in deals_list:
            name = deal["name"]
            tickers = deal.get("tickers", [])
            
            for t in tickers:
                filings = fetch_sec_filings(t, limit=3)
                all_filings.extend(filings)
                
                price = fetch_stock_price(t)
                if "error" not in price:
                    all_prices.append(price)
            
            dockets = fetch_court_dockets(name, limit=3)
            all_dockets.extend(dockets)
            
            news = fetch_news(name, limit=3)
            all_news.extend(news)
        
        # Scan for material events
        material = scan_for_material_events(all_filings)
        all_alerts = [{"form": m["form"], "ticker": m["ticker"], "date": m["date"],
                        "description": m["description"]} for m in material]
        
        self._serve_json({
            "deals": deals_list,
            "filings": all_filings,
            "prices": all_prices,
            "dockets": all_dockets,
            "news": all_news,
            "alerts": all_alerts,
            "updated": datetime.now(timezone.utc).isoformat(),
        })
    
    def _refresh_all(self):
        """Force-refresh endpoint."""
        self._serve_json({"ok": True, "refreshed": datetime.now(timezone.utc).isoformat()})
    
    def log_message(self, format, *args):
        pass


def cmd_serve(port: int) -> None:
    server = HTTPServer(("127.0.0.1", port), RadarHandler)
    print(f"\n📡 M&A Radar running at http://127.0.0.1:{port}")
    print(f"   Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()


# ── Main ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="M&A Radar — Real-time merger intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              ma-radar                                     Start dashboard
              ma-radar track "Fox Roku" --tickers FOX,ROKU
              ma-radar list                                Show deals
              ma-radar check                               Intel sweep
              ma-radar filings TSLA                        SEC filings
              ma-radar price AAPL                          Stock price
              ma-radar remove "Fox Roku"                   Untrack
        """),
    )
    sub = parser.add_subparsers(dest="command", help="Command")
    
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Dashboard port (default: {DEFAULT_PORT})")
    
    track_p = sub.add_parser("track", help="Track a deal")
    track_p.add_argument("name", help="Deal name")
    track_p.add_argument("--tickers", help="Comma-separated tickers (FOX,ROKU)")
    
    sub.add_parser("list", help="List tracked deals")
    sub.add_parser("check", help="Intel sweep for all deals")
    
    filings_p = sub.add_parser("filings", help="View SEC filings")
    filings_p.add_argument("ticker", help="Stock ticker")
    
    price_p = sub.add_parser("price", help="Get stock price")
    price_p.add_argument("ticker", help="Stock ticker")
    
    remove_p = sub.add_parser("remove", help="Stop tracking")
    remove_p.add_argument("name", help="Deal name")
    
    args = parser.parse_args()
    
    if args.command == "track":
        cmd_track(args.name, getattr(args, 'tickers', None) or "")
    elif args.command == "list":
        cmd_list()
    elif args.command == "check":
        cmd_check()
    elif args.command == "filings":
        cmd_filings(args.ticker)
    elif args.command == "price":
        cmd_price(args.ticker)
    elif args.command == "remove":
        cmd_remove(args.name)
    else:
        cmd_serve(args.port)


if __name__ == "__main__":
    main()
