"""The physical world: endless 2D land, day and night, food, and the creature's body."""

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pymunk

from .bodies import PLANS, BodyPlan
from .config import BODY, LAND, LIFE, PHYS, REWARD, SENSES

CREATURE_GROUP = 1
CHUNK = 16.0          # metres of terrain per chunk
SEGMENT = 0.5         # metres between terrain points on open ground
EDGE = 0.04           # horizontal run of a step, pit or bump wall: steep but not quite vertical


@dataclass(frozen=True)
class Feature:
    kind: str         # "pit", "bump" or "step"
    x0: float
    x1: float         # a step has x1 == x0
    size: float       # pit depth, bump height, or the step's change in level (outwards from the birthplace)


class Terrain:
    """Deterministic infinite land: hills that grow with distance from the birthplace, and pits, bumps
    and steps, more of them further out. Flat near the birthplace."""

    def __init__(self, space: pymunk.Space, seed: int):
        rng = np.random.default_rng(seed)
        self.seed = seed
        self.space = space
        self.amps = np.array([0.6, 0.3, 0.15, 0.08])
        self.freqs = np.array([0.07, 0.19, 0.43, 0.9])
        self.phases = rng.uniform(0, 2 * math.pi, size=4)
        self.chunks: dict[int, list[pymunk.Segment]] = {}

    # ---------------------------------------------------------------- shape
    @lru_cache(maxsize=4096)
    def features(self, k: int) -> tuple[Feature, ...]:
        """Pits, bumps and steps in chunk k."""
        lo, hi = k * CHUNK, (k + 1) * CHUNK
        near = min(abs(lo), abs(hi)) if lo * hi > 0 else 0.0
        if near < LAND.flat_radius:
            return ()
        rng = np.random.default_rng([self.seed, k + 1_000_000])
        chance = min(0.4 + (near - LAND.flat_radius) / 300.0, 0.8)
        out: list[Feature] = []
        x = lo + 1.0
        while True:
            x += rng.uniform(LAND.feature_spacing, CHUNK / 2)
            if x > hi - 2.0:
                break
            if rng.random() > chance:
                continue
            kind = rng.choice(["pit", "bump", "step"], p=[0.35, 0.3, 0.35])
            if kind == "pit":
                w = rng.uniform(*LAND.pit_width)
                out.append(Feature("pit", x, x + w, rng.uniform(*LAND.pit_depth)))
                x += w
            elif kind == "bump":
                w = rng.uniform(*LAND.bump_width)
                out.append(Feature("bump", x, x + w, rng.uniform(*LAND.bump_height)))
                x += w
            else:
                out.append(Feature("step", x, x, rng.choice([-1, 1]) * rng.uniform(*LAND.step_height)))
        return tuple(out)

    @lru_cache(maxsize=4096)
    def level_at_chunk(self, k: int) -> float:
        """Sum of the steps between the birthplace and the inner edge of chunk k."""
        if k == 0 or k == -1:
            return 0.0
        inner = k - 1 if k > 0 else k + 1
        return self.level_at_chunk(inner) + sum(f.size for f in self.features(inner) if f.kind == "step")

    def height(self, x: float) -> float:
        roughness = min(max((abs(x) - LAND.flat_radius + 4.0) / LAND.rough_over, 0.0), 1.0)
        h = roughness * float(np.sum(self.amps * np.sin(self.freqs * x + self.phases)))
        k = math.floor(x / CHUNK)
        h += self.level_at_chunk(k)
        for f in self.features(k):
            if f.kind == "step":
                # a step raises (or lowers) the land beyond it, going outwards from the birthplace
                past = (x - f.x0) if x >= 0 else (f.x0 - x)
                h += f.size * min(max(past / EDGE, 0.0), 1.0)
            else:
                inside = min(max(min(x - f.x0, f.x1 - x) / EDGE, 0.0), 1.0)
                h += inside * (-f.size if f.kind == "pit" else f.size)
        return h

    def points(self, x0: float, x1: float, step: float = SEGMENT) -> list[tuple[float, float]]:
        """The ground line from x0 to x1: regular points plus the corners of every feature."""
        xs = set(np.arange(math.floor(x0 / step) * step, x1 + step, step).round(4).tolist())
        for k in range(math.floor(x0 / CHUNK), math.floor(x1 / CHUNK) + 1):
            for f in self.features(k):
                for e in ((f.x0, f.x0 + EDGE) if f.kind == "step" and f.x0 >= 0 else
                          (f.x0 - EDGE, f.x0) if f.kind == "step" else
                          (f.x0, f.x0 + EDGE, f.x1 - EDGE, f.x1)):
                    xs.add(round(e, 4))
        return [(x, self.height(x)) for x in sorted(xs) if x0 - step <= x <= x1 + step]

    def pit_at(self, x: float) -> Feature | None:
        for f in self.features(math.floor(x / CHUNK)):
            if f.kind == "pit" and f.x0 <= x <= f.x1:
                return f
        return None

    # ---------------------------------------------------------------- physics
    def ensure_around(self, x: float, radius: int = 3) -> None:
        center = int(math.floor(x / CHUNK))
        wanted = set(range(center - radius, center + radius + 1))
        for k in list(self.chunks):
            if k not in wanted:
                self.space.remove(*self.chunks.pop(k))
        for k in wanted - self.chunks.keys():
            self.chunks[k] = self._build_chunk(k)

    def _build_chunk(self, k: int) -> list[pymunk.Segment]:
        pts = [p for p in self.points(k * CHUNK, (k + 1) * CHUNK) if k * CHUNK <= p[0] <= (k + 1) * CHUNK]
        segs = []
        for a, b in zip(pts, pts[1:]):
            s = pymunk.Segment(self.space.static_body, a, b, 0.04)
            s.friction = BODY.friction
            segs.append(s)
        self.space.add(*segs)
        return segs

    def profile(self, x0: float, x1: float, step: float = 0.25):
        return self.points(x0, x1, step)


class Creature:
    """A torso on legs, each with a hip and a knee motor, built from a body plan."""

    def __init__(self, space: pymunk.Space, plan: BodyPlan, x: float, ground_y: float):
        self.space = space
        self.plan = plan
        flt = pymunk.ShapeFilter(group=CREATURE_GROUP)
        tw, th = plan.torso_size

        self.torso = pymunk.Body(plan.torso_mass, pymunk.moment_for_box(plan.torso_mass, (tw, th)))
        self.torso_shape = pymunk.Poly.create_box(self.torso, (tw, th), radius=0.02)
        parts = [(self.torso, self.torso_shape)]

        self.thighs, self.shins, self.feet = [], [], []
        self.joints = []  # (body_a, body_b, motor, max_torque)
        for leg in plan.legs:
            hip = (leg.hip_x, -th / 2)
            mass, lw = plan.limb_mass, plan.limb_width
            thigh = pymunk.Body(mass, pymunk.moment_for_box(mass, (lw, plan.thigh_len)))
            thigh_shape = pymunk.Poly.create_box(thigh, (lw, plan.thigh_len), radius=0.01)
            shin = pymunk.Body(mass, pymunk.moment_for_box(mass, (lw, plan.shin_len)))
            shin_shape = pymunk.Poly.create_box(shin, (lw * 0.8, plan.shin_len), radius=0.01)
            foot = pymunk.Circle(shin, plan.foot_radius, (0, -plan.shin_len / 2))
            parts += [(thigh, thigh_shape), (shin, shin_shape), (None, foot)]

            for a, b, anchor_a, anchor_b, limits, torque in (
                (self.torso, thigh, hip, (0, plan.thigh_len / 2), plan.hip_limits, plan.hip_torque),
                (thigh, shin, (0, -plan.thigh_len / 2), (0, plan.shin_len / 2), plan.knee_limits, plan.knee_torque),
            ):
                pivot = pymunk.PivotJoint(a, b, anchor_a, anchor_b)
                limit = pymunk.RotaryLimitJoint(a, b, *limits)
                motor = pymunk.SimpleMotor(a, b, 0.0)
                motor.max_force = 0.0
                # Passive muscle tone: limbs drift back to neutral instead of folding like rope.
                tone = pymunk.DampedRotarySpring(a, b, 0.0, BODY.tone_stiffness, BODY.tone_damping)
                space.add(pivot, limit, motor, tone)
                self.joints.append((a, b, motor, torque))

            self.thighs.append(thigh)
            self.shins.append(shin)
            self.feet.append(foot)

        for body, shape in parts:
            shape.filter = flt
            shape.friction = BODY.friction
            if body is not None:
                space.add(body)
            space.add(shape)
        self.shapes = [s for _, s in parts]
        self.place(x, ground_y)

    def place(self, x: float, ground_y: float) -> None:
        """Put the body upright, standing, at rest, with feet just above the ground."""
        plan = self.plan
        th = plan.torso_size[1]
        leg = plan.thigh_len + plan.shin_len + plan.foot_radius
        ty = ground_y + leg + th / 2 + 0.05
        self.torso.position = (x, ty)
        for i, spec in enumerate(plan.legs):
            hx, hy = x + spec.hip_x, ty - th / 2
            self.thighs[i].position = (hx, hy - plan.thigh_len / 2)
            self.shins[i].position = (hx, hy - plan.thigh_len - plan.shin_len / 2)
        for b in self.bodies:
            b.angle = 0.0
            b.velocity = (0, 0)
            b.angular_velocity = 0.0

    @property
    def bodies(self):
        return [self.torso, *self.thighs, *self.shins]

    def actuate(self, action: np.ndarray, strength: float) -> None:
        # Box2D-walker style torque control: speed target by sign, force by magnitude.
        for (a, b, motor, torque), u in zip(self.joints, action):
            motor.rate = -math.copysign(BODY.max_joint_speed, u)
            motor.max_force = abs(float(u)) * torque * strength

    def joint_state(self):
        angles = [b.angle - a.angle for a, b, _, _ in self.joints]
        speeds = [b.angular_velocity - a.angular_velocity for a, b, _, _ in self.joints]
        return angles, speeds

    def touching(self, shape) -> bool:
        return len(self.space.shape_query(shape)) > 0


@dataclass
class Food:
    x: float
    y: float
    gift: str | None = None   # who dropped it, for food from visitors; None for the world's own


class World:
    """Physics + homeostasis. step(action) -> (obs, reward_parts, events)."""

    def __init__(self, seed: int = 0, body: str = "strider"):
        self.seed = seed
        self.plan = PLANS[body]
        self.rng = np.random.default_rng(seed + 1)
        self.space = pymunk.Space()
        self.space.gravity = (0, PHYS.gravity)
        self.space.iterations = PHYS.iterations
        self.space.collision_slop = PHYS.collision_slop
        self.terrain = Terrain(self.space, seed)
        self.terrain.ensure_around(0.0)
        self.body = Creature(self.space, self.plan, 0.0, self.terrain.height(0.0))

        n_legs, n_joints = len(self.plan.legs), self.plan.joints
        self.act_dim = n_joints
        self.obs_dim = 2 + 1 + 2 + 2 * n_joints + (n_legs + 1) + SENSES.lidar_rays + 3 + 1 + 1 + n_joints

        self.dt = 1.0 / (PHYS.control_hz * PHYS.substeps)
        self.age = 0.0                 # simulated seconds alive
        self.energy = 1.0
        self.foods: list[Food] = [self._food_at(5.0)]
        self.prev_action = np.zeros(self.act_dim, dtype=np.float32)
        self.helpless_for = 0.0
        self.pit_for = 0.0
        self.contacts: tuple[bool, ...] = (False,) * (n_legs + 1)   # each foot, then the torso
        self.lidar_hits: list[tuple[float, float]] = []
        self._target, self._dist = self._nearest()

    # ---------------------------------------------------------------- food
    def _food_at(self, x: float, gift: str | None = None) -> Food:
        pit = self.terrain.pit_at(x)
        if pit is not None:   # never at the bottom of a pit
            x = pit.x1 + 0.5
        return Food(x, self.terrain.height(x) + 0.12, gift)

    @property
    def food(self) -> Food:
        """The food the creature is heading for: the nearest."""
        return self._target

    def _nearest(self) -> tuple[Food, float]:
        p = self.body.torso.position
        best = min(self.foods, key=lambda f: math.hypot(f.x - p.x, f.y - p.y))
        return best, math.hypot(best.x - p.x, best.y - p.y)

    def spawn_food(self) -> None:
        direction = 1 if self.rng.random() < 0.6 else -1
        dist = self.rng.uniform(LIFE.food_min_dist, LIFE.food_max_dist)
        self.foods.append(self._food_at(self.body.torso.position.x + direction * dist))

    def gift(self, offset: float, giver: str) -> bool:
        """A visitor drops food `offset` metres from the creature. False if there is too much already."""
        if sum(1 for f in self.foods if f.gift) >= LIFE.gifts_max:
            return False
        self.foods.append(self._food_at(self.body.torso.position.x + offset, giver))
        return True

    # ---------------------------------------------------------------- time
    @property
    def daylight(self) -> float:
        """1 at noon, 0 in the dead of night; dawn and dusk are short ramps."""
        phase = (self.age / (LIFE.day_minutes * 60.0)) % 1.0
        day = 1.0 - LIFE.night_share
        if phase < day:
            return min(1.0, phase / 0.06, (day - phase) / 0.06)
        return 0.0

    @property
    def nursing(self) -> float:
        """Hunger strength: ramps from 0 to 1 over the first minutes of life."""
        return min(self.age / (LIFE.nursing_minutes * 60.0), 1.0)

    def rescue(self, x: float | None = None) -> None:
        x = self.body.torso.position.x if x is None else x
        self.body.place(x, self.terrain.height(x))
        self.helpless_for = 0.0
        self.pit_for = 0.0

    # ---------------------------------------------------------------- dynamics
    def step(self, action: np.ndarray):
        action = np.clip(np.asarray(action, dtype=np.float32), -1.0, 1.0)
        strength = 1.0 if self.energy > 0 else LIFE.exhausted_strength
        self.body.actuate(action, strength)
        for _ in range(PHYS.substeps):
            self.space.step(self.dt)
        step_dt = self.dt * PHYS.substeps
        self.age += step_dt
        events = []

        torso = self.body.torso
        self.terrain.ensure_around(torso.position.x)
        self.contacts = tuple(self.body.touching(f) for f in self.body.feet) \
            + (self.body.touching(self.body.torso_shape),)

        effort = float(np.mean(action ** 2))   # 0..1 whatever the number of motors
        burn = LIFE.energy_decay * self.nursing + LIFE.effort_cost * effort * self.nursing
        was_alive = self.energy > 0
        self.energy = max(self.energy - burn * step_dt, 0.0)
        if was_alive and self.energy == 0:
            events.append("exhausted")

        r = {"meal": 0.0, "approach": 0.0, "hunger": 0.0, "pain": 0.0, "effort": 0.0}
        for f in list(self.foods):
            if abs(f.x - torso.position.x) < LIFE.eat_reach and torso.position.y - f.y < 1.6:
                self.energy = min(self.energy + LIFE.meal_energy, 1.0)
                r["meal"] += REWARD.meal
                self.foods.remove(f)
                events.append(f"gift:{f.gift}" if f.gift else "meal")
                if f.gift is None:
                    self.spawn_food()
        target, dist = self._nearest()
        if r["meal"] == 0.0 and target is self._target:
            r["approach"] = REWARD.approach * (self._dist - dist)
        self._target, self._dist = target, dist   # a new target is no step closer to anything
        r["hunger"] = -REWARD.hunger * (1.0 - self.energy) ** 2 * self.nursing
        torso_down = self.contacts[-1]
        r["pain"] = -REWARD.pain if torso_down else 0.0
        r["effort"] = -REWARD.effort * effort * 4

        if math.cos(torso.angle) < -0.2 or torso_down:
            self.helpless_for += step_dt
            if self.helpless_for > LIFE.rescue_seconds:
                self.rescue()
                events.append("rescued")
        else:
            self.helpless_for = 0.0

        pit = self.terrain.pit_at(torso.position.x)
        self.pit_for = self.pit_for + step_dt if pit is not None else 0.0
        if pit is not None and self.pit_for > LIFE.pit_seconds:
            outward = pit.x1 if torso.position.x >= 0 else pit.x0
            self.rescue(outward + math.copysign(0.8, torso.position.x or 1.0))
            events.append("lifted")
        self._target, self._dist = self._nearest()

        self.prev_action = action
        return self.observe(), r, events

    # ---------------------------------------------------------------- senses
    def observe(self) -> np.ndarray:
        t = self.body.torso
        angles, speeds = self.body.joint_state()
        v_local = t.velocity.rotated(-t.angle)

        light = self.daylight
        reach = SENSES.night_lidar_range + (SENSES.lidar_range - SENSES.night_lidar_range) * light
        self.lidar_hits = []
        lidar = []
        flt = pymunk.ShapeFilter(group=CREATURE_GROUP)
        n = SENSES.lidar_rays
        for i in range(n):
            # A downward fan from back (200 deg) to front (340 deg), in the world frame.
            ang = math.radians(200 + 140 * i / (n - 1))
            end = t.position + pymunk.Vec2d(math.cos(ang), math.sin(ang)) * reach
            hit = self.space.segment_query_first(t.position, end, 0.0, flt)
            frac = hit.alpha if hit is not None else 1.0
            lidar.append(frac)
            self.lidar_hits.append(tuple(t.position + (end - t.position) * frac))

        f = self.food
        dx, dy = f.x - t.position.x, f.y - t.position.y
        d = math.hypot(dx, dy) + 1e-6
        scent = [dx / d, dy / d, math.exp(-d / SENSES.scent_scale)]

        obs = [
            math.sin(t.angle), math.cos(t.angle),
            t.angular_velocity / 5.0,
            v_local.x / 3.0, v_local.y / 3.0,
            *angles,
            *(s / BODY.max_joint_speed for s in speeds),
            *(1.0 if c else 0.0 for c in self.contacts),
            *lidar,
            *scent,
            self.energy,
            light,
            *self.prev_action,
        ]
        return np.asarray(obs, dtype=np.float32)

    # ---------------------------------------------------------------- persistence
    def snapshot(self) -> dict:
        return {
            "age": self.age,
            "energy": self.energy,
            "x": self.body.torso.position.x,
            "foods": [[f.x, f.y, f.gift] for f in self.foods],
            "rng": self.rng.bit_generator.state,
        }

    def restore(self, snap: dict) -> None:
        self.age = snap["age"]
        self.energy = snap["energy"]
        x = snap["x"]
        self.terrain.ensure_around(x)
        self.body.place(x, self.terrain.height(x))
        self.foods = [Food(*f) for f in snap["foods"]] or [self._food_at(x + 5.0)]
        if not any(f.gift is None for f in self.foods):
            self.spawn_food()
        self.rng.bit_generator.state = snap["rng"]
        self._target, self._dist = self._nearest()
