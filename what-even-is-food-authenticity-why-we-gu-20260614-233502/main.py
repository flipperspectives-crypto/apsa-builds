#!/usr/bin/env python3
"""
GATEKEEPER — Food Authenticity CLI
Checks whether your recipe is "authentic" according to internet gatekeepers.

Based on: "What even is food authenticity?" by Iza (iza.ac)
A playful tool that scrapes Wikipedia for traditional recipes and compares
against user-provided ingredient lists.

Usage:
  python main.py carbonara                    # show traditional recipe
  python main.py carbonara --check "egg,guanciale,pecorino,black pepper"
  python main.py carbonara --check "egg,bacon,cream,garlic,parmesan"
  python main.py --list                        # list known dishes
"""

import argparse
import json
import re
import sys
import textwrap
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

# ── Built-in traditional recipes ──────────────────────────
# Sourced from Wikipedia + culinary consensus
TRADITIONAL = {
    "carbonara": {
        "ingredients": ["guanciale", "pecorino romano", "egg yolks", "black pepper", "pasta"],
        "forbidden": ["cream", "garlic", "bacon", "parmesan", "milk", "onion", "butter"],
        "region": "Rome, Italy",
        "notes": "No cream. Ever. Guanciale not bacon. Pecorino not parmesan.",
        "source": "https://en.wikipedia.org/wiki/Carbonara",
    },
    "cacio e pepe": {
        "ingredients": ["pecorino romano", "black pepper", "pasta", "pasta water"],
        "forbidden": ["butter", "olive oil", "cream", "parmesan"],
        "region": "Rome, Italy",
        "notes": "Three ingredients: cheese, pepper, pasta. That's it.",
        "source": "https://en.wikipedia.org/wiki/Cacio_e_pepe",
    },
    "amatriciana": {
        "ingredients": ["guanciale", "pecorino romano", "tomato", "white wine", "chili pepper", "pasta"],
        "forbidden": ["bacon", "pancetta", "parmesan", "onion", "garlic"],
        "region": "Amatrice, Italy",
        "notes": "Guanciale mandatory. No onion in the classic version.",
        "source": "https://en.wikipedia.org/wiki/Amatriciana",
    },
    "pesto alla genovese": {
        "ingredients": ["basil", "pine nuts", "garlic", "parmesan", "pecorino", "olive oil", "salt"],
        "forbidden": ["walnuts", "cashews", "spinach", "sun-dried tomatoes", "cilantro"],
        "region": "Genoa, Italy",
        "notes": "Mortar and pestle traditional. Basil must be young Genoese DOP.",
        "source": "https://en.wikipedia.org/wiki/Pesto",
    },
    "hainanese chicken rice": {
        "ingredients": ["chicken", "rice", "ginger", "garlic", "pandan leaves", "chicken fat", "sesame oil", "soy sauce", "chili sauce", "cucumber"],
        "forbidden": ["MSG", "stock cubes", "butter"],
        "region": "Singapore / Hainan, China",
        "notes": "The rice must be cooked in chicken fat. Chili sauce and ginger paste mandatory. Cucumber garnish not optional.",
        "source": "https://en.wikipedia.org/wiki/Hainanese_chicken_rice",
    },
    "pad thai": {
        "ingredients": ["rice noodles", "shrimp", "tofu", "egg", "tamarind paste", "fish sauce", "garlic", "bean sprouts", "peanuts", "lime", "chili"],
        "forbidden": ["ketchup", "soy sauce as tamarind substitute", "spaghetti"],
        "region": "Thailand",
        "notes": "Tamarind paste is non-negotiable. No ketchup.",
        "source": "https://en.wikipedia.org/wiki/Pad_thai",
    },
    "bolognese": {
        "ingredients": ["beef", "pancetta", "onion", "carrot", "celery", "tomato paste", "white wine", "milk", "broth", "tagliatelle"],
        "forbidden": ["spaghetti", "garlic", "oregano", "basil", "dried herbs", "ketchup"],
        "region": "Bologna, Italy",
        "notes": "Ragù alla Bolognese is served with tagliatelle, not spaghetti. Contains milk. No garlic. No herbs. Yes, really.",
        "source": "https://en.wikipedia.org/wiki/Bolognese_sauce",
    },
    "pho": {
        "ingredients": ["beef bones", "rice noodles", "star anise", "cinnamon", "ginger", "onion", "fish sauce", "beef slices", "bean sprouts", "Thai basil", "lime", "hoisin sauce"],
        "forbidden": ["chicken stock", "soy sauce", "cumin", "MSG in traditional northern style"],
        "region": "Vietnam",
        "notes": "Broth must be clear and aromatic. Bones charred first. Spices toasted.",
        "source": "https://en.wikipedia.org/wiki/Pho",
    },
}


class Gatekeeper:
    """Food authenticity checker."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.db = TRADITIONAL
    
    def normalize(self, ingredient: str) -> str:
        """Lowercase, strip whitespace, remove plurals."""
        ing = ingredient.strip().lower()
        # Basic plural handling
        if ing.endswith("s") and len(ing) > 4:
            if not ing.endswith("ss") and not ing.endswith("us"):
                ing = ing[:-1]
        return ing
    
    def list_dishes(self):
        """List all known dishes."""
        for name, info in sorted(self.db.items()):
            print(f"  {name:30s} {info['region']}")
    
    def show_traditional(self, dish: str):
        """Display the traditional recipe."""
        info = self.db.get(dish.lower())
        if not info:
            print(f"❌ Unknown dish: {dish}")
            print(f"   Known dishes: {', '.join(sorted(self.db.keys()))}")
            sys.exit(1)
        
        print(f"\n═══ {dish.upper()} ═══")
        print(f"Region:  {info['region']}")
        print(f"Source:  {info['source']}")
        print(f"\nTraditional ingredients ({len(info['ingredients'])}):")
        for ing in info["ingredients"]:
            print(f"  ✓ {ing}")
        print(f"\nFORBIDDEN (authenticity crimes):")
        for ing in info["forbidden"]:
            print(f"  ✗ {ing}")
        print(f"\nNotes: {info['notes']}")
    
    def check(self, dish: str, user_ingredients: list[str]) -> dict:
        """Check user's ingredients against traditional recipe."""
        info = self.db.get(dish.lower())
        if not info:
            return {"error": f"Unknown dish: {dish}. Known: {', '.join(sorted(self.db.keys()))}"}
        
        trad_set = set(self.normalize(i) for i in info["ingredients"])
        forbid_set = set(self.normalize(i) for i in info["forbidden"])
        user_set = set(self.normalize(i) for i in user_ingredients)
        
        matching = user_set & trad_set
        missing = trad_set - user_set
        crimes = user_set & forbid_set
        extras = user_set - trad_set - forbid_set
        total_trad = len(trad_set)
        score = len(matching) / total_trad if total_trad > 0 else 0
        
        return {
            "dish": dish,
            "region": info["region"],
            "total_traditional": total_trad,
            "matching": sorted(matching),
            "missing": sorted(missing),
            "authenticity_crimes": sorted(crimes),
            "extras": sorted(extras),
            "score": score,
            "verdict": self._verdict(score, crimes),
            "notes": info["notes"],
        }
    
    def _verdict(self, score: float, crimes: list) -> str:
        """Determine authenticity verdict."""
        if crimes:
            return "GATEKEEPER ANGRY — FORBIDDEN INGREDIENTS DETECTED"
        elif score >= 0.9:
            return "AUTHENTIC — Nonna would approve"
        elif score >= 0.7:
            return "MOSTLY TRADITIONAL — Minor substitutions tolerated"
        elif score >= 0.5:
            return "LOOSELY INSPIRED — You're on thin ice"
        elif score >= 0.3:
            return "FUSION — Call it something else"
        else:
            return "NOT EVEN CLOSE — That's a different dish entirely"


def main():
    parser = argparse.ArgumentParser(
        description="GATEKEEPER — Food Authenticity Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
Examples:
  %(prog)s carbonara
  %(prog)s carbonara --check "egg,guanciale,pecorino,black pepper"
  %(prog)s carbonara --check "egg,bacon,cream,garlic,parmesan"
  %(prog)s --list
        """),
    )
    parser.add_argument("dish", nargs="?", help="Dish name (e.g., carbonara, pho, bolognese)")
    parser.add_argument("--check", help="Comma-separated ingredient list to verify")
    parser.add_argument("--list", action="store_true", help="List all known dishes")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    
    gk = Gatekeeper(verbose=args.verbose)
    
    if args.list:
        print("\nKnown dishes:")
        gk.list_dishes()
        return
    
    if not args.dish:
        parser.print_help()
        sys.exit(1)
    
    if args.check:
        ingredients = [i.strip() for i in args.check.split(",") if i.strip()]
        result = gk.check(args.dish, ingredients)
        
        if "error" in result:
            print(f"\n❌ {result['error']}")
            sys.exit(1)
        
        print(f"\n═══ AUTHENTICITY REPORT: {result['dish'].upper()} ═══")
        print(f"Region: {result['region']}")
        print(f"Score:  {result['score']:.0%} ({result['verdict']})")
        print()
        
        if result["matching"]:
            print(f"✅ Correct ({len(result['matching'])}/{result['total_traditional']}):")
            for ing in result["matching"]:
                print(f"    {ing}")
        
        if result["missing"]:
            print(f"\n❌ Missing:")
            for ing in result["missing"]:
                print(f"    {ing}")
        
        if result["authenticity_crimes"]:
            print(f"\n🚨 AUTHENTICITY CRIMES:")
            for ing in result["authenticity_crimes"]:
                print(f"    {ing}")
        
        if result["extras"]:
            print(f"\n⚠️  Acceptable variations:")
            for ing in result["extras"]:
                print(f"    {ing}")
        
        print(f"\n📝 {result['notes']}")
    else:
        gk.show_traditional(args.dish)


if __name__ == "__main__":
    main()
