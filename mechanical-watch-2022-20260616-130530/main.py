#!/usr/bin/env python3
"""
TICK — Mechanical watch movement simulator.
Models escapements, gear trains, power reserves, and accuracy.

Usage:
  tick simulate               Run real-time simulation
  tick design --bph 28800     Design a movement
  tick compare                Compare famous movements
  tick accuracy --test 60     Test accuracy over N seconds
"""

import argparse
import math
import sys
import textwrap
import time
from dataclasses import dataclass

# ── Physics Constants ───────────────────────────────────
GRAVITY = 9.81
RESTITUTION = 0.7  # Coefficient of restitution for pallet fork

# ── Famous Movements ────────────────────────────────────
MOVEMENTS = {
    "ETA 2824-2": {"bph": 28800, "jewels": 25, "power_reserve_h": 38, "accuracy_spd": 7, "type": "automatic", "year": 1982},
    "Rolex 3235": {"bph": 28800, "jewels": 31, "power_reserve_h": 70, "accuracy_spd": 2, "type": "automatic", "year": 2015},
    "Omega 3861": {"bph": 21600, "jewels": 26, "power_reserve_h": 50, "accuracy_spd": 5, "type": "manual", "year": 2019},
    "Seiko 9R65": {"bph": 0, "jewels": 30, "power_reserve_h": 72, "accuracy_spd": 1, "type": "spring_drive", "year": 2004},
    "Zenith El Primero": {"bph": 36000, "jewels": 31, "power_reserve_h": 50, "accuracy_spd": 4, "type": "automatic", "year": 1969},
    "Unitas 6497": {"bph": 18000, "jewels": 17, "power_reserve_h": 46, "accuracy_spd": 10, "type": "manual", "year": 1950},
    "Patek 324": {"bph": 28800, "jewels": 29, "power_reserve_h": 45, "accuracy_spd": 2, "type": "automatic", "year": 2004},
}


@dataclass
class Movement:
    name: str
    bph: int
    power_reserve_h: int
    accuracy_spd: int  # seconds per day
    
    @property
    def beat_interval_ms(self) -> float:
        """Time between beats in milliseconds."""
        if self.bph == 0:
            return 0  # Spring Drive has no beats
        return 3600000 / self.bph
    
    @property
    def frequency_hz(self) -> float:
        """Oscillation frequency in Hz."""
        return self.bph / 7200 if self.bph > 0 else 0  # 2 beats per oscillation
    
    @property
    def daily_error_s(self) -> float:
        """Expected daily error in seconds."""
        return self.accuracy_spd
    
    @property
    def monthly_error_min(self) -> float:
        """Expected monthly error in minutes."""
        return self.accuracy_spd * 30 / 60


def simulate_escapement(bph: int, steps: int = 100):
    """Simulate a Swiss lever escapement for visualization."""
    interval = 3600000 / bph  # milliseconds between beats
    angle_per_beat = 360 / (bph / 3600)  # degrees of balance rotation per beat
    
    print(f"\n⏱️  Escapement Simulation — {bph} BPH ({bph/3600:.1f} Hz)")
    print(f"   Beat interval: {interval:.1f}ms")
    print(f"   Balance amplitude: ~270°")
    print(f"\n   Simulating {steps} beats...\n")
    
    amplitude = 270
    decay_per_beat = amplitude / (bph * 40 / 3600)  # Natural decay over ~40h
    
    for i in range(steps):
        # Impulse from escape wheel through pallet fork
        impulse = 5 + (amplitude / 270) * 3  # More impulse at higher amplitude
        amplitude = min(amplitude + impulse, 310) - decay_per_beat
        
        tick = "▐" if i % 2 == 0 else "▌"
        bar_len = int(amplitude / 10)
        bar = "█" * bar_len + " " * (30 - bar_len)
        
        if i % 5 == 0:
            print(f"\r  [{i:>4}] {tick} |{bar}| {amplitude:.0f}°", end="", flush=True)
            time.sleep(0.05)
    
    print(f"\n  Final amplitude: {amplitude:.0f}°")


def cmd_simulate(args):
    bph = args.bph or 28800
    simulate_escapement(bph, args.steps)


def cmd_design(args):
    bph = args.bph or 28800
    interval = 3600000 / bph
    freq = bph / 7200
    
    # Gear train calculations
    # Typical gear train: barrel → center → third → fourth → escape
    # Ratios: center=1 rev/hr, fourth=1 rev/min, escape=1 rev/beat
    
    escape_teeth = 15  # Typical Swiss lever escape wheel
    fourth_teeth = 80  # Typical fourth wheel
    third_teeth = 75   # Typical third wheel
    center_teeth = 80  # Typical center wheel
    barrel_teeth = 72  # Typical barrel
    
    print(f"\n🔧 Movement Design — {bph} BPH\n")
    print(f"   Frequency:   {freq:.1f} Hz")
    print(f"   Beat interval: {interval:.1f}ms")
    print(f"\n   GEAR TRAIN:")
    print(f"   Barrel ({barrel_teeth}t) → Center ({center_teeth}t) → Third ({third_teeth}t)")
    print(f"   → Fourth ({fourth_teeth}t) → Escape ({escape_teeth}t)")
    
    total_ratio = (center_teeth/barrel_teeth) * (third_teeth/center_teeth) * (fourth_teeth/third_teeth) * (escape_teeth*2/fourth_teeth)
    print(f"\n   Total ratio: {total_ratio:.1f}:1")
    print(f"   Balance beats per barrel turn: {bph * 3600} during power reserve")
    
    # Power reserve estimate
    barrel_turns = 7  # Typical
    hours = barrel_turns * (barrel_teeth / center_teeth)
    print(f"\n   Estimated power reserve: {hours:.0f} hours ({barrel_turns} barrel turns)")
    
    # Accuracy estimate
    # Based on beat rate: higher = more accurate
    if bph >= 36000:
        estimated_accuracy = 2
    elif bph >= 28800:
        estimated_accuracy = 5
    elif bph >= 21600:
        estimated_accuracy = 10
    else:
        estimated_accuracy = 20
    
    print(f"   Estimated accuracy: ±{estimated_accuracy} sec/day")


def cmd_compare(args):
    print(f"\n⌚ Movement Comparison\n")
    print(f"{'Movement':<22} {'BPH':<10} {'Hz':<8} {'Jewels':<8} {'Power':<8} {'Acc/day':<10} {'Type':<12}")
    print("-" * 78)
    
    for name, m in MOVEMENTS.items():
        bph_str = f"{m['bph']:,}" if m['bph'] > 0 else "—"
        hz = m['bph'] / 7200 if m['bph'] > 0 else 0
        hz_str = f"{hz:.1f}" if hz > 0 else "—"
        print(f"{name:<22} {bph_str:<10} {hz_str:<8} {m['jewels']:<8} {m['power_reserve_h']}h{'':<4} ±{m['accuracy_spd']}s{'':<6} {m['type']:<12}")
    
    print(f"\n   🌟 Best accuracy: Seiko 9R65 (±1s/day)")
    print(f"   ⚡ Fastest beat:  Zenith El Primero (36,000 BPH)")
    print(f"   🔋 Longest reserve: Seiko 9R65 (72h)")


def cmd_accuracy(args):
    duration = args.test or 60
    bph = args.bph or 28800
    interval = 3600000 / bph / 1000  # seconds per beat
    expected_beats = int(duration / interval)
    
    print(f"\n🎯 Accuracy Test — {duration}s\n")
    print(f"   Movement: {bph} BPH")
    print(f"   Expected beats: {expected_beats:,}")
    print(f"   Beat interval: {interval*1000:.1f}ms")
    
    if not args.run:
        print(f"\n   Add --run to execute real-time test")
        return
    
    print(f"\n   Running... ", end="", flush=True)
    start = time.monotonic()
    beats = 0
    while time.monotonic() - start < duration:
        # Simulate a beat
        time.sleep(interval)
        beats += 1
        if beats % 100 == 0:
            print(".", end="", flush=True)
    
    elapsed = time.monotonic() - start
    error_s = elapsed - duration
    error_spd = error_s / duration * 86400  # extrapolate to 24h
    
    print(f"\n\n   Beats: {beats:,}")
    print(f"   Elapsed: {elapsed:.3f}s")
    print(f"   Drift: {error_s:+.3f}s")
    print(f"   Est. daily: {error_spd:+.1f} sec/day")


def main():
    parser = argparse.ArgumentParser(description="Tick — Mechanical watch movement simulator")
    sub = parser.add_subparsers(dest="command")
    
    sim_p = sub.add_parser("simulate", help="Run escapement simulation")
    sim_p.add_argument("--bph", type=int, default=28800, help="Beats per hour")
    sim_p.add_argument("--steps", type=int, default=100, help="Simulation steps")
    
    design_p = sub.add_parser("design", help="Design a movement")
    design_p.add_argument("--bph", type=int, default=28800, help="Target BPH")
    
    sub.add_parser("compare", help="Compare famous movements")
    
    acc_p = sub.add_parser("accuracy", help="Test accuracy")
    acc_p.add_argument("--test", type=int, default=60, help="Test duration in seconds")
    acc_p.add_argument("--bph", type=int, default=28800, help="BPH to test")
    acc_p.add_argument("--run", action="store_true", help="Execute real-time test")
    
    args = parser.parse_args()
    
    if args.command == "simulate":
        cmd_simulate(args)
    elif args.command == "design":
        cmd_design(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "accuracy":
        cmd_accuracy(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
