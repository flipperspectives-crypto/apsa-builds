# M&A Radar

Real-time merger & acquisition intelligence dashboard.

Tracks deals across SEC EDGAR filings, stock prices, court dockets, and news — all in a dark-themed Live dashboard on port 8090.

## Quickstart

```bash
# Track a deal
python main.py track "Fox Roku" --tickers FOX,ROKU
python main.py track "Microsoft Activision" --tickers MSFT,ATVI

# Intel sweep (CLI)
python main.py check

# View SEC filings
python main.py filings TSLA

# Stock price
python main.py price AAPL

# Start dashboard
python main.py
# → http://127.0.0.1:8090
```

## Dashboard

Five live panels auto-refreshing every 60 seconds:

| Panel | Data Source | Refresh |
|-------|------------|---------|
| 🎯 Tracked Deals | Local state + DealWatch | Every load |
| 📄 SEC Filings | EDGAR RSS + submissions API | Per-request |
| 💰 Stock Prices | Yahoo Finance | Per-request |
| ⚖️ Court Dockets | CourtListener API | Per-request |
| 📰 News Feed | Google News RSS | Per-request |

Material events (8-K, S-4, 13D, SC TO-T) flagged with 🚨 alert banner.

## Architecture

- **Zero pip deps** — pure Python stdlib (urllib, xml.etree, json, http.server)
- **DealWatch integration** — reads ~/.dealwatch/state.json for backward compat
- **Ticker→CIK** — built-in map for 20+ common M&A stocks, SEC API with 24h cache
- **SEC fallback** — EDGAR RSS → submissions API

## Commands

| Command | Description |
|---------|-------------|
| (no args) | Start dashboard on :8090 |
| `track "Name" --tickers A,B` | Track a deal |
| `list` | List tracked deals |
| `check` | Full intel sweep (filings, prices, dockets, news) |
| `filings TICKER` | Recent SEC filings |
| `price TICKER` | Current stock price |
| `remove "Name"` | Stop tracking |

## Limitations

- SEC rate-limits automated access — filing data uses 24h cache with built-in ticker fallback
- CourtListener returns empty for some queries (free tier)
- ATVI (delisted) won't return prices — use acquirer ticker instead
