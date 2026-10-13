"""The mind: soft actor-critic for acting, random network distillation for curiosity.

There are no episodes and no terminal states. The creature lives one continuous
life, so the critic learns a discounted value of an endless future.
"""

import threading
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import BRAIN, REWARD

LOG_STD_MIN, LOG_STD_MAX = -5.0, 2.0
LEARN_AFTER = BRAIN.batch * 4  # memories needed before learning starts


def mlp(inp: int, out: int, hidden: int = BRAIN.hidden, norm: bool = True) -> nn.Sequential:
    layers: list[nn.Module] = []
    for i, o in ((inp, hidden), (hidden, hidden)):
        layers.append(nn.Linear(i, o))
        if norm:
            layers.append(nn.LayerNorm(o))
        layers.append(nn.ReLU())
    layers.append(nn.Linear(hidden, out))
    return nn.Sequential(*layers)


class Normalizer:
    """Running mean / std of observations (parallel Welford)."""

    def __init__(self, dim: int):
        self.n = 0
        self.mean = np.zeros(dim, dtype=np.float64)
        self.m2 = np.zeros(dim, dtype=np.float64)

    def update(self, x: np.ndarray) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)

    @property
    def std(self) -> np.ndarray:
        if self.n < 2:
            return np.ones_like(self.mean)
        return np.sqrt(self.m2 / (self.n - 1)) + 1e-4

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        mean = torch.as_tensor(self.mean, dtype=torch.float32)
        std = torch.as_tensor(self.std, dtype=torch.float32)
        return ((x - mean) / std).clamp(-5.0, 5.0)

    def state(self) -> dict:
        return {"n": self.n, "mean": self.mean, "m2": self.m2}

    def load(self, s: dict) -> None:
        self.n, self.mean, self.m2 = s["n"], np.asarray(s["mean"]), np.asarray(s["m2"])


class Actor(nn.Module):
    def __init__(self, obs_dim: int, act_dim: int):
        super().__init__()
        self.net = mlp(obs_dim, 2 * act_dim)

    def forward(self, obs: torch.Tensor, deterministic: bool = False):
        mu, log_std = self.net(obs).chunk(2, dim=-1)
        log_std = log_std.clamp(LOG_STD_MIN, LOG_STD_MAX)
        if deterministic:
            return torch.tanh(mu), None
        dist = torch.distributions.Normal(mu, log_std.exp())
        u = dist.rsample()
        a = torch.tanh(u)
        logp = dist.log_prob(u).sum(-1) - (2 * (np.log(2) - u - F.softplus(-2 * u))).sum(-1)
        return a, logp


class TwinCritic(nn.Module):
    def __init__(self, obs_dim: int, act_dim: int):
        super().__init__()
        self.q1 = mlp(obs_dim + act_dim, 1)
        self.q2 = mlp(obs_dim + act_dim, 1)

    def forward(self, obs, act):
        x = torch.cat([obs, act], dim=-1)
        return self.q1(x).squeeze(-1), self.q2(x).squeeze(-1)


class Replay:
    """Lifelong memory. Ring buffer; the oldest memories fade first."""

    def __init__(self, obs_dim: int, act_dim: int, capacity: int):
        self.capacity = capacity
        self.obs = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.next_obs = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.act = np.zeros((capacity, act_dim), dtype=np.float32)
        self.rew = np.zeros(capacity, dtype=np.float32)
        self.ptr = 0
        self.size = 0

    def add(self, o, a, r, o2) -> None:
        i = self.ptr
        self.obs[i], self.act[i], self.rew[i], self.next_obs[i] = o, a, r, o2
        self.ptr = (i + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, n: int, rng: np.random.Generator):
        idx = rng.integers(0, self.size, size=n)
        return (torch.from_numpy(self.obs[idx]), torch.from_numpy(self.act[idx]),
                torch.from_numpy(self.rew[idx]), torch.from_numpy(self.next_obs[idx]))

    def save(self, path) -> None:
        n = self.size
        np.savez(path, obs=self.obs[:n], next_obs=self.next_obs[:n], act=self.act[:n],
                 rew=self.rew[:n], ptr=self.ptr)

    def load(self, path) -> None:
        d = np.load(path)
        n = min(len(d["rew"]), self.capacity)
        self.obs[:n], self.next_obs[:n] = d["obs"][:n], d["next_obs"][:n]
        self.act[:n], self.rew[:n] = d["act"][:n], d["rew"][:n]
        self.size = n
        self.ptr = int(d["ptr"]) % self.capacity


class Brain:
    def __init__(self, obs_dim: int, act_dim: int, seed: int = 0):
        torch.set_num_threads(BRAIN.threads)
        torch.manual_seed(seed)
        self.rng = np.random.default_rng(seed)
        self.act_dim = act_dim

        self.actor = Actor(obs_dim, act_dim)
        self.critic = TwinCritic(obs_dim, act_dim)
        self.critic_target = TwinCritic(obs_dim, act_dim)
        self.critic_target.load_state_dict(self.critic.state_dict())
        for p in self.critic_target.parameters():
            p.requires_grad_(False)
        self.log_alpha = torch.zeros(1, requires_grad=True)
        self.target_entropy = -float(act_dim)

        # Curiosity: a fixed random projection of the senses and a predictor that
        # chases it. What the predictor cannot yet predict is new to the creature.
        self.rnd_target = mlp(obs_dim, BRAIN.rnd_dim, hidden=128, norm=False)
        for p in self.rnd_target.parameters():
            p.requires_grad_(False)
        self.rnd_pred = mlp(obs_dim, BRAIN.rnd_dim, hidden=128, norm=False)
        self.novelty_mean = 1.0  # EMA of raw prediction error, for scale

        self.opt_actor = torch.optim.Adam(self.actor.parameters(), lr=BRAIN.lr, foreach=True)
        self.opt_critic = torch.optim.Adam(self.critic.parameters(), lr=BRAIN.lr, foreach=True)
        self.opt_alpha = torch.optim.Adam([self.log_alpha], lr=BRAIN.lr)
        self.opt_rnd = torch.optim.Adam(self.rnd_pred.parameters(), lr=BRAIN.lr, foreach=True)
        self.lock = threading.Lock()
        self._alive = False
        self._thread: threading.Thread | None = None

        self.norm = Normalizer(obs_dim)
        self.memory = Replay(obs_dim, act_dim, BRAIN.replay_capacity)
        self.steps = 0
        self.updates = 0
        self.babble = np.zeros(act_dim, dtype=np.float32)
        self.stats = {"critic_loss": 0.0, "actor_loss": 0.0, "alpha": 1.0, "entropy": 0.0}

    @property
    def babbling(self) -> bool:
        return self.steps < BRAIN.babbling_steps

    # ---------------------------------------------------------------- acting
    @torch.no_grad()
    def act(self, obs: np.ndarray):
        """Returns (action, mood, novelty). Mood is the critic's guess of the future."""
        o = self.norm(torch.from_numpy(obs).unsqueeze(0))
        if self.babbling:
            # Motor babbling: smooth random twitches, like an infant discovering limbs.
            self.babble = 0.85 * self.babble + 0.35 * self.rng.standard_normal(self.act_dim).astype(np.float32)
            a = torch.from_numpy(np.clip(self.babble, -1, 1)).unsqueeze(0)
        else:
            a, _ = self.actor(o)
        q1, q2 = self.critic(o, a)
        mood = float(torch.min(q1, q2))
        novelty = float(self._novelty(o)) / self.novelty_mean
        return a.squeeze(0).numpy(), mood, novelty

    def _novelty(self, o: torch.Tensor) -> torch.Tensor:
        return (self.rnd_pred(o) - self.rnd_target(o)).pow(2).mean(-1)

    # ---------------------------------------------------------------- learning
    def remember(self, o, a, r, o2) -> None:
        self.norm.update(o2.astype(np.float64))
        self.memory.add(o, a, r, o2)
        self.steps += 1

    # The mind learns on its own thread while the body keeps living. The update
    # ratio is kept between min_utd and max_utd updates per lived step.
    @property
    def _learnable_steps(self) -> int:
        return max(self.steps - LEARN_AFTER, 0)

    @property
    def behind(self) -> bool:
        return self._alive and self.updates < self._learnable_steps * BRAIN.min_utd

    def start(self) -> None:
        self._alive = True
        self._thread = threading.Thread(target=self._learn_loop, name="learner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._alive = False
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _learn_loop(self) -> None:
        while self._alive:
            if self.memory.size < LEARN_AFTER or self.updates >= self._learnable_steps * BRAIN.max_utd:
                time.sleep(0.002)
                continue
            with self.lock:
                self._update()

    def _update(self) -> None:
        obs, act, rew, nxt = self.memory.sample(BRAIN.batch, self.rng)
        obs, nxt = self.norm(obs), self.norm(nxt)
        alpha = self.log_alpha.exp().detach()

        # Curiosity reward is recomputed fresh: what was novel yesterday is boring today.
        nov = self._novelty(nxt)
        self.novelty_mean = 0.99 * self.novelty_mean + 0.01 * float(nov.detach().mean())
        intrinsic = (nov.detach() / self.novelty_mean).clamp(0, 5.0)
        reward = rew + REWARD.curiosity * intrinsic

        with torch.no_grad():
            a2, logp2 = self.actor(nxt)
            tq1, tq2 = self.critic_target(nxt, a2)
            target = reward + BRAIN.gamma * (torch.min(tq1, tq2) - alpha * logp2)
        q1, q2 = self.critic(obs, act)
        critic_loss = F.mse_loss(q1, target) + F.mse_loss(q2, target)
        self.opt_critic.zero_grad(set_to_none=True)
        critic_loss.backward()
        nn.utils.clip_grad_norm_(self.critic.parameters(), 10.0)
        self.opt_critic.step()

        a, logp = self.actor(obs)
        q1, q2 = self.critic(obs, a)
        actor_loss = (alpha * logp - torch.min(q1, q2)).mean()
        self.opt_actor.zero_grad(set_to_none=True)
        actor_loss.backward()
        nn.utils.clip_grad_norm_(self.actor.parameters(), 10.0)
        self.opt_actor.step()

        alpha_loss = -(self.log_alpha * (logp.detach() + self.target_entropy)).mean()
        self.opt_alpha.zero_grad(set_to_none=True)
        alpha_loss.backward()
        self.opt_alpha.step()

        rnd_loss = nov.mean()
        self.opt_rnd.zero_grad(set_to_none=True)
        rnd_loss.backward()
        self.opt_rnd.step()

        with torch.no_grad():
            for p, tp in zip(self.critic.parameters(), self.critic_target.parameters()):
                tp.mul_(1 - BRAIN.tau).add_(p, alpha=BRAIN.tau)

        self.updates += 1
        if self.updates % 50 == 0:
            self.stats = {
                "critic_loss": critic_loss.item(),
                "actor_loss": actor_loss.item(),
                "alpha": float(alpha),
                "entropy": -logp.mean().item(),
            }

    # ---------------------------------------------------------------- persistence
    def state_dict(self) -> dict:
        return {
            "actor": self.actor.state_dict(),
            "critic": self.critic.state_dict(),
            "critic_target": self.critic_target.state_dict(),
            "log_alpha": self.log_alpha.detach(),
            "rnd_target": self.rnd_target.state_dict(),
            "rnd_pred": self.rnd_pred.state_dict(),
            "novelty_mean": self.novelty_mean,
            "opt_actor": self.opt_actor.state_dict(),
            "opt_critic": self.opt_critic.state_dict(),
            "opt_alpha": self.opt_alpha.state_dict(),
            "opt_rnd": self.opt_rnd.state_dict(),
            "norm": self.norm.state(),
            "steps": self.steps,
            "updates": self.updates,
            "rng": self.rng.bit_generator.state,
            "babble": self.babble,
        }

    def load_state_dict(self, s: dict) -> None:
        self.actor.load_state_dict(s["actor"])
        self.critic.load_state_dict(s["critic"])
        self.critic_target.load_state_dict(s["critic_target"])
        with torch.no_grad():
            self.log_alpha.copy_(s["log_alpha"])
        self.rnd_target.load_state_dict(s["rnd_target"])
        self.rnd_pred.load_state_dict(s["rnd_pred"])
        self.novelty_mean = s["novelty_mean"]
        self.opt_actor.load_state_dict(s["opt_actor"])
        self.opt_critic.load_state_dict(s["opt_critic"])
        self.opt_alpha.load_state_dict(s["opt_alpha"])
        self.opt_rnd.load_state_dict(s["opt_rnd"])
        self.norm.load(s["norm"])
        self.steps, self.updates = s["steps"], s["updates"]
        self.rng.bit_generator.state = s["rng"]
        self.babble = np.asarray(s["babble"], dtype=np.float32)
