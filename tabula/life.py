"""Biography: what happened to the creature, and what it has become."""

import collections
import datetime as dt
from pathlib import Path

from .config import PHYS

STAGES = ("babbling", "flailing", "crawling", "walking", "running")
WINDOW_S = 30  # simulated seconds used to judge how it moves right now


def fmt_age(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


class Biography:
    def __init__(self, name: str, log_path: Path | None = None):
        self.name = name
        self.born = dt.datetime.now().isoformat(timespec="seconds")
        self.log_path = log_path
        self.meals = 0
        self.rescues = 0
        self.exhaustions = 0
        self.gifts = 0             # meals dropped by visitors
        self.lifted = 0            # times it was lifted out of a pit
        self.nights = 0
        self.walked = 0.0          # total ground covered, metres
        self.farthest = 0.0        # farthest from birthplace, metres
        self.stage = "babbling"
        self.milestones: list[tuple[float, str]] = []
        self.achieved: set[str] = set()
        self.history: list[dict] = []  # one row per simulated minute

        self._xs = collections.deque(maxlen=WINDOW_S * PHYS.control_hz)
        self._scrape = collections.deque(maxlen=WINDOW_S * PHYS.control_hz)
        self._minute = self._blank_minute()
        self._last_x = None

    @staticmethod
    def _blank_minute() -> dict:
        return {"n": 0, "reward": 0.0, "novelty": 0.0, "energy": 0.0, "meals": 0, "x0": None, "x1": 0.0}

    # ---------------------------------------------------------------- live updates
    def record(self, age: float, x: float, reward: float, novelty: float, energy: float,
               torso_contact: bool, events: list[str], babbling: bool) -> list[str]:
        """Feed one step of life. Returns newly reached milestones as text."""
        if self._last_x is not None:
            self.walked += abs(x - self._last_x)
        self._last_x = x
        self.farthest = max(self.farthest, abs(x))
        self._xs.append(x)
        self._scrape.append(1.0 if torso_contact else 0.0)

        new = []
        for e in events:
            if e == "meal":
                self.meals += 1
                self._minute["meals"] += 1
            elif e.startswith("gift:"):
                self.meals += 1
                self.gifts += 1
                self._minute["meals"] += 1
                giver = e[5:]
                new += self._mark(age, "gift1", f"Ate food from a stranger ({giver})" if giver else
                                  "Ate food from a stranger")
            elif e == "rescued":
                self.rescues += 1
            elif e == "lifted":
                self.lifted += 1
                new += self._mark(age, "lifted", "Got stuck in a pit and was lifted out")
            elif e == "exhausted":
                self.exhaustions += 1
                new += self._mark(age, "exhausted", "Ran out of energy for the first time")

        m = self._minute
        m["n"] += 1
        m["reward"] += reward
        m["novelty"] += novelty
        m["energy"] += energy
        if m["x0"] is None:
            m["x0"] = x
        m["x1"] = x
        if m["n"] >= 60 * PHYS.control_hz:
            self._close_minute(age)

        self.stage = self._judge_stage(babbling)
        new += self._check_milestones(age)
        return new

    @property
    def speed(self) -> float:
        """Net travel speed over the recent window, m/s."""
        if len(self._xs) < 2:
            return 0.0
        return abs(self._xs[-1] - self._xs[0]) / (len(self._xs) / PHYS.control_hz)

    def _judge_stage(self, babbling: bool) -> str:
        if babbling:
            return "babbling"
        if len(self._xs) < self._xs.maxlen:
            return self.stage if self.stage != "babbling" else "flailing"
        scrape = sum(self._scrape) / len(self._scrape)
        v = self.speed
        if v < 0.15:
            return "flailing"
        if v < 0.5 or scrape > 0.3:
            return "crawling"
        if v < 1.5:
            return "walking"
        return "running"

    def _close_minute(self, age: float) -> None:
        m = self._minute
        n = m["n"]
        self.history.append({
            "age": round(age, 1),
            "reward": m["reward"] / n,
            "novelty": m["novelty"] / n,
            "energy": m["energy"] / n,
            "meals": m["meals"],
            "speed": abs(m["x1"] - m["x0"]) / 60.0,
            "stage": self.stage,
        })
        self._minute = self._blank_minute()

    # ---------------------------------------------------------------- milestones
    def _mark(self, age: float, key: str, text: str) -> list[str]:
        if key in self.achieved:
            return []
        self.achieved.add(key)
        self.milestones.append((age, text))
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"[{fmt_age(age)}] {text}\n")
        return [text]

    def _check_milestones(self, age: float) -> list[str]:
        new = []
        for n in (1, 10, 100, 1000, 10000):
            if self.meals >= n:
                text = "Found food for the first time" if n == 1 else f"Ate {n} meals"
                new += self._mark(age, f"meals{n}", text)
        for d in (2, 10, 50, 200, 1000, 5000):
            if self.farthest >= d:
                new += self._mark(age, f"far{d}", f"Wandered {d} m from its birthplace")
        idx = STAGES.index(self.stage)
        for s in STAGES[2:idx + 1]:
            new += self._mark(age, f"stage_{s}", f"Started {s}")
        for secs, label in ((3600, "an hour"), (86400, "a day"), (7 * 86400, "a week")):
            if age >= secs:
                new += self._mark(age, f"age{secs}", f"Lived for {label}")
        return new

    # ---------------------------------------------------------------- persistence
    def state(self) -> dict:
        return {
            "name": self.name, "born": self.born, "meals": self.meals, "rescues": self.rescues,
            "exhaustions": self.exhaustions, "gifts": self.gifts, "lifted": self.lifted,
            "walked": self.walked, "farthest": self.farthest,
            "stage": self.stage, "milestones": self.milestones, "achieved": sorted(self.achieved),
            "history": self.history,
        }

    def load(self, s: dict) -> None:
        self.name, self.born = s["name"], s["born"]
        self.meals, self.rescues, self.exhaustions = s["meals"], s["rescues"], s["exhaustions"]
        self.gifts, self.lifted = s.get("gifts", 0), s.get("lifted", 0)
        self.walked, self.farthest, self.stage = s["walked"], s["farthest"], s["stage"]
        self.milestones = [tuple(m) for m in s["milestones"]]
        self.achieved = set(s["achieved"])
        self.history = s["history"]
