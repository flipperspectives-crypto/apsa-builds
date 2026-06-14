# GATEKEEPER — Food Authenticity Checker

**LLM-generated** — real implementation, not a template stub.

A playful CLI that checks whether your recipe is "authentic" according to internet gatekeepers. Contains built-in traditional recipes sourced from Wikipedia, and scores your ingredient list against them.

Inspired by: [What even is food authenticity?](https://iza.ac/posts/2026/06/food-authenticity/)

## Usage

```bash
python main.py carbonara                              # show traditional recipe
python main.py carbonara --check "egg,guanciale,pecorino,black pepper"
python main.py carbonara --check "egg,bacon,cream,garlic,parmesan"
python main.py --list                                  # list all known dishes
```

## Known Dishes

Carbonara, Cacio e Pepe, Amatriciana, Pesto alla Genovese, Bolognese, Hainanese Chicken Rice, Pad Thai, Pho

## Verdicts

- **AUTHENTIC** — 90%+ match, no forbidden ingredients. Nonna approves.
- **MOSTLY TRADITIONAL** — 70%+, minor substitutions tolerated.
- **LOOSELY INSPIRED** — 50%+, you're on thin ice.
- **FUSION** — 30%+, call it something else.
- **GATEKEEPER ANGRY** — Forbidden ingredients detected!
- **NOT EVEN CLOSE** — That's a different dish entirely.

## Zero Dependencies

Uses only Python stdlib. No pip install needed.
