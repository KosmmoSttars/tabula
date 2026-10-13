"""All tunable constants in one place."""

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
    torso_size: tuple = (1.1, 0.28)
    torso_mass: float = 4.0
    thigh_len: float = 0.42
    shin_len: float = 0.42
    limb_width: float = 0.09
    limb_mass: float = 0.6
    foot_radius: float = 0.07
    hip_offset: float = 0.42      # hips sit this far from torso center (front / back)
    hip_limits: tuple = (-1.1, 1.1)
    knee_limits: tuple = (-2.2, 0.1)
    hip_torque: float = 36.0
    knee_torque: float = 30.0
    max_joint_speed: float = 6.0
    tone_stiffness: float = 20.0  # passive spring pulling every joint to neutral
    tone_damping: float = 1.5
    friction: float = 1.0


@dataclass(frozen=True)
class Senses:
    lidar_rays: int = 9
    lidar_range: float = 3.0
    scent_scale: float = 12.0     # distance at which scent fades to ~37%


@dataclass(frozen=True)
class Life:
    energy_decay: float = 1 / 240     # per simulated second at rest
    effort_cost: float = 1 / 900      # extra per second at full effort on every motor
    meal_energy: float = 0.35
    exhausted_strength: float = 0.5   # motor strength when energy hits zero
    nursing_minutes: float = 30.0     # hunger ramps in over this much simulated time
    food_min_dist: float = 6.0
    food_max_dist: float = 15.0
    eat_reach: float = 0.65
    rescue_seconds: float = 12.0      # flipped or lying on its torso this long -> the world rights it


@dataclass(frozen=True)
class Reward:
    meal: float = 10.0
    approach: float = 3.0         # per metre closer to the food (scent shaping)
    hunger: float = 0.03          # per step, scaled by (1 - energy)^2
    pain: float = 0.5             # per step while torso scrapes the ground
    effort: float = 0.0005        # per step, times sum(a^2)
    curiosity: float = 0.05       # times normalized novelty


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
SENSES = Senses()
LIFE = Life()
REWARD = Reward()
BRAIN = Brain()
