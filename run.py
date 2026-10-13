"""Tabula: a creature that learns to live on its own.

    python run.py                 resume the most recent life (or start one)
    python run.py --new           give birth to a new creature
    python run.py --life Kaloru   resume a specific creature
    python run.py --headless      live without a window, as fast as possible
"""

import argparse
import time

from tabula.being import Being
from tabula.life import fmt_age


def headless(being: Being, report_every: float = 30.0) -> None:
    print(f"{being.name} is living headless. Ctrl+C to put it to sleep.")
    t0 = last = time.monotonic()
    n = 0
    try:
        while True:
            being.tick()
            n += 1
            now = time.monotonic()
            if now - last > report_every:
                bio, w = being.bio, being.world
                print(f"[{fmt_age(now - t0)} real | {fmt_age(w.age)} lived] {bio.stage:9s} "
                      f"meals {bio.meals:5d}  farthest {bio.farthest:7.1f} m  speed {bio.speed:.2f} m/s  "
                      f"energy {w.energy:4.0%}  {n / (now - last):.0f} steps/s", flush=True)
                last, n = now, 0
    except KeyboardInterrupt:
        pass
    finally:
        print("Going to sleep (saving)...")
        being.sleep()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", action="store_true", help="start a new life")
    ap.add_argument("--life", help="name of the creature to resume or create")
    ap.add_argument("--seed", type=int, help="world seed for a new life")
    ap.add_argument("--headless", action="store_true", help="no window, maximum speed")
    args = ap.parse_args()

    being = Being(args.life, new=args.new, seed=args.seed)
    print(("Resumed " if being.resumed else "Born: ") + being.name)
    if args.headless:
        headless(being)
    else:
        from tabula.view import View
        View(being).run()


if __name__ == "__main__":
    main()
