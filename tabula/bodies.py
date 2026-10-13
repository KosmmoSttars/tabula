"""Body plans. A creature is born with one and keeps it for life.

Every body is a torso with legs; each leg has a hip and a knee motor and a round foot. Legs on the far
side of the body share positions with near ones (it is a 2D world): they do not collide with each other
and are drawn behind the torso. The senses and the motor count follow from the plan, so each body plan
grows its own mind and finds its own gait.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Leg:
    name: str
    hip_x: float          # along the torso from its center, metres (+ is the front)
    far: bool = False     # on the far side of the body


@dataclass(frozen=True)
class BodyPlan:
    key: str
    title: str
    about: str
    legs: tuple[Leg, ...]
    torso_size: tuple[float, float]
    torso_mass: float
    thigh_len: float
    shin_len: float
    limb_width: float = 0.09
    limb_mass: float = 0.6
    foot_radius: float = 0.07
    hip_limits: tuple[float, float] = (-1.1, 1.1)
    knee_limits: tuple[float, float] = (-2.2, 0.1)
    hip_torque: float = 36.0
    knee_torque: float = 30.0
    eye_x: float = 0.38   # where the eye sits on the torso

    @property
    def joint_names(self) -> tuple[str, ...]:
        return tuple(f"{leg.name} {part}" for leg in self.legs for part in ("hip", "knee"))

    @property
    def joints(self) -> int:
        return 2 * len(self.legs)


STRIDER = BodyPlan(
    "strider", "Strider", "A long torso on a back leg and a front leg.",
    legs=(Leg("back", -0.42), Leg("front", 0.42)),
    torso_size=(1.1, 0.28), torso_mass=4.0, thigh_len=0.42, shin_len=0.42,
)

QUADRUPED = BodyPlan(
    "quadruped", "Quadruped", "Four legs, two on each side, shorter and weaker than the strider's.",
    legs=(Leg("back near", -0.45), Leg("back far", -0.45, far=True),
          Leg("front near", 0.45), Leg("front far", 0.45, far=True)),
    torso_size=(1.2, 0.26), torso_mass=4.5, thigh_len=0.36, shin_len=0.36,
    hip_torque=26.0, knee_torque=22.0, eye_x=0.42,
)

HOPPER = BodyPlan(
    "hopper", "Hopper", "A short torso on one strong leg. It has to balance and hop.",
    legs=(Leg("leg", 0.0),),
    torso_size=(0.55, 0.3), torso_mass=3.0, thigh_len=0.45, shin_len=0.5, foot_radius=0.08,
    hip_limits=(-1.0, 1.0), knee_limits=(-2.4, 0.1), hip_torque=40.0, knee_torque=48.0, eye_x=0.16,
)

PLANS = {p.key: p for p in (STRIDER, QUADRUPED, HOPPER)}
DEFAULT = STRIDER.key
