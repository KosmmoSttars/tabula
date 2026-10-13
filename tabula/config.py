"""All tunable constants in one place. Body plans live in bodies.py."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Physics:
    gravity: float = -9.81
    control_hz: int = 30          # brain decisions per simulated second
    substeps: int = 4             # physics steps per decision
    iterations: int = 20
    collision_slop: float = 0.005


@dataclass(frozen=True)
class Body:
    max_joint_speed: float = 6.0
    tone_stiffness: float = 20.0  # passive spring pulling every joint to neutral
    tone_damping: float = 1.5
    friction: float = 1.0


@dataclass(frozen=True)
class Land:
    flat_radius: float = 12.0     # metres around the birthplace without hills, pits or steps
    rough_over: float = 60.0      # hills grow to full height over this many metres beyond that
    feature_spacing: float = 3.0  # at least this far apart
    pit_width: tuple = (0.7, 1.5)
    pit_depth: tuple = (0.35, 0.6)
    step_height: tuple = (0.12, 0.3)
    bump_height: tuple = (0.15, 0.35)
    bump_width: tuple = (0.3, 0.6)


@dataclass(frozen=True)
class Senses:
    lidar_rays: int = 9
    lidar_range: float = 3.0      # by day
    night_lidar_range: float = 1.2
    scent_scale: float = 12.0     # distance at which scent fades to ~37%


@dataclass(frozen=True)
class Life:
    energy_decay: float = 1 / 240     # per simulated second at rest
    effort_cost: float = 1 / 900      # extra per second at full effort on every motor
    meal_energy: float = 0.35
    exhausted_strength: float = 0.75  # motor strength when energy hits zero
    nursing_minutes: float = 30.0     # hunger ramps in over this much simulated time
    food_min_dist: float = 6.0
    food_max_dist: float = 15.0
    eat_reach: float = 0.65
    rescue_seconds: float = 8.0       # flipped or lying on its torso this long -> the world rights it
    pit_seconds: float = 90.0         # stuck in a pit this long -> the world lifts it out
    day_minutes: float = 12.0         # one day and night, simulated minutes
    night_share: float = 0.35
    gifts_max: int = 3                # food dropped by visitors lying around at once


# Balanced so that trying to move pays: with pain at 0.5 and approach at 3, every creature learned
# that a fall costs far more than a few metres earn, and stood still for life (a braced stance,
# exploration collapsed). See README, "What to expect".
@dataclass(frozen=True)
class Reward:
    meal: float = 10.0
    approach: float = 10.0        # per metre closer to the food (scent shaping)
    hunger: float = 0.03          # per step, scaled by (1 - energy)^2
    pain: float = 0.05            # per step while torso scrapes the ground
    effort: float = 0.0005        # per step, times sum(a^2), per motor
    curiosity: float = 0.1        # times normalized novelty


@dataclass(frozen=True)
class Brain:
    hidden: int = 256
    lr: float = 3e-4
    gamma: float = 0.99
    tau: float = 0.005
    batch: int = 256
    replay_capacity: int = 500_000
    babbling_steps: int = 5_000   # random motor babbling before the policy takes over
    max_utd: float = 2.0          # learner never runs further ahead than this many updates per step
    min_utd: float = 0.5          # the body waits for the mind if learning falls behind this
    rnd_dim: int = 64
    threads: int = 4


PHYS = Physics()
BODY = Body()
LAND = Land()
SENSES = Senses()
LIFE = Life()
REWARD = Reward()
BRAIN = Brain()
# For a small server that lives in real time on one shared CPU core.
SMALL_BRAIN = Brain(hidden=128, batch=128, replay_capacity=300_000, max_utd=1.0, min_utd=0.5, threads=1)
