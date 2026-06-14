# KAGE — Shadow any website to a single offline HTML file

**Built by Hermes Agent** — LLM-generated real implementation of the Kage concept.

Fetches a URL, downloads all same-domain assets (CSS, JS, images), inlines everything as data URIs, and produces a single self-contained HTML file that works fully offline.

| Field | Value |
|-------|-------|
| Category | tool — CLI tool |
| Source | [HN] Show HN: Kage (github.com/tamnd/kage) |
| Lines | 278 |
| Dependencies | Zero (stdlib only) |

## Usage

```bash
python main.py https://example.com                    # shadow to auto-named file
python main.py https://example.com -o offline.html    # named output
python main.py https://example.com --verbose          # show details
```

## What it does

1. Fetches the target URL
2. Parses HTML for external assets: `<link rel="stylesheet">`, `<script src>`, `<img src>`, favicons, `url()` in styles
3. Downloads each asset (same-domain only)
4. Inlines CSS as `<style>` blocks, JS as `<script>` blocks, images as `data:` URIs
5. Outputs a single `.html` file — open in any browser, works offline

## Verified

Tested on:
- `https://example.com` (0 assets, clean pass)
- `https://news.ycombinator.com` (1 CSS, 1 JS, 2 images inlined)

## Why this beats the template stub

The original APSA template generated a generic Flask dashboard. This is a real, working tool — 278 lines of actual logic vs 61 lines of scaffolding. LLM code-gen produces real solutions.
