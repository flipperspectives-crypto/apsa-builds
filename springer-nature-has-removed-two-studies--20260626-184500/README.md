# RetractWatch

CLI tool to track retracted academic papers using the [OpenAlex API](https://openalex.org) (free, no API key required).

## Background

Academic paper retractions are on the rise. Springer Nature, Elsevier, Wiley, and other major publishers periodically retract studies for issues ranging from honest error to outright fraud. This tool lets you monitor the retraction landscape — by author, by publisher, or by recency.

## Requirements

- Python 3.9+
- No external pip packages — uses only Python standard library (`urllib`, `json`, `argparse`)

## Installation

```bash
git clone <repo-url> && cd <repo-dir>
# No pip install needed — pure stdlib.
```

## Usage

```bash
# Show help
python3 main.py --help

# Search retractions by author
python3 main.py author "Max Planck"

# Search retractions by publisher
python3 main.py publisher "Springer Nature"

# Recently retracted papers (last 30 days)
python3 main.py recent --days 30

# Retraction statistics
python3 main.py stats

# Daily digest — stats + recent retractions
python3 main.py digest
```

## Examples

```bash
$ python3 main.py author "Max Planck"
🔍 Searching for retracted works by: Max Planck

  Found 2 retracted work(s):

  Title:   [retracted paper title]
  Author:  Max Planck, ...
  Year:    2024
  Journal: Nature
  DOI:     https://doi.org/10.xxxx/xxxxx

$ python3 main.py stats
  Total retracted works tracked: 58,421
  By publication year:
    2024: 4,201  ████████████████████████████
    2023: 5,400  ██████████████████████████████████
    ...
```

## Data Source

[OpenAlex](https://openalex.org) — an open, comprehensive catalog of scholarly works. All data is freely available without authentication.

## License

MIT
