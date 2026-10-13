"""Tabula: a creature that learns to live on its own.

    python run.py                 resume the most recent life (or start one)
    python run.py --new           give birth to a new creature
    python run.py --new --body quadruped   ...with another body plan (strider, quadruped, hopper)
    python run.py --life Kaloru   resume a specific creature
    python run.py --headless      live without a window, as fast as possible
"""

import argparse
import time

from tabula.being import Being
from tabula.bodies import PLANS
from tabula.config import SMALL_BRAIN
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


def self_check() -> int:
    """For the build: every body plan is born, lives a little, sleeps and wakes. Writes tabula_check.txt
    next to the program (the built app has no console)."""
    import os
    import sys
    import tempfile
    import traceback
    from pathlib import Path

    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    lines, ok = [], True
    try:
        from tabula import persist
        persist.LIVES = Path(tempfile.mkdtemp(prefix="tabula-check-"))
        import torch
        lines.append(f"torch      {torch.__version__}, {torch.get_num_threads()} threads")
        for key in sorted(PLANS):
            b = Being(f"Check{key}", new=True, seed=1, body=key, brain_config=SMALL_BRAIN)
            t = time.perf_counter()
            for _ in range(1500):   # past babbling into learning
                b.tick()
            rate = 1500 / (time.perf_counter() - t)
            b.sleep()
            again = Being(f"Check{key}")
            woke = again.resumed and again.world.age > 49 and again.brain.steps == 1500
            again.brain.stop()
            ok &= woke
            lines.append(f"{key:10} {rate:5.0f} steps/s, {b.brain.updates} updates, "
                         f"{'slept and woke' if woke else 'DID NOT WAKE'}")
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.insert(0, f"self-check {'passed' if ok else 'FAILED'}")
    (base / "tabula_check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


def main() -> None:
    import sys
    if "--self-check" in sys.argv:
        raise SystemExit(self_check())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", action="store_true", help="start a new life")
    ap.add_argument("--life", help="name of the creature to resume or create")
    ap.add_argument("--seed", type=int, help="world seed for a new life")
    ap.add_argument("--body", choices=sorted(PLANS), help="body plan for a new life (default strider)")
    ap.add_argument("--headless", action="store_true", help="no window, maximum speed")
    ap.add_argument("--small-brain", action="store_true", help="the server's smaller, single-threaded mind")
    args = ap.parse_args()

    body = args.body
    if not args.headless and body is None and args.life is None:
        from tabula import persist
        if args.new or persist.latest_life() is None:
            from tabula.view import choose_body
            body = choose_body()
            if body is None:
                return
            args.new = True
    being = Being(args.life, new=args.new, seed=args.seed, body=body,
                  brain_config=SMALL_BRAIN if args.small_brain else None)
    print(("Resumed " if being.resumed else "Born: ") + being.name)
    if args.headless:
        headless(being)
    else:
        from tabula.view import View
        View(being).run()


if __name__ == "__main__":
    main()
