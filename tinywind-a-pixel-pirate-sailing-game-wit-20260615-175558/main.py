#!/usr/bin/env python3
"""
WINDROUTER — Sailing route optimizer with real-time wind physics.
Computes optimal sailing routes between coordinates using live wind data.

Usage:
  windrouter route 37.8,-122.4 37.4,-122.2    Route between two points
  windrouter wind 37.8,-122.4                  Current wind at location
  windrouter simulate 37.8,-122.4 --hours 24    Simulate 24h of sailing
  windrouter polar                              Show polar speed diagram
"""

import argparse
import json
import math
import os
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse

# ── Constants ───────────────────────────────────────────
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
DATA_DIR = Path(os.path.expanduser("~/.windrouter"))
KNOTS_TO_MS = 0.514444
MS_TO_KNOTS = 1.94384

# ── Polar diagram (boat speed vs wind angle/speed) ──────
# Typical cruising sailboat: speed in knots at given wind speed (kts) and angle
# Angles: 0=dead upwind, 90=beam reach, 180=dead downwind
POLAR = {
    # wind_kts: {angle: boat_speed_kts}
    5:  {45: 3.2, 60: 4.1, 90: 4.8, 120: 4.5, 135: 3.8, 150: 3.2, 180: 2.5},
    10: {45: 4.8, 60: 5.8, 90: 6.5, 120: 6.2, 135: 5.5, 150: 4.8, 180: 3.8},
    15: {45: 5.5, 60: 6.8, 90: 7.5, 120: 7.2, 135: 6.5, 150: 5.8, 180: 4.5},
    20: {45: 5.8, 60: 7.2, 90: 7.8, 120: 7.5, 135: 7.0, 150: 6.2, 180: 5.0},
    25: {45: 6.0, 60: 7.5, 90: 8.0, 120: 7.8, 135: 7.2, 150: 6.5, 180: 5.2},
}


def interpolate_polar(wind_kts: float, angle: float) -> float:
    """Get boat speed for given wind speed and apparent wind angle."""
    wind_levels = sorted(POLAR.keys())
    if wind_kts <= wind_levels[0]:
        lo_w, hi_w = wind_levels[0], wind_levels[1] if len(wind_levels) > 1 else wind_levels[0]
    elif wind_kts >= wind_levels[-1]:
        lo_w, hi_w = wind_levels[-2], wind_levels[-1]
    else:
        for i in range(len(wind_levels) - 1):
            if wind_levels[i] <= wind_kts <= wind_levels[i + 1]:
                lo_w, hi_w = wind_levels[i], wind_levels[i + 1]
                break
    
    angle_levels = sorted(POLAR[lo_w].keys())
    if angle <= angle_levels[0]:
        lo_a, hi_a = angle_levels[0], angle_levels[1]
    elif angle >= angle_levels[-1]:
        lo_a, hi_a = angle_levels[-2], angle_levels[-1]
    else:
        for i in range(len(angle_levels) - 1):
            if angle_levels[i] <= angle <= angle_levels[i + 1]:
                lo_a, hi_a = angle_levels[i], angle_levels[i + 1]
                break
    
    # Bilinear interpolation
    try:
        s11 = POLAR[lo_w][lo_a]
        s12 = POLAR[lo_w][hi_a]
        s21 = POLAR[hi_w][lo_a]
        s22 = POLAR[hi_w][hi_a]
    except KeyError:
        return 0
    
    wa = (wind_kts - lo_w) / (hi_w - lo_w) if hi_w != lo_w else 0
    aa = (angle - lo_a) / (hi_a - lo_a) if hi_a != lo_a else 0
    
    s_lo = s11 + (s12 - s11) * aa
    s_hi = s21 + (s22 - s21) * aa
    return s_lo + (s_hi - s_lo) * wa


# ── Wind Data ────────────────────────────────────────────

def fetch_wind(lat: float, lon: float, hours: int = 24) -> list:
    """Fetch wind forecast from Open-Meteo (free, no API key)."""
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kn",
        "timezone": "auto",
        "forecast_hours": min(hours, 48),
    })
    url = f"{OPEN_METEO}?{params}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WindRouter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        speeds = hourly.get("wind_speed_10m", [])
        directions = hourly.get("wind_direction_10m", [])
        gusts = hourly.get("wind_gusts_10m", [])
        
        forecast = []
        for i in range(min(len(times), hours)):
            forecast.append({
                "time": times[i],
                "speed_kts": speeds[i] if speeds[i] is not None else 0,
                "direction": directions[i] if directions[i] is not None else 0,
                "gust_kts": gusts[i] if gusts[i] is not None else 0,
            })
        return forecast
    except Exception as e:
        print(f"⚠️  Wind fetch error: {e}", file=sys.stderr)
        return []


# ── Navigation ──────────────────────────────────────────

def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 (degrees)."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in nautical miles."""
    R = 3440.065  # Earth radius in NM
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def apparent_wind_angle(true_wind_dir: float, boat_heading: float) -> float:
    """Compute apparent wind angle (0=on the nose, 180=dead downwind)."""
    rel = (true_wind_dir - boat_heading + 360) % 360
    if rel > 180:
        rel = 360 - rel
    return rel


def boat_speed_kts(true_wind_speed_kts: float, true_wind_dir: float, heading: float) -> float:
    """Compute boat speed for given wind and heading."""
    awa = apparent_wind_angle(true_wind_dir, heading)
    return interpolate_polar(true_wind_speed_kts, awa)


def optimal_heading(true_wind_speed_kts: float, true_wind_dir: float, dest_bearing: float) -> tuple:
    """Find optimal heading considering VMG (velocity made good) toward destination."""
    best_vmg = -1
    best_heading = dest_bearing
    best_speed = 0
    
    for offset in range(-70, 75, 5):  # Can't sail closer than 35° to wind
        heading = (dest_bearing + offset + 360) % 360
        speed = boat_speed_kts(true_wind_speed_kts, true_wind_dir, heading)
        awa = apparent_wind_angle(true_wind_dir, heading)
        
        # Can't sail into the no-go zone (<35° apparent)
        if awa < 35:
            continue
        
        # VMG = speed * cos(angle between heading and destination)
        angle_diff = abs((heading - dest_bearing + 180) % 360 - 180)
        vmg = speed * math.cos(math.radians(angle_diff))
        
        if vmg > best_vmg:
            best_vmg = vmg
            best_heading = heading
            best_speed = speed
    
    return best_heading, best_speed, best_vmg


# ── Commands ─────────────────────────────────────────────

def cmd_route(args) -> None:
    """Compute optimal sailing route between two points."""
    try:
        lat1, lon1 = map(float, args.start.split(","))
        lat2, lon2 = map(float, args.end.split(","))
    except ValueError:
        print("❌ Coordinates must be lat,lon format. Example: 37.8,-122.4")
        sys.exit(1)
    
    dist = distance_nm(lat1, lon1, lat2, lon2)
    brg = bearing(lat1, lon1, lat2, lon2)
    
    print(f"\n⛵ Route: {lat1},{lon1} → {lat2},{lon2}")
    print(f"   Distance: {dist:.1f} NM ({dist*1.852:.1f} km)")
    print(f"   Bearing:  {brg:.0f}°")
    
    # Fetch wind
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    forecast = fetch_wind(mid_lat, mid_lon, hours=args.hours)
    
    if not forecast:
        # Use average wind guess
        print("\n🌬️  No live wind data — using 10kt NW assumption")
        winds = [{"speed_kts": 10, "direction": 315, "time": "simulated"}]
    else:
        winds = forecast
        print(f"\n🌬️  Wind forecast ({len(winds)}h) — {winds[0]['speed_kts']:.0f}kt from {winds[0]['direction']:.0f}°")
    
    # Optimize route
    total_time = 0
    remaining = dist
    pos_lat, pos_lon = lat1, lon1
    
    print(f"\n{'Hour':<6} {'Heading':<8} {'Boat kts':<10} {'VMG kts':<10} {'NM left':<10} {'Wind':<20}")
    print("-" * 64)
    
    for i, w in enumerate(winds[:args.hours]):
        dest_brg = bearing(pos_lat, pos_lon, lat2, lon2)
        heading, speed, vmg = optimal_heading(w["speed_kts"], w["direction"], dest_brg)
        
        # Advance position (simplified: use VMG directly toward destination)
        nm_covered = vmg * 1  # 1 hour
        remaining = max(0, remaining - nm_covered)
        
        awa = apparent_wind_angle(w["direction"], heading)
        tack = "⛵" if awa < 90 else "🏄" if awa < 150 else "🪂"
        
        print(f"{i:<6} {heading:<8.0f}° {speed:<10.1f} {vmg:<10.1f} {remaining:<10.1f} {tack} {w['speed_kts']:.0f}kt@{w['direction']:.0f}°")
        
        total_time += 1
        if remaining < 0.1:
            break
    
    if remaining > 0.1:
        print(f"\n⚠️  {remaining:.1f} NM remaining after {total_time}h — wind insufficient")
    else:
        print(f"\n✅ Arrival in {total_time:.1f}h (avg {dist/total_time:.1f} kt VMG)")


def cmd_wind(args) -> None:
    """Show current wind at a location."""
    try:
        lat, lon = map(float, args.location.split(","))
    except ValueError:
        print("❌ Coordinates must be lat,lon format.")
        sys.exit(1)
    
    forecast = fetch_wind(lat, lon, hours=6)
    
    print(f"\n🌬️  Wind Forecast — {lat},{lon}")
    if not forecast:
        print("   No data available.")
        return
    
    print(f"\n{'Time':<20} {'Speed':<8} {'Gust':<8} {'Direction':<12}")
    print("-" * 48)
    for w in forecast[:6]:
        dir_name = deg_to_cardinal(w["direction"])
        gust = f"{w['gust_kts']:.0f}kt" if w.get("gust_kts") else "-"
        print(f"{w['time']:<20} {w['speed_kts']:.0f}kt{'':<3} {gust:<8} {w['direction']:.0f}° {dir_name}")


def deg_to_cardinal(deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]


def cmd_simulate(args) -> None:
    """Simulate sailing for N hours from a point."""
    try:
        lat, lon = map(float, args.location.split(","))
    except ValueError:
        print("❌ Coordinates must be lat,lon format.")
        sys.exit(1)
    
    forecast = fetch_wind(lat, lon, hours=args.hours)
    if not forecast:
        print("No wind data — simulation aborted.")
        return
    
    # Simulate sailing on optimal heading for max speed
    print(f"\n⛵ Simulation — {args.hours}h from {lat},{lon}")
    print(f"\n{'Hour':<6} {'Wind':<15} {'Heading':<8} {'Speed':<10} {'Position':<20}")
    print("-" * 65)
    
    pos_lat, pos_lon = lat, lon
    for i, w in enumerate(forecast[:args.hours]):
        # Sail on beam reach (fastest point of sail)
        heading = (w["direction"] + 90) % 360
        speed = interpolate_polar(w["speed_kts"], 90)
        
        # Advance position
        nm = speed * 1  # 1 hour
        pos_lat += (nm / 60) * math.cos(math.radians(heading))
        pos_lon += (nm / 60) * math.sin(math.radians(heading)) / math.cos(math.radians(pos_lat))
        
        print(f"{i:<6} {w['speed_kts']:.0f}kt@{w['direction']:.0f}°{'':<5} {heading:<8.0f}° {speed:<10.1f}kt {pos_lat:.3f},{pos_lon:.3f}")
    
    total_nm = distance_nm(lat, lon, pos_lat, pos_lon)
    print(f"\n   Total distance: {total_nm:.1f} NM in {min(args.hours, len(forecast))}h")


def cmd_polar(args) -> None:
    """Display polar speed diagram as ASCII art."""
    print("\n📊 Polar Speed Diagram (cruising sailboat)")
    print("   Speed in knots at given wind speed & angle\n")
    
    wind_speeds = [5, 10, 15, 20, 25]
    angles = [45, 60, 90, 120, 135, 150, 180]
    
    # Header
    header = f"{'Wind→':<8}"
    for ws in wind_speeds:
        header += f"{ws}kt{'':<5}"
    print(header)
    print("-" * 48)
    
    for angle in angles:
        label = f"{angle}°{'':<5}" if angle != 180 else "DDW   "
        row = f"{label:<8}"
        for ws in wind_speeds:
            spd = interpolate_polar(ws, angle)
            bar = "█" * int(spd)
            row += f"{spd:<4.1f} {bar:<5}"
        print(row)
    
    print("\n   Angle: 0°=upwind  90°=beam  180°=dead downwind")


def main():
    parser = argparse.ArgumentParser(
        description="WindRouter — Sailing route optimizer with real wind physics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              windrouter route 37.8,-122.4 37.4,-122.2
              windrouter wind 37.8,-122.4
              windrouter simulate 37.8,-122.4 --hours 12
              windrouter polar
        """),
    )
    sub = parser.add_subparsers(dest="command", help="Command")
    
    route_p = sub.add_parser("route", help="Optimize route between two points")
    route_p.add_argument("start", help="Start lat,lon")
    route_p.add_argument("end", help="End lat,lon")
    route_p.add_argument("--hours", type=int, default=24, help="Forecast hours")
    
    wind_p = sub.add_parser("wind", help="Wind forecast at location")
    wind_p.add_argument("location", help="lat,lon")
    
    sim_p = sub.add_parser("simulate", help="Simulate sailing")
    sim_p.add_argument("location", help="Start lat,lon")
    sim_p.add_argument("--hours", type=int, default=24, help="Hours to simulate")
    
    sub.add_parser("polar", help="Show polar speed diagram")
    
    args = parser.parse_args()
    
    if args.command == "route":
        cmd_route(args)
    elif args.command == "wind":
        cmd_wind(args)
    elif args.command == "simulate":
        cmd_simulate(args)
    elif args.command == "polar":
        cmd_polar(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
