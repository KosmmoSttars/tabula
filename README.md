# Tabula

A creature with a physical body and a blank mind. Leave it running and it figures out,
on its own, how to move, find food and stay alive.

There is no training run, no episodes and no resets. It is born once and lives one
continuous life. Closing the program puts it to sleep; starting it again wakes it up
exactly where it was, with everything it has learned.

**One lives online, around the clock: [kosmo-stars.ru/tabula](https://kosmo-stars.ru/tabula/).**
Watch it and drop it some food.

## What it is

**Body.** A 2D physics body (pymunk) built from a body plan chosen at birth:

| Plan | Body | Motors |
|---|---|---|
| `strider` | a long torso on a back leg and a front leg | 4 |
| `quadruped` | four shorter, weaker legs, two on each side | 8 |
| `hopper` | a short torso on one strong leg: it has to balance and hop | 2 |

Every leg has a hip and a knee motor and a round foot. Joints have passive muscle tone,
so an idle body stands instead of folding. Gravity, friction and falls are real; nothing
is animated.

**Senses** (the count follows the body plan; 34 numbers for the strider):
- proprioception: joint angles and speeds, torso tilt, spin and velocity
- touch: each foot, and the torso scraping the ground
- vision: a fan of 9 rays measuring the land around it (shorter at night)
- smell: direction and strength of the nearest food
- interoception: its own energy level, and how light it is
- efference copy: what it just told its muscles to do

**Drives.** Energy drains with time and effort and comes back by eating. Hunger ramps
in slowly over the first 30 simulated minutes, so a newborn is not punished for being
helpless. Scraping the torso hurts. Food smells better the closer it gets.

**Mind.** Soft actor-critic (twin LayerNorm critics, automatic entropy tuning) learning
online from a lifelong memory, plus curiosity from random network distillation:
states it cannot yet predict feel rewarding, and that reward fades as they become familiar.
The first 5,000 steps are motor babbling (smooth random twitching), the way infants
discover their limbs. Learning runs on its own thread while the body keeps living.

**World.** Endless procedural land, flat around the birthplace and rougher further out:
hills, then pits, bumps and steps, more of them the further it goes. Day turns to night
every 12 simulated minutes. Food appears 6–15 m away, more often ahead than behind;
visitors can drop more. If it ends up stuck on its back or lying on its torso for 12 s,
the world sets it upright again; if it is stuck in a pit for 90 s, the world lifts it out
(both are logged).

## Run it yourself

```bash
python -m venv .venv
.venv\Scripts\pip install numpy pymunk pygame-ce
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```bash
.venv\Scripts\python run.py
```

| Command | What it does |
|---|---|
| `run.py` | Wake the most recent creature, or give birth to one |
| `run.py --new` | A new creature, new world |
| `run.py --new --body quadruped` | ...with another body plan (`strider`, `quadruped`, `hopper`) |
| `run.py --life Kaloru` | Wake a specific creature |
| `run.py --headless` | No window, as fast as the mind can learn (Ctrl+C to sleep) |
| `run.py --small-brain` | The online creature's smaller, single-threaded mind |

Window keys: `1` real time, `2` fast, `3` turbo, `Space` pause, `V` show senses,
`S` save, `Esc` sleep (save and quit). Click the land to drop food.

## What to expect

It learns at roughly 50–100 steps per second on a laptop CPU (2–3x real time).
Stages, judged from how far it actually travels over the last 30 simulated seconds:

`babbling` → `flailing` → `crawling` → `walking` → `running`

It takes a long time. Simple gaits need a few hundred thousand moments of experience,
which is hours; every body plan finds a different one, and not every creature finds one
quickly. Milestones (first meal, distance from birthplace, new stages, age, food from
strangers) are shown in the window and appended to `lives/<name>/life.log`.

## Online

`python -m tabula.server` keeps one creature alive in real time (30 decisions a
simulated second, in step with the clock) with the small mind, and serves it:

| Endpoint | |
|---|---|
| `GET /state` | name, body plan, biography, per-minute history |
| `GET /stream` | server-sent events, ten frames a second: pose, food, energy, light |
| `GET /terrain?x0=&x1=` | the ground line between two points |
| `POST /feed` | `{"side": -1 or 1}`: drop food behind or ahead of it, once a minute per visitor |

The page in `web/` draws it and blends the frames. On kosmo-stars.ru it runs as a
systemd service at the lowest CPU priority with a CPU and memory cap, behind nginx;
`deploy/server-setup.sh` sets that up and `deploy/deploy.ps1` ships the code and the page.

## Files

```
run.py              entry point
tabula/config.py    every tunable number
tabula/bodies.py    body plans
tabula/world.py     land, body, senses, energy, food, reward
tabula/brain.py     SAC + curiosity, learner thread, lifelong memory
tabula/life.py      biography: stages, milestones, per-minute history
tabula/being.py     body + mind + biography stepping together, autosave
tabula/persist.py   sleep and wake
tabula/view.py      live window and dashboard
tabula/server.py    the online creature over HTTP
web/                the live page
deploy/             server setup and deploy
lives/<name>/       brain.pt, memory.npz, state.json, life.log
```

The brain is saved every 10 minutes and the full memory every 30 minutes, and both on exit.

## License

MIT, see [LICENSE](LICENSE).
