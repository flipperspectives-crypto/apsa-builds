#!/usr/bin/env python3
"""
FUSION CLI — OpenRouter's free multi-model deliberation.
Fusion turns your prompt into a small multi-model deliberation.
$0/million tokens, 1M context window.

Usage:
  fusion "your prompt"              Single query
  fusion chat                       Interactive chat
  fusion models                     List available models
  fusion compare "prompt"           Compare Fusion vs single model
"""

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime
from typing import Optional

# Pure stdlib — no pip deps needed
import urllib.request
import urllib.error

# ── Config ──────────────────────────────────────────────
API_BASE = "https://openrouter.ai/api/v1"
FUSION_MODEL = "openrouter/fusion"
CONFIG_PATH = os.path.expanduser("~/.config/fusion/config.json")
DEFAULT_MODEL = "openrouter/auto"


def load_api_key() -> Optional[str]:
    """Load API key from env or config file."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        if os.path.exists(CONFIG_PATH):
            cfg = json.loads(open(CONFIG_PATH).read())
            return cfg.get("api_key")
    except Exception:
        pass
    return None


def save_api_key(key: str) -> None:
    """Save API key to config."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.loads(open(CONFIG_PATH).read())
        except Exception:
            pass
    cfg["api_key"] = key
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    print(f"🔑 API key saved to {CONFIG_PATH}")


def api_call(
    messages: list,
    model: str = FUSION_MODEL,
    api_key: Optional[str] = None,
    stream: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    """Make a chat completion call to OpenRouter."""
    key = api_key or load_api_key()
    if not key:
        raise ValueError(
            "No API key. Set OPENROUTER_API_KEY env var or run: fusion auth <key>"
        )

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/flipperspectives/fusion-cli",
            "X-Title": "Fusion CLI",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        raise RuntimeError(f"API error {e.code}: {err_body}")


def cmd_query(prompt: str, args) -> None:
    """Single-shot query."""
    messages = [{"role": "user", "content": prompt}]
    
    print(f"\n🧠 Fusion ({FUSION_MODEL}) thinking...\n")
    
    try:
        result = api_call(messages, model=FUSION_MODEL, temperature=args.temperature, max_tokens=args.max_tokens)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    choice = result["choices"][0]
    content = choice["message"]["content"]
    usage = result.get("usage", {})
    model_used = choice.get("model", FUSION_MODEL)

    print(content)
    print(f"\n─── {model_used} │ {usage.get('prompt_tokens', '?')}↑ {usage.get('completion_tokens', '?')}↓ ${usage.get('total_cost', 0):.6f} ───")


def cmd_chat(args) -> None:
    """Interactive chat loop."""
    messages = []
    print(f"\n💬 Fusion Chat ({FUSION_MODEL})")
    print("   Type /exit to quit, /clear to reset, /system <msg> to set system prompt\n")
    
    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/clear":
            messages = []
            print("🧹 Chat cleared.\n")
            continue
        if user_input.startswith("/system "):
            system_msg = user_input[8:].strip()
            messages = [m for m in messages if m["role"] != "system"]
            messages.insert(0, {"role": "system", "content": system_msg})
            print(f"⚙️  System prompt set.\n")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            result = api_call(messages, model=FUSION_MODEL)
        except Exception as e:
            print(f"❌ {e}\n")
            messages.pop()
            continue

        choice = result["choices"][0]
        content = choice["message"]["content"]
        messages.append({"role": "assistant", "content": content})
        
        usage = result.get("usage", {})
        print(f"\nFusion> {content}")
        print(f"({usage.get('prompt_tokens', '?')}↑ {usage.get('completion_tokens', '?')}↓)\n")


def cmd_compare(prompt: str, args) -> None:
    """Compare Fusion against a standard model."""
    compare_model = args.model or "openrouter/auto"
    messages = [{"role": "user", "content": prompt}]

    print(f"\n⚡ Comparing: {FUSION_MODEL} vs {compare_model}\n")

    # Fusion first
    print(f"─── {FUSION_MODEL} ───")
    try:
        r1 = api_call(messages, model=FUSION_MODEL)
        c1 = r1["choices"][0]["message"]["content"]
        u1 = r1.get("usage", {})
        print(c1)
        print(f"  {u1.get('prompt_tokens', '?')}↑ {u1.get('completion_tokens', '?')}↓ | ${u1.get('total_cost', 0):.6f}\n")
    except Exception as e:
        print(f"  ❌ {e}\n")
        c1 = None

    # Compare model
    print(f"─── {compare_model} ───")
    try:
        r2 = api_call(messages, model=compare_model)
        c2 = r2["choices"][0]["message"]["content"]
        u2 = r2.get("usage", {})
        print(c2)
        print(f"  {u2.get('prompt_tokens', '?')}↑ {u2.get('completion_tokens', '?')}↓ | ${u2.get('total_cost', 0):.6f}")
    except Exception as e:
        print(f"  ❌ {e}")
        c2 = None

    if c1 and c2:
        print(f"\n📊 Fusion used {len(c1)} chars, {compare_model} used {len(c2)} chars")


def cmd_models(args) -> None:
    """List available free models."""
    print(f"\n📋 OpenRouter Free Models:\n")
    models = [
        ("openrouter/fusion", "Multi-model deliberation (FREE)", "1M ctx"),
        ("openrouter/auto", "Auto-select best model", "varies"),
        ("google/gemini-2.5-flash", "Google Gemini (FREE)", "1M ctx"),
        ("meta-llama/llama-4-maverick", "Meta Llama 4 Maverick (FREE)", "1M ctx"),
        ("deepseek/deepseek-chat", "DeepSeek V3 (FREE)", "128k ctx"),
        ("mistralai/mistral-small", "Mistral Small (FREE)", "128k ctx"),
        ("qwen/qwen3-235b-a22b", "Qwen 3 235B (FREE)", "128k ctx"),
    ]
    for model, desc, ctx in models:
        marker = "⭐" if model == FUSION_MODEL else "  "
        print(f"  {marker} {model:<38} {desc:<38} {ctx}")


def main():
    parser = argparse.ArgumentParser(
        description="Fusion CLI — OpenRouter multi-model deliberation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              fusion "Explain quantum computing"
              fusion chat
              fusion compare "Best sorting algorithm?"
              fusion models
              fusion auth sk-or-...
        """),
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # auth
    auth_p = sub.add_parser("auth", help="Save API key")
    auth_p.add_argument("key", help="OpenRouter API key")

    # query (default)
    query_p = sub.add_parser("query", help="Single prompt")
    query_p.add_argument("prompt", help="Your prompt")
    query_p.add_argument("-t", "--temperature", type=float, default=0.7)
    query_p.add_argument("-m", "--max-tokens", type=int, default=4096)

    # chat
    sub.add_parser("chat", help="Interactive chat")

    # compare
    comp_p = sub.add_parser("compare", help="Compare Fusion vs another model")
    comp_p.add_argument("prompt", help="Prompt to compare")
    comp_p.add_argument("-m", "--model", default=None, help="Model to compare against (default: auto)")

    # models
    sub.add_parser("models", help="List available models")

    args = parser.parse_args()

    # Handle positional prompt as query
    if args.command is None and len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        args.command = "query"
        args.prompt = sys.argv[1]
        # Re-parse with prompt captured... easier to just handle inline
        if not hasattr(args, 'temperature'):
            args.temperature = 0.7
        if not hasattr(args, 'max_tokens'):
            args.max_tokens = 4096

    if args.command == "auth":
        save_api_key(args.key)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "compare":
        cmd_compare(args.prompt, args)
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "query":
        cmd_query(args.prompt, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
