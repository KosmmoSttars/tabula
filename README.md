# Tabula

A creature with a physical body and a blank mind. Leave it running and it figures out,
on its own, how to move, find food and stay alive.

There is no training run, no episodes and no resets. It is born once and lives one
continuous life. Closing the program puts it to sleep; starting it again wakes it up
exactly where it was, with everything it has learned.

## What it is

**Body.** A 2D physics body (pymunk): a torso on a back leg and a front leg, each with
a hip and a knee motor. Joints have passive muscle tone, so an idle body stands
instead of folding. Gravity, friction and falls are real; nothing is animated.

**Senses** (33 numbers per tick):
- proprioception: joint angles and speeds, torso tilt, spin and velocity
- touch: each foot, and the torso scraping the ground
- vision: a fan of 9 rays measuring the terrain around it
- smell: direction and strength of the nearest food
- interoception: its own energy level
- efference copy: what it just told its muscles to do

**Drives.** Energy drains with time and effort and comes back by eating. Hunger ramps
in slowly over the first 30 simulated minutes, so a newborn is not punished for being
helpless. Scraping the torso hurts. Food smells better the closer it gets.

**Mind.** Soft actor-critic (twin LayerNorm critics, automatic entropy tuning) learning
online from a 500k-step lifelong memory, plus curiosity from random network distillation:
states it cannot yet predict feel rewarding, and that reward fades as they become familiar.
The first 5,000 steps are motor babbling (smooth random twitching), the way infants
discover their limbs. Learning runs on its own thread while the body keeps living.

**World.** Endless procedural hills, flat around the birthplace and rougher further out.
Food appears 6–15 m away, more often ahead than behind. If it ends up stuck on its back
or lying on its torso for 12 s, the world sets it upright again (logged as a rescue).

## Run

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
| `run.py --life Kaloru` | Wake a specific creature |
| `run.py --headless` | No window, as fast as the mind can learn (Ctrl+C to sleep) |

Window keys: `1` real time, `2` fast, `3` turbo, `Space` pause, `V` show senses,
`S` save, `Esc` sleep (save and quit).

## What to expect

It learns at roughly 100 steps per second on a laptop CPU (about 3–4x real time).
Stages, judged from how far it actually travels over the last 30 simulated seconds:

`babbling` → `flailing` → `crawling` → `walking` → `running`

Milestones (first meal, distance from birthplace, new stages, age) are shown in the
window and appended to `lives/<name>/life.log`.

## Files

```
run.py              entry point
tabula/config.py    every tunable number
tabula/world.py     terrain, body, senses, energy, reward
tabula/brain.py     SAC + curiosity, learner thread, lifelong memory
tabula/life.py      biography: stages, milestones, per-minute history
tabula/being.py     body + mind + biography stepping together, autosave
tabula/persist.py   sleep and wake
tabula/view.py      live window and dashboard
lives/<name>/       brain.pt, memory.npz, state.json, life.log
```

The brain is saved every 10 minutes and the full memory every 30 minutes, and both on exit.
