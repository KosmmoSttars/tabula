"""The physical world: endless 2D terrain, food, and the creature's body."""

import math

import numpy as np
import pymunk

from .config import BODY, LIFE, PHYS, REWARD, SENSES

CREATURE_GROUP = 1
CHUNK = 16.0          # metres of terrain per chunk
SEGMENT = 0.5         # metres per terrain segment
JOINT_NAMES = ("back hip", "back knee", "front hip", "front knee")


class Terrain:
    """Deterministic infinite hills. Flat near the birthplace, rougher further out."""

    def __init__(self, space: pymunk.Space, seed: int):
        rng = np.random.default_rng(seed)
        self.space = space
        self.amps = np.array([0.6, 0.3, 0.15, 0.08])
        self.freqs = np.array([0.07, 0.19, 0.43, 0.9])
        self.phases = rng.uniform(0, 2 * math.pi, size=4)
        self.chunks: dict[int, list[pymunk.Segment]] = {}

    def height(self, x: float) -> float:
        roughness = min(max((abs(x) - 8.0) / 60.0, 0.0), 1.0)
        return float(roughness * np.sum(self.amps * np.sin(self.freqs * x + self.phases)))

    def ensure_around(self, x: float, radius: int = 3) -> None:
        center = int(math.floor(x / CHUNK))
        wanted = set(range(center - radius, center + radius + 1))
        for k in list(self.chunks):
            if k not in wanted:
                self.space.remove(*self.chunks.pop(k))
        for k in wanted - self.chunks.keys():
            self.chunks[k] = self._build_chunk(k)

    def _build_chunk(self, k: int) -> list[pymunk.Segment]:
        xs = np.arange(k * CHUNK, (k + 1) * CHUNK + 1e-6, SEGMENT)
        pts = [(float(x), self.height(x)) for x in xs]
        segs = []
        for a, b in zip(pts, pts[1:]):
            s = pymunk.Segment(self.space.static_body, a, b, 0.04)
            s.friction = BODY.friction
            segs.append(s)
        self.space.add(*segs)
        return segs

    def profile(self, x0: float, x1: float, step: float = 0.25):
        xs = np.arange(x0, x1 + step, step)
        return [(float(x), self.height(x)) for x in xs]


class Creature:
    """A torso on two legs (back and front), each with a hip and a knee motor."""

    def __init__(self, space: pymunk.Space, x: float, ground_y: float):
        self.space = space
        flt = pymunk.ShapeFilter(group=CREATURE_GROUP)
        tw, th = BODY.torso_size

        self.torso = pymunk.Body(BODY.torso_mass, pymunk.moment_for_box(BODY.torso_mass, (tw, th)))
        self.torso_shape = pymunk.Poly.create_box(self.torso, (tw, th), radius=0.02)
        parts = [(self.torso, self.torso_shape)]

        self.thighs, self.shins, self.feet = [], [], []
        self.joints = []  # (body_a, body_b, motor, max_torque)
        for side in (-1, 1):
            hip = (side * BODY.hip_offset, -th / 2)
            thigh = pymunk.Body(BODY.limb_mass, pymunk.moment_for_box(BODY.limb_mass, (BODY.limb_width, BODY.thigh_len)))
            thigh_shape = pymunk.Poly.create_box(thigh, (BODY.limb_width, BODY.thigh_len), radius=0.01)
            shin = pymunk.Body(BODY.limb_mass, pymunk.moment_for_box(BODY.limb_mass, (BODY.limb_width, BODY.shin_len)))
            shin_shape = pymunk.Poly.create_box(shin, (BODY.limb_width * 0.8, BODY.shin_len), radius=0.01)
            foot = pymunk.Circle(shin, BODY.foot_radius, (0, -BODY.shin_len / 2))
            parts += [(thigh, thigh_shape), (shin, shin_shape), (None, foot)]

            for a, b, anchor_a, anchor_b, limits, torque in (
                (self.torso, thigh, hip, (0, BODY.thigh_len / 2), BODY.hip_limits, BODY.hip_torque),
                (thigh, shin, (0, -BODY.thigh_len / 2), (0, BODY.shin_len / 2), BODY.knee_limits, BODY.knee_torque),
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
        tw, th = BODY.torso_size
        leg = BODY.thigh_len + BODY.shin_len + BODY.foot_radius
        ty = ground_y + leg + th / 2 + 0.05
        self.torso.position = (x, ty)
        for i, side in enumerate((-1, 1)):
            hx, hy = x + side * BODY.hip_offset, ty - th / 2
            self.thighs[i].position = (hx, hy - BODY.thigh_len / 2)
            self.shins[i].position = (hx, hy - BODY.thigh_len - BODY.shin_len / 2)
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


class World:
    """Physics + homeostasis. step(action) -> (obs, reward_parts, events)."""

    obs_dim = 2 + 1 + 2 + 4 + 4 + 3 + SENSES.lidar_rays + 3 + 1 + 4
    act_dim = 4

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.rng = np.random.default_rng(seed + 1)
        self.space = pymunk.Space()
        self.space.gravity = (0, PHYS.gravity)
        self.space.iterations = PHYS.iterations
        self.space.collision_slop = PHYS.collision_slop
        self.terrain = Terrain(self.space, seed)
        self.terrain.ensure_around(0.0)
        self.body = Creature(self.space, 0.0, self.terrain.height(0.0))

        self.dt = 1.0 / (PHYS.control_hz * PHYS.substeps)
        self.age = 0.0                 # simulated seconds alive
        self.energy = 1.0
        self.food = self._food_at(5.0)
        self.prev_action = np.zeros(self.act_dim, dtype=np.float32)
        self.helpless_for = 0.0
        self.contacts = (False, False, False)  # back foot, front foot, torso
        self.lidar_hits: list[tuple[float, float]] = []
        self._dist = self._food_distance()

    # ---------------------------------------------------------------- world state
    def _food_at(self, x: float):
        return (x, self.terrain.height(x) + 0.12)

    def _food_distance(self) -> float:
        p = self.body.torso.position
        return math.hypot(self.food[0] - p.x, self.food[1] - p.y)

    def spawn_food(self) -> None:
        direction = 1 if self.rng.random() < 0.6 else -1
        dist = self.rng.uniform(LIFE.food_min_dist, LIFE.food_max_dist)
        self.food = self._food_at(self.body.torso.position.x + direction * dist)
        self._dist = self._food_distance()

    def rescue(self) -> None:
        x = self.body.torso.position.x
        self.body.place(x, self.terrain.height(x))
        self.helpless_for = 0.0

    @property
    def nursing(self) -> float:
        """Hunger strength: ramps from 0 to 1 over the first minutes of life."""
        return min(self.age / (LIFE.nursing_minutes * 60.0), 1.0)

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
        self.contacts = (
            self.body.touching(self.body.feet[0]),
            self.body.touching(self.body.feet[1]),
            self.body.touching(self.body.torso_shape),
        )

        effort = float(np.sum(action ** 2))
        burn = LIFE.energy_decay * self.nursing + LIFE.effort_cost * effort / 4 * self.nursing
        was_alive = self.energy > 0
        self.energy = max(self.energy - burn * step_dt, 0.0)
        if was_alive and self.energy == 0:
            events.append("exhausted")

        r = {"meal": 0.0, "approach": 0.0, "hunger": 0.0, "pain": 0.0, "effort": 0.0}
        dist = self._food_distance()
        fx, fy = self.food
        if abs(fx - torso.position.x) < LIFE.eat_reach and torso.position.y - fy < 1.6:
            self.energy = min(self.energy + LIFE.meal_energy, 1.0)
            r["meal"] = REWARD.meal
            events.append("meal")
            self.spawn_food()
        else:
            r["approach"] = REWARD.approach * (self._dist - dist)
            self._dist = dist
        r["hunger"] = -REWARD.hunger * (1.0 - self.energy) ** 2 * self.nursing
        r["pain"] = -REWARD.pain if self.contacts[2] else 0.0
        r["effort"] = -REWARD.effort * effort

        if math.cos(torso.angle) < -0.2 or self.contacts[2]:
            self.helpless_for += step_dt
            if self.helpless_for > LIFE.rescue_seconds:
                self.rescue()
                self._dist = self._food_distance()
                events.append("rescued")
        else:
            self.helpless_for = 0.0

        self.prev_action = action
        return self.observe(), r, events

    # ---------------------------------------------------------------- senses
    def observe(self) -> np.ndarray:
        t = self.body.torso
        angles, speeds = self.body.joint_state()
        v_local = t.velocity.rotated(-t.angle)

        self.lidar_hits = []
        lidar = []
        flt = pymunk.ShapeFilter(group=CREATURE_GROUP)
        n = SENSES.lidar_rays
        for i in range(n):
            # A downward fan from back (200 deg) to front (340 deg), in the world frame.
            ang = math.radians(200 + 140 * i / (n - 1))
            end = t.position + pymunk.Vec2d(math.cos(ang), math.sin(ang)) * SENSES.lidar_range
            hit = self.space.segment_query_first(t.position, end, 0.0, flt)
            frac = hit.alpha if hit is not None else 1.0
            lidar.append(frac)
            self.lidar_hits.append(tuple(t.position + (end - t.position) * frac))

        dx = self.food[0] - t.position.x
        dy = self.food[1] - t.position.y
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
            *self.prev_action,
        ]
        return np.asarray(obs, dtype=np.float32)

    # ---------------------------------------------------------------- persistence
    def snapshot(self) -> dict:
        return {
            "age": self.age,
            "energy": self.energy,
            "x": self.body.torso.position.x,
            "food": list(self.food),
            "rng": self.rng.bit_generator.state,
        }

    def restore(self, snap: dict) -> None:
        self.age = snap["age"]
        self.energy = snap["energy"]
        x = snap["x"]
        self.terrain.ensure_around(x)
        self.body.place(x, self.terrain.height(x))
        self.food = tuple(snap["food"])
        self.rng.bit_generator.state = snap["rng"]
        self._dist = self._food_distance()
