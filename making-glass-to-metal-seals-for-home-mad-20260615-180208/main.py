#!/usr/bin/env python3
"""
MATCOMPAT — Materials compatibility calculator for DIY builders.
Thermal expansion, glass-to-metal seals, galvanic corrosion, melting points.

Usage:
  matcompat seal glass_type metal_type    Check glass-to-metal seal viability
  matcompat expand material temp          Thermal expansion at temperature
  matcompat galvanic metal1 metal2        Galvanic corrosion risk
  matcompat melt material                 Melting point lookup
  matcompat list                          List all materials
"""

import argparse
import sys
import textwrap

# ── Materials Database ──────────────────────────────────

# CTE = Coefficient of Thermal Expansion (×10⁻⁶/°C)
MATERIALS = {
    # Glasses
    "borosilicate": {"type": "glass", "cte": 3.3, "melt": 820, "density": 2.23, "desc": "Pyrex, lab glass"},
    "soda-lime": {"type": "glass", "cte": 9.0, "melt": 720, "density": 2.50, "desc": "Window glass"},
    "quartz": {"type": "glass", "cte": 0.55, "melt": 1670, "density": 2.65, "desc": "Fused silica"},
    "aluminosilicate": {"type": "glass", "cte": 4.5, "melt": 920, "density": 2.55, "desc": "Gorilla glass type"},
    "lead-glass": {"type": "glass", "cte": 8.5, "melt": 630, "density": 3.10, "desc": "Crystal, low melt"},
    
    # Metals for sealing
    "tungsten": {"type": "metal", "cte": 4.5, "melt": 3422, "density": 19.3, "desc": "Best for borosilicate seals"},
    "molybdenum": {"type": "metal", "cte": 4.8, "melt": 2623, "density": 10.2, "desc": "Good with borosilicate"},
    "kovar": {"type": "metal", "cte": 5.3, "melt": 1450, "density": 8.36, "desc": "Fe-Ni-Co alloy, matches borosilicate"},
    "platinum": {"type": "metal", "cte": 8.8, "melt": 1768, "density": 21.45, "desc": "Seals to soda-lime, expensive"},
    "dumet": {"type": "metal", "cte": 9.0, "melt": 1083, "density": 8.9, "desc": "Cu-clad Fe-Ni, for soda-lime"},
    "copper": {"type": "metal", "cte": 16.5, "melt": 1085, "density": 8.96, "desc": "High CTE, house seals only"},
    "stainless-304": {"type": "metal", "cte": 17.3, "melt": 1450, "density": 8.0, "desc": "Poor glass match"},
    "nickel": {"type": "metal", "cte": 13.0, "melt": 1455, "density": 8.9, "desc": "Moderate match"},
    "iron": {"type": "metal", "cte": 11.8, "melt": 1538, "density": 7.87, "desc": "Poor glass match"},
    "aluminum": {"type": "metal", "cte": 23.1, "melt": 660, "density": 2.70, "desc": "Very poor glass match"},
    "titanium": {"type": "metal", "cte": 8.6, "melt": 1668, "density": 4.51, "desc": "Possible with special glass"},
    
    # Other
    "invar": {"type": "metal", "cte": 1.2, "melt": 1430, "density": 8.1, "desc": "Fe-Ni, near-zero expansion"},
    "graphite": {"type": "other", "cte": 2.0, "melt": 3650, "density": 2.25, "desc": "Sublimes, not melt"},
}

# Galvanic series (volts vs SCE, approximate)
GALVANIC = {
    "graphite": 0.3, "platinum": 0.25, "titanium": 0.0,
    "stainless-304": -0.1, "copper": -0.2, "nickel": -0.25,
    "tungsten": -0.3, "molybdenum": -0.35, "iron": -0.5,
    "aluminum": -0.8, "kovar": -0.3, "dumet": -0.3,
    "invar": -0.3,
}

# ── Calculations ────────────────────────────────────────

def seal_compatibility(glass: str, metal: str) -> dict:
    """Check glass-to-metal seal viability based on CTE matching."""
    g = MATERIALS.get(glass.lower(), {})
    m = MATERIALS.get(metal.lower(), {})
    
    if not g:
        return {"error": f"Unknown glass: {glass}"}
    if not m:
        return {"error": f"Unknown metal: {metal}"}
    
    cte_diff = abs(g["cte"] - m["cte"])
    cte_ratio = max(g["cte"], m["cte"]) / min(g["cte"], m["cte"]) if min(g["cte"], m["cte"]) > 0 else 999
    
    # Classification
    if cte_diff < 1.0:
        seal_type = "MATCHED (Excellent)"
        grade = "A"
        note = "Direct glass-to-metal seal, no stress. Ideal for vacuum."
    elif cte_diff < 2.5:
        seal_type = "COMPRESSION (Good)"
        grade = "B"
        note = "Metal CTE slightly higher — puts glass in compression. Acceptable."
    elif cte_diff < 5.0:
        seal_type = "HOUSEKEEPER (Fair)"
        grade = "C"
        note = "Thin metal edge seal. Viable for non-critical vacuum."
    else:
        seal_type = "MISMATCH (Poor)"
        grade = "F"
        note = "Will crack on cooling. Do not use for vacuum seals."
    
    # Temperature check
    can_seal = g["melt"] > m["melt"] * 0.6 if m["type"] == "metal" else True
    if not can_seal:
        note += " WARNING: Metal melts before glass softens."
        grade = "F"
    
    return {
        "glass": glass,
        "metal": metal,
        "glass_cte": g["cte"],
        "metal_cte": m["cte"],
        "cte_diff": round(cte_diff, 1),
        "cte_ratio": round(cte_ratio, 1),
        "seal_type": seal_type,
        "grade": grade,
        "note": note,
        "glass_melt": g["melt"],
        "metal_melt": m["melt"],
    }


def thermal_expansion(material: str, delta_t: float, length: float = 1.0) -> dict:
    """Calculate thermal expansion."""
    m = MATERIALS.get(material.lower(), {})
    if not m:
        return {"error": f"Unknown material: {material}"}
    
    cte = m["cte"] * 1e-6
    expansion = length * cte * delta_t
    
    return {
        "material": material,
        "cte": m["cte"],
        "delta_t": delta_t,
        "original_length": length,
        "new_length": round(length + expansion, 6),
        "expansion_mm": round(expansion * 1000, 4),
        "expansion_pct": round(expansion / length * 100, 4),
    }


def galvanic_risk(metal1: str, metal2: str) -> dict:
    """Check galvanic corrosion risk."""
    v1 = GALVANIC.get(metal1.lower())
    v2 = GALVANIC.get(metal2.lower())
    
    if v1 is None:
        return {"error": f"Unknown metal: {metal1}"}
    if v2 is None:
        return {"error": f"Unknown metal: {metal2}"}
    
    diff = abs(v1 - v2)
    
    if diff < 0.15:
        risk = "NEGLIGIBLE"
        icon = "✅"
        note = "Safe to use together in any environment."
    elif diff < 0.3:
        risk = "LOW"
        icon = "⚠️"
        note = "Acceptable in dry environments. Avoid salt water."
    elif diff < 0.5:
        risk = "MODERATE"
        icon = "⚡"
        note = "Use protective coating. Different metals will corrode over time."
    else:
        risk = "HIGH"
        icon = "🔴"
        note = "Galvanic corrosion likely. Isolate metals or use sacrificial anode."
    
    anode = metal1 if v1 < v2 else metal2  # More negative = anode
    cathode = metal2 if v2 > v1 else metal1
    
    return {
        "metal1": metal1,
        "metal2": metal2,
        "voltage1": v1,
        "voltage2": v2,
        "difference": round(diff, 2),
        "risk": risk,
        "icon": icon,
        "note": note,
        "anode": anode,
        "cathode": cathode,
    }


# ── CLI ─────────────────────────────────────────────────

def cmd_seal(args):
    result = seal_compatibility(args.glass, args.metal)
    if "error" in result:
        print(f"❌ {result['error']}")
        return
    
    grades = {"A": "🟢", "B": "🟡", "C": "🟠", "F": "🔴"}
    
    print(f"\n🔬 Glass-to-Metal Seal: {args.glass} + {args.metal}")
    print(f"\n   Glass CTE:  {result['glass_cte']} ×10⁻⁶/°C (melt: {result['glass_melt']}°C)")
    print(f"   Metal CTE:  {result['metal_cte']} ×10⁻⁶/°C (melt: {result['metal_melt']}°C)")
    print(f"   CTE diff:   {result['cte_diff']} (ratio: {result['cte_ratio']}:1)")
    print(f"\n   Verdict: {grades.get(result['grade'],'?')} {result['seal_type']}")
    print(f"   {result['note']}")


def cmd_expand(args):
    result = thermal_expansion(args.material, args.temp, args.length)
    if "error" in result:
        print(f"❌ {result['error']}")
        return
    
    print(f"\n🌡️  {args.material}: ΔT={args.temp}°C")
    print(f"   CTE: {result['cte']} ×10⁻⁶/°C")
    print(f"   Original: {result['original_length']}m")
    print(f"   New:      {result['new_length']}m")
    print(f"   Δ:        {result['expansion_mm']}mm ({result['expansion_pct']}%)")


def cmd_galvanic(args):
    result = galvanic_risk(args.metal1, args.metal2)
    if "error" in result:
        print(f"❌ {result['error']}")
        return
    
    print(f"\n⚡ Galvanic: {args.metal1} + {args.metal2}")
    print(f"   {args.metal1}: {result['voltage1']}V  |  {args.metal2}: {result['voltage2']}V")
    print(f"   Difference: {result['difference']}V")
    print(f"   Risk: {result['icon']} {result['risk']}")
    print(f"   Anode (corrodes): {result['anode']}")
    print(f"   Cathode: {result['cathode']}")
    print(f"   {result['note']}")


def cmd_melt(args):
    m = MATERIALS.get(args.material.lower(), {})
    if not m:
        print(f"❌ Unknown: {args.material}")
        return
    print(f"\n🔥 {args.material}: melts at {m['melt']}°C ({m.get('desc','')})")


def cmd_list(args):
    filter_type = args.type
    materials = {k: v for k, v in MATERIALS.items() if not filter_type or v["type"] == filter_type}
    
    print(f"\n📋 Materials ({len(materials)}):\n")
    print(f"{'Name':<22} {'Type':<8} {'CTE':<10} {'Melt °C':<10} {'Description'}")
    print("-" * 80)
    for name, m in sorted(materials.items()):
        print(f"{name:<22} {m['type']:<8} {m['cte']:<10} {m['melt']:<10} {m['desc']}")


def main():
    parser = argparse.ArgumentParser(description="MatCompat — Materials compatibility for DIY builders")
    sub = parser.add_subparsers(dest="command")
    
    seal_p = sub.add_parser("seal", help="Check glass-to-metal seal")
    seal_p.add_argument("glass")
    seal_p.add_argument("metal")
    
    expand_p = sub.add_parser("expand", help="Thermal expansion")
    expand_p.add_argument("material")
    expand_p.add_argument("temp", type=float, help="ΔT in °C")
    expand_p.add_argument("--length", type=float, default=1.0, help="Original length in meters")
    
    galvanic_p = sub.add_parser("galvanic", help="Galvanic corrosion risk")
    galvanic_p.add_argument("metal1")
    galvanic_p.add_argument("metal2")
    
    melt_p = sub.add_parser("melt", help="Melting point")
    melt_p.add_argument("material")
    
    list_p = sub.add_parser("list", help="List materials")
    list_p.add_argument("--type", choices=["glass", "metal", "other"], default=None)
    
    args = parser.parse_args()
    
    if args.command == "seal":
        cmd_seal(args)
    elif args.command == "expand":
        cmd_expand(args)
    elif args.command == "galvanic":
        cmd_galvanic(args)
    elif args.command == "melt":
        cmd_melt(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
