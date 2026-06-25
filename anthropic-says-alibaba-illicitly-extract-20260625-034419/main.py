#!/usr/bin/env python3
"""Anthropic says Alibaba illicitly extracted Claude AI model capabilities — Web Scraper
Source: [HN] https://www.reuters.com/world/china/anthropic-says-alibaba-illicitly-extracted-claude-ai-model-capabilities-2026-06-24/
"""

import argparse, json, sys, time
import requests
from bs4 import BeautifulSoup

def scrape(url: str, selector: str = "a") -> list:
    """Scrape a URL and extract elements matching CSS selector."""
    print(f"🔍 Scraping {url}...")
    headers = {"User-Agent": "APSA-Net/1.0"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    elements = soup.select(selector)
    
    results = []
    for el in elements:
        item = {"text": el.get_text(strip=True)[:200]}
        if el.name == "a":
            item["href"] = el.get("href", "")
        if el.get("src"):
            item["src"] = el["src"]
        results.append(item)
    
    return results

def main():
    parser = argparse.ArgumentParser(description="Anthropic says Alibaba illicitly extracted Claude AI model capabilities")
    parser.add_argument("url", nargs="?", default="https://www.reuters.com/world/china/anthropic-says-alibaba-illicitly-extracted-claude-ai-model-capabilities-2026-06-24/", help="URL to scrape")
    parser.add_argument("-s", "--selector", default="a", help="CSS selector (default: a)")
    parser.add_argument("-o", "--output", default="output/data.json", help="Output file")
    parser.add_argument("--limit", type=int, default=100, help="Max results")
    args = parser.parse_args()
    
    results = scrape(args.url, args.selector)[:args.limit]
    
    import os; os.makedirs("output", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"✅ {len(results)} items saved to {args.output}")

if __name__ == "__main__":
    main()
