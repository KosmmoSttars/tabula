"""Saving and resuming a life. Closing the program is sleep, not death."""

import dataclasses
import json
import os
import random
import sys
from pathlib import Path

import torch

# TABULA_LIVES moves the lives somewhere else (experiments, the server). The built app keeps them
# next to Tabula.exe.
_HOME = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
LIVES = Path(os.environ.get("TABULA_LIVES") or _HOME / "lives")

SYLLABLES = ("ka", "lo", "mi", "ru", "te", "vo", "ze", "ni", "sa", "pu", "ri", "do")


def random_name() -> str:
    return "".join(random.choice(SYLLABLES) for _ in range(3)).capitalize()


def life_dir(name: str) -> Path:
    return LIVES / name


def latest_life() -> str | None:
    if not LIVES.exists():
        return None
    dirs = [d for d in LIVES.iterdir() if (d / "state.json").exists() and compatible(d.name)]
    if not dirs:
        return None
    return max(dirs, key=lambda d: (d / "state.json").stat().st_mtime).name


def compatible(name: str) -> bool:
    """Lives from before body plans (no "body" in their state) had other senses and cannot wake up."""
    try:
        return "body" in json.loads((life_dir(name) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def read_birth(name: str) -> tuple[int, str, dict | None]:
    """The world seed, body plan and size of mind a creature was born with."""
    state = json.loads((life_dir(name) / "state.json").read_text(encoding="utf-8"))
    return int(state["seed"]), state.get("body", "strider"), state.get("mind")


def save(name: str, world, brain, bio, with_memory: bool = True) -> None:
    d = life_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "brain.pt.tmp"
    with brain.lock:
        torch.save(brain.state_dict(), tmp)
    tmp.replace(d / "brain.pt")
    if with_memory:
        brain.memory.save(d / "memory.tmp.npz")
        (d / "memory.tmp.npz").replace(d / "memory.npz")
    state = {"seed": world.seed, "body": world.plan.key, "mind": dataclasses.asdict(brain.cfg),
             "world": world.snapshot(), "bio": bio.state()}
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(d / "state.json")


def load(name: str, world, brain, bio) -> None:
    d = life_dir(name)
    state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    world.restore(state["world"])
    bio.load(state["bio"])
    brain.load_state_dict(torch.load(d / "brain.pt", weights_only=False))
    if (d / "memory.npz").exists():
        brain.memory.load(d / "memory.npz")
