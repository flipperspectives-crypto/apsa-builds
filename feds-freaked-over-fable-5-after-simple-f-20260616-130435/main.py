#!/usr/bin/env python3
"""
PROMPTSHIELD — AI prompt safety auditor. Detects jailbreak attempts,
injection attacks, and risky prompt patterns before they hit your model.

Usage:
  promptshield check "your prompt here"    Scan a single prompt
  promptshield audit file.txt              Audit all prompts in a file
  promptshield monitor --watch log.json    Monitor live prompt logs
  promptshield rules                       List detection rules
"""

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

DATA_DIR = Path(os.path.expanduser("~/.promptshield"))

# ── Detection Rules ─────────────────────────────────────

INJECTION_PATTERNS = [
    (r"ignore (all )?(previous|prior|above) instruct(ions?)?", "HIGH", "Instruction override"),
    (r"forget (everything|all) (you|we) (said|discussed|talked)", "HIGH", "Context wipe attempt"),
    (r"you are now (DAN|STAN|jailbroken|unrestricted|free)", "CRITICAL", "Jailbreak persona"),
    (r"system:\s*override", "CRITICAL", "System prompt injection"),
    (r"<\|im_start\|>", "HIGH", "ChatML injection"),
    (r"\[INST\].*\[/INST\]", "HIGH", "LLaMA instruction injection"),
    (r"\{.*system.*:.*\}", "MEDIUM", "JSON system injection"),
    (r"new instructions?:.*you must", "HIGH", "Instruction injection"),
    (r"output format:.*do not (include|say|mention)", "MEDIUM", "Output suppression"),
    (r"respond (only|exclusively) with", "LOW", "Output constraint"),
    (r"base64 decode", "MEDIUM", "Encoded payload"),
    (r"python.*exec\(|eval\(|__import__|subprocess", "HIGH", "Code execution attempt"),
    (r"curl.*http|wget.*http|fetch.*http", "MEDIUM", "External request"),
    (r"sudo|rm -rf|chmod 777|/etc/passwd|/etc/shadow", "CRITICAL", "System command injection"),
    (r"prompt leak|prompt injection|prompt extraction", "HIGH", "Prompt extraction"),
    (r"repeat (after me|the following|this exactly)", "MEDIUM", "Echo attack"),
    (r"translate.*to.*and.*back", "LOW", "Translation bypass"),
    (r"as a (security )?researcher", "MEDIUM", "Social engineering"),
    (r"hypothetically|imagine.*if|what if.*you could", "MEDIUM", "Hypothetical bypass"),
    (r"write.*harmful|write.*dangerous|how to.*hack|how to.*exploit", "HIGH", "Harmful content"),
    (r"\\\\n\\\\n\s*system", "HIGH", "Newline injection"),
    (r"BEGIN.*ROLE.*END", "HIGH", "Role-play injection"),
    (r"from now on|starting now|your new (role|identity|name) is", "HIGH", "Identity override"),
    (r"do not (refuse|reject|deny|decline)", "MEDIUM", "Refusal bypass"),
]

CONTENT_RISKS = [
    (r"(bomb|explosive|weapon).*(how|make|build|create)", "CRITICAL", "Weapons"),
    (r"(hack|exploit|crack).*(password|login|account|system)", "HIGH", "Unauthorized access"),
    (r"(social security|credit card|ssn|dob).*(generate|create|fake)", "HIGH", "PII generation"),
    (r"(child|minor|underage).*(sexual|explicit|nude)", "CRITICAL", "CSAM"),
    (r"(suicide|self-harm|kill myself).*(how|method|way)", "CRITICAL", "Self-harm"),
]

def scan_prompt(text: str) -> dict:
    """Scan a prompt for risks and return findings."""
    results = {"text": text[:200], "length": len(text), "risks": [], "score": 0}
    
    for pattern, severity, category in INJECTION_PATTERNS + CONTENT_RISKS:
        if re.search(pattern, text, re.IGNORECASE):
            sev_score = {"LOW": 1, "MEDIUM": 3, "HIGH": 5, "CRITICAL": 10}[severity]
            results["risks"].append({
                "pattern": pattern[:60],
                "severity": severity,
                "category": category,
                "score": sev_score,
            })
            results["score"] += sev_score
    
    # Overall risk level
    if results["score"] >= 10:
        results["level"] = "CRITICAL"
    elif results["score"] >= 5:
        results["level"] = "HIGH"
    elif results["score"] >= 2:
        results["level"] = "MEDIUM"
    else:
        results["level"] = "LOW"
    
    return results


# ── CLI ─────────────────────────────────────────────────

def cmd_check(args):
    result = scan_prompt(args.prompt)
    
    levels = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
    icon = levels.get(result["level"], "⚪")
    
    print(f"\n{icon} RISK: {result['level']} (score: {result['score']})")
    print(f"   Length: {result['length']} chars")
    
    if result["risks"]:
        print(f"\n   Findings ({len(result['risks'])}):")
        for r in result["risks"]:
            sev_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}[r["severity"]]
            print(f"   {sev_icon} [{r['severity']:<8}] {r['category']}")
    else:
        print(f"\n   ✅ No risks detected")
    
    if args.json:
        print(f"\n{json.dumps(result, indent=2)}")


def cmd_audit(args):
    path = Path(args.file)
    if not path.exists():
        print(f"❌ File not found: {args.file}")
        sys.exit(1)
    
    content = path.read_text()
    # Split by common delimiters to extract individual prompts
    prompts = re.split(r'\n---\n|\n={3,}\n|^#+\s', content, flags=re.MULTILINE)
    prompts = [p.strip() for p in prompts if len(p.strip()) > 10]
    
    print(f"\n📋 Auditing {len(prompts)} prompts from {args.file}\n")
    
    total_score = 0
    flagged = 0
    for i, prompt in enumerate(prompts):
        result = scan_prompt(prompt)
        total_score += result["score"]
        if result["score"] > 0:
            flagged += 1
            icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}[result["level"]]
            print(f"  [{i+1}] {icon} {result['level']:<8} score={result['score']:<3} {prompt[:80]}...")
    
    print(f"\n  Total: {flagged}/{len(prompts)} flagged, avg score: {total_score/max(len(prompts),1):.1f}")


def cmd_rules(args):
    print(f"\n📋 Detection Rules ({len(INJECTION_PATTERNS) + len(CONTENT_RISKS)}):\n")
    
    print("INJECTION ATTACKS:")
    for pat, sev, cat in INJECTION_PATTERNS:
        icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}[sev]
        print(f"  {icon} [{sev:<8}] {cat:<30} {pat[:50]}")
    
    print(f"\nCONTENT RISKS:")
    for pat, sev, cat in CONTENT_RISKS:
        icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}[sev]
        print(f"  {icon} [{sev:<8}] {cat:<30} {pat[:50]}")


def main():
    parser = argparse.ArgumentParser(description="PromptShield — AI prompt safety auditor")
    sub = parser.add_subparsers(dest="command")
    
    check_p = sub.add_parser("check", help="Scan a single prompt")
    check_p.add_argument("prompt", help="Prompt text to scan")
    check_p.add_argument("--json", action="store_true", help="Output as JSON")
    
    audit_p = sub.add_parser("audit", help="Audit prompts in a file")
    audit_p.add_argument("file", help="File containing prompts")
    
    sub.add_parser("rules", help="List detection rules")
    
    args = parser.parse_args()
    
    if args.command == "check":
        cmd_check(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "rules":
        cmd_rules(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
