# ArchaeoBoard

Real-time dashboard tracking archaeological discoveries worldwide.

Scrapes Google News for archaeological finds, classifies by historical era (Roman, Greek, Egyptian, Viking, etc.), and displays in a dark-themed interactive dashboard.

## Quickstart

```bash
# Fetch discoveries and view dashboard
python main.py --update
python main.py

# Open http://127.0.0.1:8090
```

## Features

- **10 historical eras** auto-detected from headlines
- **Real-time dashboard** with era filtering
- **Stats panel** — total finds, eras, sources, classification rate
- **Zero dependencies** — pure Python stdlib
- **Persistent storage** — discoveries saved to `~/.archaeology/`

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/` | Dashboard HTML |
| `/api/discoveries` | JSON list of all discoveries |
| `/api/refresh` | Trigger new fetch |
| `/health` | Health check |

## Why

Archaeological discoveries make headlines then vanish. ArchaeoBoard collects and categorizes them so you can browse finds by era — from Roman villas to dinosaur fossils — all in one place.
