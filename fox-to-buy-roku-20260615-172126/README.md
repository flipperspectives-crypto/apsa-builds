# DealWatch

Track mergers, acquisitions, and regulatory filings from the terminal.

Watches Google News, Hacker News, and SEC EDGAR for deal status changes. Alerts on keywords like "approved", "blocked", "antitrust", "FTC", and more.

## Quickstart

```bash
# Track a deal
python main.py track "Fox Roku"

# With custom search keywords
python main.py track "Microsoft Activision" --keywords "MSFT,ATVI,merger,acquisition"

# Check for updates
python main.py check

# List all tracked deals
python main.py list

# Stop tracking
python main.py remove "Fox Roku"
```

## How It Works

1. **Track** — saves deal name with search keywords to `~/.dealwatch/state.json`
2. **Check** — scrapes Google News RSS, HN Algolia, and SEC EDGAR for new articles
3. **Alert** — scans titles/URLs for trigger words (approved, blocked, FTC, lawsuit, etc.)
4. **Deduplicate** — tracks seen URLs so you only get new alerts

## Alert Triggers

| Category | Keywords |
|----------|----------|
| Approval | approved, cleared, completed, closed, finalized |
| Block/Reject | blocked, rejected, terminated, cancelled |
| Regulatory | antitrust, FTC, DOJ, investigation, regulatory |
| Legal | lawsuit, proxy, shareholder vote |
| Filing | 8-K, S-4, 13D, filing, tender offer |

## Why

M&A deals take months and status changes are easy to miss. DealWatch checks multiple sources on demand so you catch regulatory blocks, shareholder votes, and closing announcements without babysitting Bloomberg.
