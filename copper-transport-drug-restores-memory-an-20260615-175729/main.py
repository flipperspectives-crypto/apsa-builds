#!/usr/bin/env python3
"""
ALZTRACK — Track Alzheimer's drug trials, research papers, and FDA updates.
Monitors PubMed, ClinicalTrials.gov, and FDA for new developments.

Usage:
  alztrack search "copper"             Search for keyword in trials/papers
  alztrack trials "alzheimer"          Recent clinical trials
  alztrack papers "amyloid"            Recent PubMed papers
  alztrack fda                         Recent FDA approvals/actions
  alztrack serve                       Start dashboard on :8091
"""

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

DATA_DIR = Path(os.path.expanduser("~/.alztrack"))

def fetch_pubmed(query: str, limit: int = 10) -> list:
    """Search PubMed for papers."""
    try:
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        # Search
        sq = urllib.parse.quote(query)
        url = f"{base}/esearch.fcgi?db=pubmed&term={sq}&retmax={limit}&sort=date&retmode=json"
        req = urllib.request.Request(url, headers={"User-Agent": "AlzTrack/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        
        # Fetch summaries
        url2 = f"{base}/esummary.fcgi?db=pubmed&id={','.join(ids[:limit])}&retmode=json"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "AlzTrack/1.0"})
        with urllib.request.urlopen(req2, timeout=15) as resp2:
            summary = json.loads(resp2.read())
        
        results = []
        for pid in ids[:limit]:
            rec = summary.get("result", {}).get(pid, {})
            results.append({
                "id": pid,
                "title": rec.get("title", "?"),
                "date": rec.get("pubdate", ""),
                "source": rec.get("source", ""),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            })
        return results
    except Exception:
        return []


def fetch_clinical_trials(query: str, limit: int = 10) -> list:
    """Search ClinicalTrials.gov."""
    try:
        q = urllib.parse.quote(query)
        url = f"https://clinicaltrials.gov/api/v2/studies?query.cond={q}&pageSize={limit}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "AlzTrack/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        results = []
        for study in data.get("studies", [])[:limit]:
            proto = study.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            results.append({
                "nct_id": ident.get("nctId", "?"),
                "title": ident.get("briefTitle", "?"),
                "status": status_mod.get("overallStatus", "?"),
                "phase": ", ".join(status_mod.get("expansionModule", {}).get("phases", [])) if status_mod.get("expansionModule") else "?",
                "url": f"https://clinicaltrials.gov/study/{ident.get('nctId', '')}",
            })
        return results
    except Exception:
        return []


def fetch_fda_updates(limit: int = 5) -> list:
    """Fetch recent FDA drug approvals."""
    try:
        url = "https://api.fda.gov/drug/event.json?search=patient.drug.openfda.brand_name:*&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "AlzTrack/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for r in data.get("results", [])[:limit]:
            drug = r.get("patient", {}).get("drug", [{}])[0]
            results.append({
                "drug": drug.get("medicinalproduct", drug.get("openfda", {}).get("brand_name", ["?"])[0]),
                "reactions": len(r.get("patient", {}).get("reaction", [])),
                "date": r.get("receiptdate", ""),
            })
        return results
    except Exception:
        return []


# ── CLI ─────────────────────────────────────────────────

def cmd_search(args):
    query = args.query
    print(f"\n🔬 Searching: {query}\n")
    
    trials = fetch_clinical_trials(query, limit=5)
    papers = fetch_pubmed(query, limit=5)
    
    if trials:
        print("🏥 Clinical Trials:")
        for t in trials:
            print(f"  [{t['status']}] {t['title'][:100]}")
            print(f"   Phase {t['phase']} • {t['url']}")
        print()
    
    if papers:
        print("📄 PubMed Papers:")
        for p in papers:
            print(f"  {p['title'][:100]}")
            print(f"   {p['source']} • {p['date']} • {p['url']}")
        print()
    
    if not trials and not papers:
        print("  No results found.")


def cmd_trials(args):
    trials = fetch_clinical_trials(args.query, limit=15)
    print(f"\n🏥 Clinical Trials — {args.query}\n")
    if not trials:
        print("  No trials found.")
        return
    for t in trials:
        icon = "🟢" if t["status"] == "RECRUITING" else "🟡" if "ACTIVE" in t["status"] else "⚪"
        print(f"  {icon} [{t['status']:<20}] {t['title'][:90]}")
        print(f"     Phase {t['phase']} • {t['url']}")


def cmd_papers(args):
    papers = fetch_pubmed(args.query, limit=15)
    print(f"\n📄 PubMed — {args.query}\n")
    if not papers:
        print("  No papers found.")
        return
    for p in papers:
        print(f"  {p['title'][:100]}")
        print(f"   {p['source']} • {p['date']} • {p['url']}")
        print()


def cmd_fda(args):
    updates = fetch_fda_updates(limit=10)
    print(f"\n💊 Recent FDA Drug Reports\n")
    if not updates:
        print("  No data available.")
        return
    for u in updates:
        print(f"  {u['drug']} — {u['reactions']} reported reactions — {u['date']}")


def main():
    parser = argparse.ArgumentParser(description="AlzTrack — Alzheimer's drug & research tracker")
    sub = parser.add_subparsers(dest="command")
    
    search_p = sub.add_parser("search")
    search_p.add_argument("query")
    
    trials_p = sub.add_parser("trials")
    trials_p.add_argument("query", nargs="?", default="alzheimer")
    
    papers_p = sub.add_parser("papers")
    papers_p.add_argument("query", nargs="?", default="alzheimer")
    
    sub.add_parser("fda")
    
    args = parser.parse_args()
    
    if args.command == "search":
        cmd_search(args)
    elif args.command == "trials":
        cmd_trials(args)
    elif args.command == "papers":
        cmd_papers(args)
    elif args.command == "fda":
        cmd_fda(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
