# Fusion CLI

OpenRouter Fusion API CLI — free multi-model deliberation.

**Fusion** turns your prompt into a small multi-model deliberation. Multiple models weigh in, then synthesize the best response. **$0/million tokens, 1M context window.**

## Quickstart

```bash
# Set API key (get one at https://openrouter.ai/keys)
export OPENROUTER_API_KEY="sk-or-..."
# Or save it:
python main.py auth sk-or-...

# Single query
python main.py "Explain quantum entanglement"

# Interactive chat
python main.py chat

# Compare Fusion vs standard model
python main.py compare "Best sorting algorithm?"

# List free models
python main.py models
```

## Commands

| Command | Description |
|---------|-------------|
| `"prompt"` | Single query through Fusion |
| `chat` | Interactive multi-turn chat |
| `compare "prompt"` | Side-by-side Fusion vs another model |
| `models` | List available free models |
| `auth <key>` | Save API key to ~/.config/fusion/ |

## Why Fusion?

- **Free** — $0 per million tokens
- **Multi-model** — automatically deliberates across models
- **1M context** — huge context window
- **Better answers** — crowd wisdom from multiple AIs

## Problem Solved

OpenRouter Fusion is a powerful but under-documented free API. This CLI makes it instantly usable from the terminal — no browser, no copy-paste, just type and get multi-model answers.
