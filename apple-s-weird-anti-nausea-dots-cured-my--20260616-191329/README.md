# termcue — Terminal Motion Cues Simulator

Inspired by **Apple Vehicle Motion Cues** (iOS 18), `termcue` animates dots along
your terminal border to help reduce motion sickness when using a laptop or
tablet in a moving vehicle.

## How It Works

Your brain gets conflicting signals when you read a screen in a moving vehicle:
your eyes see a stationary display, but your vestibular system feels motion.
Apple's Vehicle Motion Cues places animated dots on screen edges that move with
the vehicle — giving your peripheral vision motion cues that match what your
body feels. This reduces the sensory conflict and eases nausea.

`termcue` brings this idea to the terminal.

## Quick Start

```bash
python3 main.py                  # Gentle city driving (default)
python3 main.py --mode highway   # Steady highway cruising
python3 main.py --mode boat      # Boat on gentle waves
python3 main.py --list-modes     # Show all available motion modes
```

Press **Ctrl+C** to exit.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--mode`, `-m` | Motion pattern | `gentle` |
| `--dots`, `-n` | Number of dots (1-20) | `6` |
| `--speed`, `-s` | Speed multiplier (0.1-5.0) | `1.0` |
| `--no-border` | Hide the terminal border | off |
| `--dot-char` | Character used for dots | `●` |
| `--list-modes` | List all modes and exit | — |

## Available Modes

| Mode | Description |
|------|-------------|
| `gentle` | Gentle city driving with mild sway |
| `highway` | Steady highway cruising with occasional lane changes |
| `turns` | Winding road with frequent turns |
| `stopgo` | Stop-and-go traffic |
| `train` | Train ride with rhythmic sway |
| `boat` | Boat on gentle waves (vertical motion) |
| `bumpy` | Bumpy off-road terrain |

## Requirements

- Python 3.8+
- **Zero pip dependencies** — pure standard library only
- Works on any terminal with ANSI escape code support (Linux, macOS, Termux, WSL)

## Reference

Apple Vehicle Motion Cues:  
https://www.theverge.com/tech/942854/apple-vehicle-motion-cues-review-really-work
