#!/usr/bin/env python3
"""U.S. government will decide who gets to use latest upgrade to ChatGPT — Automation Bot
Source: [HN] https://www.washingtonpost.com/technology/2026/06/26/openai-says-us-government-will-vet-users-its-latest-ai-model/
"""

import argparse, json, os, sys, time, requests

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        return json.load(open(CONFIG_FILE))
    return {"webhook_url": "", "interval": 60, "target": "https://www.washingtonpost.com/technology/2026/06/26/openai-says-us-government-will-vet-users-its-latest-ai-model/"}

def save_config(cfg):
    json.dump(cfg, open(CONFIG_FILE, "w"), indent=2)

def send_webhook(url: str, msg: str):
    """Send message to webhook (Discord/Slack compatible)."""
    if not url:
        return False
    try:
        requests.post(url, json={"content": msg}, timeout=5)
        return True
    except:
        return False

def check(url: str) -> dict | None:
    """Check target URL for changes. Override for custom logic."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "APSA-Bot/1.0"})
        return {"status": resp.status_code, "size": len(resp.content), "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}

def main():
    parser = argparse.ArgumentParser(description="U.S. government will decide who gets to use latest upgrade to ChatGPT")
    parser.add_argument("--webhook", help="Discord/Slack webhook URL")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval (seconds)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()
    
    cfg = load_config()
    if args.webhook:
        cfg["webhook_url"] = args.webhook
        save_config(cfg)
    if args.interval != 60:
        cfg["interval"] = args.interval
    
    print(f"🤖 {cfg.get('target','?')}")
    print(f"   interval: {cfg['interval']}s | webhook: {'configured' if cfg.get('webhook_url') else 'none'}")
    
    while True:
        result = check(cfg["target"])
        status = "✓" if result and "error" not in result else "✗"
        msg = f"[{status}] {result}"
        print(msg)
        
        if cfg.get("webhook_url") and "error" in (result or {}):
            send_webhook(cfg["webhook_url"], f"⚠️ Alert: {result}")
        
        if args.once:
            break
        time.sleep(cfg["interval"])

if __name__ == "__main__":
    main()
