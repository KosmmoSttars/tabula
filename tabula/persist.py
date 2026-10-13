"""Saving and resuming a life. Closing the program is sleep, not death."""

import json
import random
from pathlib import Path

import torch

LIVES = Path(__file__).resolve().parent.parent / "lives"

SYLLABLES = ("ka", "lo", "mi", "ru", "te", "vo", "ze", "ni", "sa", "pu", "ri", "do")


def random_name() -> str:
    return "".join(random.choice(SYLLABLES) for _ in range(3)).capitalize()


def life_dir(name: str) -> Path:
    return LIVES / name


def latest_life() -> str | None:
    if not LIVES.exists():
        return None
    dirs = [d for d in LIVES.iterdir() if (d / "state.json").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: (d / "state.json").stat().st_mtime).name


def read_seed(name: str) -> int:
    state = json.loads((life_dir(name) / "state.json").read_text(encoding="utf-8"))
    return int(state["seed"])


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
    state = {"seed": world.seed, "world": world.snapshot(), "bio": bio.state()}
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
