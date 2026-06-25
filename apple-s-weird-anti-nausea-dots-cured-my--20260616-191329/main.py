#!/usr/bin/env python3
"""termcue — Terminal Motion Cues Simulator (Apple Vehicle Motion Cues inspired).
Animates dots along the terminal border to reduce motion sickness in vehicles.
Usage: python3 main.py [--mode gentle|highway|turns|stopgo|train|boat|bumpy] [--dots N] [--speed X]
Ref: https://www.theverge.com/tech/942854/apple-vehicle-motion-cues-review-really-work
"""
import argparse, math, os, signal, sys, time
from typing import List, Tuple

# ── Terminal helpers ────────────────────────────────────────────────────────
def _ts() -> Tuple[int, int]:
    try: c, l = os.get_terminal_size()
    except (OSError, ValueError): c, l = 80, 24
    return max(c, 20), max(l, 8)

def _hide(): sys.stdout.write("\033[?25l"); sys.stdout.flush()
def _show(): sys.stdout.write("\033[?25h"); sys.stdout.flush()
def _cls(): sys.stdout.write("\033[2J\033[H"); sys.stdout.flush()
def _goto(c, r): sys.stdout.write(f"\033[{r};{c}H"); sys.stdout.flush()
def _color(fg=None, bg=None, bold=False):
    codes = (["1"] if bold else []) + \
            ([f"38;5;{fg}"] if fg is not None else []) + \
            ([f"48;5;{bg}"] if bg is not None else [])
    sys.stdout.write(f"\033[{';'.join(codes)}m" if codes else "\033[0m")
def _reset(): sys.stdout.write("\033[0m"); sys.stdout.flush()

# ── Motion modes (dx,dy vectors per tick) ───────────────────────────────────
MODES = {
    "gentle":  ("Gentle city driving", 120, 33, [
        (0,0),(.1,0),(.2,0),(.3,0),(.3,.05),(.2,.1),(.1,.05),(0,0),
        (-.1,0),(-.2,0),(-.3,-.05),(-.2,-.1),(-.1,-.05),(0,0),
        (0,.05),(.1,.1),(.1,.05),(0,0)]),
    "highway": ("Highway cruising", 100, 75, [
        (0,0),(0,0),(0,0),(0,0),(.15,0),(.2,0),(.15,0),(0,0),
        (0,0),(0,0),(0,0),(0,0),(-.15,0),(-.2,0),(-.15,0),(0,0)]),
    "turns":   ("Winding road", 100, 196, [
        (0,0),(.2,.05),(.4,.1),(.5,.15),(.3,.2),(.1,.15),(-.1,.05),(-.3,0),
        (-.5,-.05),(-.4,-.15),(-.3,-.2),(-.1,-.1),(.1,0),(.3,.1),(.4,.2),(.3,.15)]),
    "stopgo":  ("Stop-and-go traffic", 80, 208, [
        (0,0),(.5,0),(.7,0),(.3,0),(0,0),(-.6,0),(-.3,0),(0,0),
        (0,0),(0,0),(0,0),(.4,0),(.7,0),(.3,0),(0,0),(-.7,0)]),
    "train":   ("Train ride", 150, 141, [
        (0,0),(.1,.1),(0,.15),(-.1,.1),(0,0),(.1,-.1),(0,-.15),(-.1,-.1)]),
    "boat":    ("Boat on waves", 140, 51, [
        (0,0),(.05,.3),(.1,.5),(.1,.3),(.05,0),(0,-.3),(-.05,-.5),(-.1,-.3),
        (-.05,0),(0,.3),(.05,.4),(.05,.2)]),
    "bumpy":   ("Off-road terrain", 90, 34, [
        (0,0),(.3,.2),(-.1,-.15),(.2,-.1),(-.3,.1),(.1,.25),
        (-.2,-.2),(.3,.05),(-.1,-.1),(.15,.15),(-.25,-.05),(.2,-.15)]),
}

# ── Engine ──────────────────────────────────────────────────────────────────
class Dot:
    def __init__(self, pos: float, speed: float = 1.0):
        self.pos, self.speed = pos, speed
    def advance(self, amt: float, perim: float):
        self.pos = (self.pos + amt * self.speed) % perim

class Engine:
    def __init__(self, dots=6, speed=1.0, border=True, char="●", color=33):
        self.ndots, self.speed, self.border, self.char, self.color = dots, speed, border, char, color
        self.cols, self.lines = _ts()
        self.perim = 2 * (self.cols + self.lines - 2)
        self.dots: List[Dot] = []
        self.running = False
        self._place()

    def _place(self):
        self.dots.clear()
        step = self.perim / max(self.ndots, 1)
        for i in range(self.ndots):
            sv = 0.8 + 0.4 * ((i % 3) / 2.0)
            self.dots.append(Dot((i * step) % self.perim, self.speed * sv))

    def _colrow(self, p: float) -> Tuple[int, int]:
        w, h = self.cols, self.lines
        tl, rl, bl = w, h - 2, w
        if p < tl: return (int(p) % w, 0)
        p -= tl
        if p < rl: return (w - 1, 1 + int(p))
        p -= rl
        if p < bl: return (w - 1 - int(p), h - 1)
        p -= bl
        return (0, h - 2 - int(p))

    def _draw_border(self):
        w, h = self.cols, self.lines
        bar = "─" * (w - 2)
        _color(fg=self.color)
        _goto(1, 1); sys.stdout.write(f"┌{bar}┐")
        for r in range(1, h - 1):
            _goto(1, r + 1); sys.stdout.write("│")
            _goto(w, r + 1); sys.stdout.write("│")
        _goto(1, h); sys.stdout.write(f"└{bar}┘")
        _reset()

    def _frame(self, vecs, tick):
        vx, vy = vecs[tick % len(vecs)]
        motion = math.sqrt(vx * vx + vy * vy) * 2.0
        for d in self.dots:
            d.advance(motion, self.perim)
        if self.border:
            self._draw_border()
        _color(fg=self.color, bold=True)
        for d in self.dots:
            c, r = self._colrow(d.pos)
            c = max(1, min(self.cols, c + 1))
            r = max(1, min(self.lines, r + 1))
            _goto(c, r); sys.stdout.write(self.char)
        _reset(); sys.stdout.flush()

    def run(self, mode="gentle"):
        desc, tick_ms, color, vecs = MODES.get(mode, MODES["gentle"])
        self.color = color
        self.running = True
        _cls(); _hide(); tick = 0
        try:
            while self.running:
                nc, nl = _ts()
                if (nc, nl) != (self.cols, self.lines):
                    self.cols, self.lines = nc, nl
                    self.perim = 2 * (self.cols + self.lines - 2)
                    self._place(); _cls()
                self._frame(vecs, tick); tick += 1
                time.sleep(tick_ms / 1000.0)
        except KeyboardInterrupt: pass
        finally:
            self.running = False; _cls(); _show(); _reset(); _goto(1, 1)

    def stop(self): self.running = False

# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="termcue — Terminal Motion Cues Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Modes: " + ", ".join(f"{k} ({v[0]})" for k, v in MODES.items()))
    p.add_argument("--mode", "-m", default="gentle", choices=list(MODES),
                   help="Motion pattern (default: gentle)")
    p.add_argument("--dots", "-n", type=int, default=6, metavar="N",
                   help="Number of dots 1-20 (default: 6)")
    p.add_argument("--speed", "-s", type=float, default=1.0, metavar="X",
                   help="Speed multiplier 0.1-5.0 (default: 1.0)")
    p.add_argument("--no-border", action="store_true", help="Hide border")
    p.add_argument("--dot-char", default="●", metavar="C", help="Dot char (default: ●)")
    p.add_argument("--list-modes", action="store_true", help="List modes and exit")
    a = p.parse_args()

    if a.list_modes:
        print("\nAvailable modes:\n" + "─" * 45)
        for k, v in MODES.items():
            print(f"  {k:10s} {v[0]}  (tick={v[1]}ms, {len(v[3])} vectors)")
        print(); return

    if not (1 <= a.dots <= 20):
        print("Error: --dots must be 1-20", file=sys.stderr); sys.exit(1)
    if not (0.1 <= a.speed <= 5.0):
        print("Error: --speed must be 0.1-5.0", file=sys.stderr); sys.exit(1)

    eng = Engine(dots=a.dots, speed=a.speed, border=not a.no_border,
                 char=a.dot_char, color=MODES[a.mode][2])
    signal.signal(signal.SIGINT, lambda *_: eng.stop())
    signal.signal(signal.SIGTERM, lambda *_: eng.stop())

    print(f"\n  termcue — {MODES[a.mode][0]}")
    print(f"  Dots: {a.dots}  Speed: {a.speed}x  Border: {'on' if not a.no_border else 'off'}")
    print("  Ctrl+C to exit.\n")
    time.sleep(1.2)
    eng.run(a.mode)

if __name__ == "__main__":
    main()
