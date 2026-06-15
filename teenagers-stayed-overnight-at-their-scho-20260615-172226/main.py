#!/usr/bin/env python3
"""
ARCHAEOLOGY DASHBOARD — Track archaeological discoveries from news sources.
Runs a local web server showing recent finds, interactive timeline, and map.

Usage:
  python main.py                    Start dashboard on :8090
  python main.py --port 8080        Custom port
  python main.py --update           Fetch latest discoveries (CLI mode)
"""

import argparse
import json
import os
import sys
import time
import hashlib
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# ── Config ──────────────────────────────────────────────
DATA_DIR = Path(os.path.expanduser("~/.archaeology"))
DISCOVERIES_FILE = DATA_DIR / "discoveries.json"
DEFAULT_PORT = 8090

ARCHAEOLOGY_KEYWORDS = [
    "archaeological discovery", "ancient ruins found", "roman villa discovered",
    "buried city found", "tomb discovered", "pyramid found", "ancient artifacts",
    "fossil discovery", "shipwreck found", "treasure discovered",
    "prehistoric site", "neolithic discovery", "bronze age found",
    "excavation reveals", "archaeologists unearth", "lost city found",
    "underground chamber", "hidden ruins", "ancient temple discovered",
    "medieval find", "viking discovery", "dinosaur fossil",
]


def load_discoveries() -> list:
    if DISCOVERIES_FILE.exists():
        return json.loads(DISCOVERIES_FILE.read_text())
    return []


def save_discoveries(items: list) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DISCOVERIES_FILE.write_text(json.dumps(items, indent=2, default=str))


def fetch_discoveries() -> list:
    """Scrape news for archaeological discoveries."""
    all_items = []
    seen_ids = {d["id"] for d in load_discoveries()}
    
    for kw in ARCHAEOLOGY_KEYWORDS[:10]:  # Top 10 keywords to stay fast
        try:
            query = urllib.parse.quote(kw)
            url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
            req = urllib.request.Request(url, headers={"User-Agent": "ArchaeoBoard/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
            
            for item in root.iter("item"):
                title = (item.find("title").text or "") if item.find("title") is not None else ""
                link = (item.find("link").text or "") if item.find("link") is not None else ""
                pubdate = (item.find("pubDate").text or "") if item.find("pubDate") is not None else ""
                source = (item.find("source").text or "Unknown") if item.find("source") is not None else "Unknown"
                
                item_id = hashlib.md5(f"{title}:{link}".encode()).hexdigest()[:12]
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                
                # Detect era from title
                era = detect_era(title)
                
                all_items.append({
                    "id": item_id,
                    "title": clean_title(title),
                    "url": link,
                    "date": pubdate,
                    "source": source,
                    "era": era,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            continue
    
    # Merge with existing
    existing = load_discoveries()
    existing.extend(all_items)
    # Keep last 200
    existing = existing[-200:]
    save_discoveries(existing)
    
    return all_items


def clean_title(title: str) -> str:
    """Remove ' - SourceName' suffix from Google News titles."""
    if " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts[1]) < 30:
            return parts[0]
    return title


def detect_era(title: str) -> str:
    """Guess historical era from title keywords."""
    t = title.lower()
    eras = [
        ("Roman", ["roman", "rome", "caesar", "pompeii", "gladiator"]),
        ("Greek", ["greek", "athens", "sparta", "alexander", "hellenistic"]),
        ("Egyptian", ["egypt", "pyramid", "pharaoh", "mummy", "nile"]),
        ("Viking", ["viking", "norse", "scandinavian"]),
        ("Medieval", ["medieval", "castle", "knight", "feudal"]),
        ("Prehistoric", ["prehistoric", "neolithic", "stone age", "bronze age", "ice age"]),
        ("Mesoamerican", ["maya", "aztec", "inca", "olmec", "mesoamerica"]),
        ("Chinese", ["chinese", "dynasty", "han", "tang", "ming"]),
        ("Mesopotamian", ["mesopotamia", "babylon", "sumerian", "assyrian"]),
        ("Dinosaur", ["dinosaur", "jurassic", "cretaceous", "fossil", "t-rex"]),
    ]
    for era, keywords in eras:
        if any(k in t for k in keywords):
            return era
    return "Unknown"


# ── Dashboard HTML ──────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ArchaeoBoard — Discoveries Dashboard</title>
<style>
  :root {
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --orange: #d2991d;
    --red: #f85149;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    line-height: 1.5;
    padding: 20px;
  }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  h1 span { color: var(--orange); }
  .subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 20px; }
  
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }
  .stat-value { font-size: 2rem; font-weight: 700; color: var(--accent); }
  .stat-label { font-size: 0.8rem; color: var(--muted); margin-top: 4px; }
  
  .era-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 8px;
    margin-bottom: 24px;
  }
  .era-chip {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s;
  }
  .era-chip:hover { border-color: var(--accent); }
  .era-chip.active { border-color: var(--accent); background: #1a2332; }
  .era-name { font-weight: 600; font-size: 0.9rem; }
  .era-count { color: var(--muted); font-size: 0.75rem; }
  
  .discovery-list {
    display: grid;
    gap: 8px;
  }
  .discovery {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 12px;
    align-items: start;
    transition: border-color 0.2s;
  }
  .discovery:hover { border-color: var(--accent); }
  .era-badge {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
    text-transform: uppercase;
  }
  .era-Roman { background: #8b000020; color: #ff6b6b; }
  .era-Greek { background: #00008b20; color: #6bb5ff; }
  .era-Egyptian { background: #8b8b0020; color: #ffd700; }
  .era-Viking { background: #008b0020; color: #6bff6b; }
  .era-Medieval { background: #8b008b20; color: #ff6bff; }
  .era-Prehistoric { background: #8b450020; color: #ff8c42; }
  .era-Mesoamerican { background: #008b8b20; color: #6bffff; }
  .era-Chinese { background: #8b000020; color: #ff4444; }
  .era-Mesopotamian { background: #4b008b20; color: #b46bff; }
  .era-Dinosaur { background: #2e8b0020; color: #8bff6b; }
  .era-Unknown { background: #44444420; color: #aaaaaa; }
  
  .discovery-title {
    font-weight: 500;
    margin-bottom: 4px;
  }
  .discovery-title a {
    color: var(--accent);
    text-decoration: none;
  }
  .discovery-title a:hover { text-decoration: underline; }
  .discovery-meta {
    font-size: 0.8rem;
    color: var(--muted);
  }
  .discovery-date {
    font-size: 0.75rem;
    color: var(--muted);
    white-space: nowrap;
    text-align: right;
  }
  
  .empty { 
    text-align: center; 
    color: var(--muted); 
    padding: 60px 20px;
  }
  .empty-icon { font-size: 3rem; margin-bottom: 12px; }
  
  @media (max-width: 600px) {
    .discovery { grid-template-columns: 1fr; }
    .discovery-date { text-align: left; }
  }
</style>
</head>
<body>
  <h1>🏛️ Archaeo<span>Board</span></h1>
  <p class="subtitle" id="subtitle">Loading discoveries...</p>
  
  <div class="stats" id="stats"></div>
  <div class="era-grid" id="eras"></div>
  <div class="discovery-list" id="discoveries"></div>
  
  <script>
    const ERA_COLORS = {
      'Roman': '#ff6b6b', 'Greek': '#6bb5ff', 'Egyptian': '#ffd700',
      'Viking': '#6bff6b', 'Medieval': '#ff6bff', 'Prehistoric': '#ff8c42',
      'Mesoamerican': '#6bffff', 'Chinese': '#ff4444', 'Mesopotamian': '#b46bff',
      'Dinosaur': '#8bff6b', 'Unknown': '#aaaaaa'
    };
    
    let allDiscoveries = [];
    let activeEra = null;
    
    async function load() {
      try {
        const resp = await fetch('/api/discoveries');
        allDiscoveries = await resp.json();
        render();
      } catch(e) {
        document.getElementById('subtitle').textContent = '⚠️ Failed to load';
      }
    }
    
    function render() {
      document.getElementById('subtitle').textContent = 
        `${allDiscoveries.length} discoveries tracked • Auto-refreshes`;
      
      // Stats
      const eras = {};
      const sources = {};
      allDiscoveries.forEach(d => {
        eras[d.era] = (eras[d.era] || 0) + 1;
        sources[d.source] = (sources[d.source] || 0) + 1;
      });
      
      document.getElementById('stats').innerHTML = `
        <div class="stat-card">
          <div class="stat-value">${allDiscoveries.length}</div>
          <div class="stat-label">Total Discoveries</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${Object.keys(eras).length}</div>
          <div class="stat-label">Historical Eras</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${Object.keys(sources).length}</div>
          <div class="stat-label">News Sources</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${allDiscoveries.filter(d => d.era !== 'Unknown').length}</div>
          <div class="stat-label">Classified</div>
        </div>
      `;
      
      // Era filters
      const sortedEras = Object.entries(eras).sort((a,b) => b[1] - a[1]);
      document.getElementById('eras').innerHTML = sortedEras.map(([era, count]) => `
        <div class="era-chip ${activeEra === era ? 'active' : ''}" onclick="filterEra('${era}')">
          <div class="era-name" style="color:${ERA_COLORS[era] || '#aaa'}">${era}</div>
          <div class="era-count">${count} finds</div>
        </div>
      `).join('');
      
      // Discovery list
      let filtered = activeEra ? allDiscoveries.filter(d => d.era === activeEra) : allDiscoveries;
      
      if (!filtered.length) {
        document.getElementById('discoveries').innerHTML = `
          <div class="empty">
            <div class="empty-icon">🔍</div>
            <div>No discoveries yet. Run with --update to fetch.</div>
          </div>`;
        return;
      }
      
      document.getElementById('discoveries').innerHTML = filtered.map(d => `
        <div class="discovery">
          <span class="era-badge era-${d.era}">${d.era}</span>
          <div>
            <div class="discovery-title">
              <a href="${d.url || '#'}" target="_blank" rel="noopener">${d.title}</a>
            </div>
            <div class="discovery-meta">${d.source}</div>
          </div>
          <div class="discovery-date">${formatDate(d.date)}</div>
        </div>
      `).join('');
    }
    
    function filterEra(era) {
      activeEra = activeEra === era ? null : era;
      render();
    }
    
    function formatDate(d) {
      if (!d) return '';
      try { return new Date(d).toLocaleDateString('en-US', {month:'short', day:'numeric'}); }
      catch { return d; }
    }
    
    load();
    setInterval(load, 300000); // Refresh every 5 min
  </script>
</body>
</html>"""


# ── HTTP Server ─────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html(DASHBOARD_HTML, "text/html")
        elif self.path == "/api/discoveries":
            discoveries = load_discoveries()
            self._serve_json(discoveries)
        elif self.path == "/api/refresh":
            new_items = fetch_discoveries()
            self._serve_json({"ok": True, "new": len(new_items), "items": new_items})
        elif self.path == "/health":
            self._serve_json({"status": "ok", "discoveries": len(load_discoveries())})
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
    
    def _serve_html(self, content: str, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
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
    
    def log_message(self, format, *args):
        pass  # Quiet


def cmd_serve(port: int) -> None:
    """Start the dashboard server."""
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"\n🏛️  ArchaeoBoard running at http://127.0.0.1:{port}")
    print(f"   Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()


def cmd_update() -> None:
    """Fetch latest discoveries (CLI)."""
    print("🔍 Fetching archaeological discoveries...")
    new_items = fetch_discoveries()
    existing = load_discoveries()
    
    if not existing:
        print("📭 No discoveries found. Try again later.")
        return
    
    print(f"\n📊 {len(existing)} total discoveries")
    print(f"   {len(new_items)} new this fetch\n")
    
    # Show recent
    for d in existing[-10:]:
        era_tag = f"[{d['era']}]" if d['era'] != 'Unknown' else ""
        print(f"  {era_tag} {d['title'][:100]}")
        print(f"     {d['source']} • {d['url'][:80]}")
    
    print(f"\n   Start dashboard: python main.py")


def main():
    parser = argparse.ArgumentParser(
        description="ArchaeoBoard — Archaeological discoveries dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python main.py                 Start dashboard
              python main.py --port 8080     Custom port
              python main.py --update        Fetch discoveries (CLI)
        """),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    parser.add_argument("--update", action="store_true", help="Fetch discoveries and exit")
    args = parser.parse_args()
    
    if args.update:
        cmd_update()
    else:
        cmd_serve(args.port)


if __name__ == "__main__":
    main()
