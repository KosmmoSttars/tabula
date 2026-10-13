"""One living creature: body + mind + biography, stepping through time together."""

import collections
import time

import numpy as np

from . import persist
from .brain import Brain
from .life import Biography
from .bodies import DEFAULT as DEFAULT_BODY
from .config import Brain as BrainConfig
from .world import World

SAVE_EVERY_S = 10 * 60        # brain and biography, real seconds
MEMORY_EVERY_S = 30 * 60      # full replay memory, real seconds


class Being:
    def __init__(self, name: str | None = None, new: bool = False, seed: int | None = None,
                 body: str | None = None, brain_config=None):
        if name is None and not new:
            name = persist.latest_life()
        resume = name is not None and not new and (persist.life_dir(name) / "state.json").exists()
        if resume and not persist.compatible(name):
            raise SystemExit(f"{name} was born in an older Tabula with other senses and cannot wake up in this one.")
        if name is None or new:
            name = name or persist.random_name()
            while (persist.life_dir(name) / "state.json").exists():
                name = persist.random_name()
        self.name = name
        persist.life_dir(name).mkdir(parents=True, exist_ok=True)

        if resume:
            seed, body, mind = persist.read_birth(name)
            if mind is not None:   # a mind keeps the size it was born with
                brain_config = BrainConfig(**mind)
        elif seed is None:
            seed = int(np.random.default_rng().integers(0, 2**31))
        self.world = World(seed, body or DEFAULT_BODY)
        self.brain = Brain(self.world.obs_dim, self.world.act_dim, seed, brain_config)
        self.bio = Biography(name, persist.life_dir(name) / "life.log")
        if resume:
            persist.load(name, self.world, self.brain, self.bio)
            self.bio._mark(self.world.age, f"wake{len(self.bio.milestones)}", "Woke up")
        else:
            self.bio._mark(0.0, "born", f"Born as {name}, a {self.world.plan.title.lower()}")
        self.resumed = resume

        self.obs = self.world.observe()
        self.action = np.zeros(self.world.act_dim, dtype=np.float32)
        self.mood = 0.0
        self.novelty = 0.0
        self.reward = 0.0
        self.reward_parts: dict = {}
        self.trace = collections.deque(maxlen=600)   # (reward, novelty, mood) per step

        now = time.monotonic()
        self._saved_at = now
        self._memory_saved_at = now
        self.brain.start()

    def tick(self) -> None:
        a, self.mood, self.novelty = self.brain.act(self.obs)
        obs2, parts, events = self.world.step(a)
        r = float(sum(parts.values()))
        self.brain.remember(self.obs, a, r, obs2)
        while self.brain.behind:  # let the mind catch up with what the body lived through
            time.sleep(0.0005)
        self.obs, self.action, self.reward, self.reward_parts = obs2, a, r, parts
        self.trace.append((r, self.novelty, self.mood))

        w = self.world
        self.bio.record(w.age, w.body.torso.position.x, r, self.novelty, w.energy,
                        w.contacts[-1], events, self.brain.babbling)

        now = time.monotonic()
        if now - self._saved_at > SAVE_EVERY_S:
            self.save(with_memory=now - self._memory_saved_at > MEMORY_EVERY_S)

    def sleep(self) -> None:
        """Stop learning and save everything. The life continues on the next start."""
        self.brain.stop()
        self.save()

    def save(self, with_memory: bool = True) -> None:
        persist.save(self.name, self.world, self.brain, self.bio, with_memory)
        now = time.monotonic()
        self._saved_at = now
        if with_memory:
            self._memory_saved_at = now
