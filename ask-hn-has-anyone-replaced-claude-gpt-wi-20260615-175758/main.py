#!/usr/bin/env python3
"""
LOCALBENCH — Benchmark local LLMs against cloud models for coding tasks.
Tests latency, correctness, and cost across models.

Usage:
  localbench test                    Run coding benchmark suite
  localbench models                  List supported models
  localbench compare "prompt"        Compare local vs cloud on a prompt
  localbench serve                   Start benchmark dashboard on :8092
"""

import argparse
import json
import os
import sys
import textwrap
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error

DATA_DIR = Path(os.path.expanduser("~/.localbench"))
RESULTS_FILE = DATA_DIR / "results.json"

# ── Benchmark Suite ─────────────────────────────────────

CODING_TESTS = [
    {"name": "fizzbuzz", "prompt": "Write a Python function fizzbuzz(n) that prints numbers 1 to n, but prints 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, and 'FizzBuzz' for multiples of both. Return the function only, no explanation.", "check": lambda out: "fizzbuzz" in out.lower() and "def" in out and "return" in out},
    {"name": "binary_search", "prompt": "Write a Python function binary_search(arr, target) that returns the index of target in a sorted array, or -1 if not found. Use iterative binary search. Return code only.", "check": lambda out: "binary_search" in out.lower() and "mid" in out.lower()},
    {"name": "fibonacci", "prompt": "Write a Python function fib(n) that returns the nth Fibonacci number using memoization. Return code only.", "check": lambda out: "fib" in out.lower() and ("memo" in out.lower() or "cache" in out.lower())},
    {"name": "flatten", "prompt": "Write a Python function flatten(lst) that recursively flattens a nested list of arbitrary depth. Return code only.", "check": lambda out: "flatten" in out.lower() and "recurs" in out.lower() and "isinstance" in out.lower()},
    {"name": "rate_limiter", "prompt": "Write a Python class RateLimiter that limits calls to max_calls per window_seconds using a sliding window. Return code only.", "check": lambda out: "ratelimiter" in out.lower().replace("_","") and "time" in out.lower()},
]

MODELS = {
    "local": {"name": "Local LLM (llama.cpp)", "endpoint": "http://127.0.0.1:8081/v1/chat/completions", "cost_per_1k": 0},
    "openrouter": {"name": "OpenRouter (free models)", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "cost_per_1k": 0},
}


def call_llm(model_key: str, prompt: str, timeout: int = 60) -> dict:
    """Call an LLM API and return timing + response."""
    if model_key not in MODELS:
        return {"error": f"Unknown model: {model_key}"}
    
    cfg = MODELS[model_key]
    body = {
        "model": "gpt-3.5-turbo" if model_key != "local" else "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.1,
    }
    
    extra_headers = {}
    if model_key == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if key:
            extra_headers["Authorization"] = f"Bearer {key}"
            body["model"] = "openrouter/auto"
    
    try:
        start = time.monotonic()
        req = urllib.request.Request(
            cfg["endpoint"],
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "LocalBench/1.0",
                **extra_headers,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        elapsed = time.monotonic() - start
        
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("completion_tokens", len(content) // 4)
        
        return {
            "ok": True,
            "response": content,
            "latency_ms": round(elapsed * 1000),
            "tokens": tokens,
            "model": data.get("model", model_key),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def cmd_test(args) -> None:
    """Run benchmark suite."""
    model = args.model
    if model not in MODELS:
        print(f"❌ Unknown model: {model}. Use: local -> OpenRouter")
        sys.exit(1)
    
    print(f"\n🧪 LocalBench — {MODELS[model]['name']}")
    print(f"   {len(CODING_TESTS)} coding tests\n")
    
    results = {"model": model, "timestamp": datetime.now(timezone.utc).isoformat(), "tests": []}
    passed = 0
    total_latency = 0
    
    for i, test in enumerate(CODING_TESTS):
        print(f"  [{i+1}/{len(CODING_TESTS)}] {test['name']}...", end=" ", flush=True)
        result = call_llm(model, test["prompt"])
        
        if not result.get("ok"):
            print(f"❌ {result.get('error', 'unknown')[:60]}")
            results["tests"].append({"name": test["name"], "passed": False, "error": result.get("error", "")})
            continue
        
        passed_check = test["check"](result["response"])
        total_latency += result["latency_ms"]
        
        icon = "✅" if passed_check else "❌"
        print(f"{icon} {result['latency_ms']}ms {result['tokens']}t")
        results["tests"].append({
            "name": test["name"],
            "passed": passed_check,
            "latency_ms": result["latency_ms"],
            "tokens": result["tokens"],
        })
        if passed_check:
            passed += 1
    
    avg_latency = total_latency / len(CODING_TESTS) if CODING_TESTS else 0
    
    print(f"\n{'='*50}")
    print(f"  Results: {passed}/{len(CODING_TESTS)} passed")
    print(f"  Avg latency: {avg_latency:.0f}ms")
    print(f"  Cost: ${MODELS[model]['cost_per_1k'] * sum(t.get('tokens',0) for t in results['tests']) / 1000:.4f}")
    
    # Save results
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []
    if RESULTS_FILE.exists():
        all_results = json.loads(RESULTS_FILE.read_text())
    all_results.append(results)
    # Keep last 50 runs
    RESULTS_FILE.write_text(json.dumps(all_results[-50:], indent=2))


def cmd_compare(args) -> None:
    """Compare local vs cloud on a single prompt."""
    prompt = args.prompt
    
    print(f"\n⚡ Comparing: Local vs Cloud\n")
    
    for model_key in ["local", "openrouter"]:
        print(f"─── {MODELS[model_key]['name']} ───")
        result = call_llm(model_key, prompt)
        if result.get("ok"):
            print(f"  {result['latency_ms']}ms | {result['tokens']} tokens")
            print(f"  {result['response'][:300]}")
            if len(result['response']) > 300:
                print(f"  ... ({len(result['response'])} chars total)")
        else:
            print(f"  ❌ {result.get('error', 'offline')}")
        print()


def cmd_models(args) -> None:
    """List available models."""
    print("\n📋 Available Models:\n")
    for key, cfg in MODELS.items():
        status = "🟢" if key == "local" else "🌐"
        cost = "FREE" if cfg["cost_per_1k"] == 0 else f"${cfg['cost_per_1k']}/1k tok"
        print(f"  {status} {cfg['name']:<40} {cost}")
    
    print(f"\n  History: {len(json.loads(RESULTS_FILE.read_text()) if RESULTS_FILE.exists() else '[]')} runs saved")
    
    # Show recent results
    if RESULTS_FILE.exists():
        all_results = json.loads(RESULTS_FILE.read_text())
        if all_results:
            last = all_results[-1]
            print(f"\n  Last run: {last['timestamp'][:19]}")
            print(f"  Model: {last['model']}")
            passed = sum(1 for t in last["tests"] if t.get("passed"))
            print(f"  Score: {passed}/{len(last['tests'])}")


def main():
    parser = argparse.ArgumentParser(description="LocalBench — LLM coding benchmark")
    sub = parser.add_subparsers(dest="command")
    
    test_p = sub.add_parser("test")
    test_p.add_argument("--model", default="openrouter", choices=["local", "openrouter"])
    
    comp_p = sub.add_parser("compare")
    comp_p.add_argument("prompt")
    
    sub.add_parser("models")
    
    args = parser.parse_args()
    
    if args.command == "test":
        cmd_test(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "models":
        cmd_models(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
