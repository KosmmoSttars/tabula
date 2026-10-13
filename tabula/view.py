"""Live window: the world on the left, the creature's inner life on the right."""

import math
import time

import pygame
import pymunk

from .config import PHYS
from .life import STAGES, fmt_age

W, H = 1280, 720
PANEL = 420
VIEW_W = W - PANEL
PPM = 95.0  # pixels per metre

NIGHT_SKY = ((6, 8, 18), (16, 20, 36))
C = {
    "sky_top": (24, 30, 48), "sky_bot": (58, 66, 92),
    "ground": (46, 52, 44), "ground_edge": (120, 140, 96),
    "torso": (232, 176, 98), "limb": (196, 132, 74), "limb_dark": (150, 98, 60),
    "foot_on": (250, 230, 140), "foot_off": (120, 84, 54),
    "food": (120, 230, 140), "gift": (255, 150, 210), "lidar": (110, 160, 220),
    "panel": (18, 20, 26), "text": (220, 224, 232), "dim": (120, 126, 140),
    "accent": (255, 196, 92), "good": (120, 220, 140), "bad": (236, 100, 96),
    "blue": (110, 170, 255), "violet": (186, 140, 255), "grid": (40, 44, 56),
}
STAGE_COLORS = {
    "babbling": (160, 160, 180), "flailing": (236, 120, 100), "crawling": (240, 190, 90),
    "walking": (140, 220, 120), "running": (110, 200, 255),
}
MODES = {1: ("real time", None), 2: ("fast", 1 / 30), 3: ("turbo", 0.25)}


class View:
    def __init__(self, being):
        pygame.init()
        pygame.display.set_caption(f"Tabula - {being.name} the {being.world.plan.title.lower()}")
        self.screen = pygame.display.set_mode((W, H))
        self.being = being
        self.font = pygame.font.SysFont("consolas", 14)
        self.small = pygame.font.SysFont("consolas", 12)
        self.big = pygame.font.SysFont("consolas", 26, bold=True)
        self.day_sky = self._gradient(VIEW_W, H, C["sky_top"], C["sky_bot"])
        self.night_sky = self._gradient(VIEW_W, H, *NIGHT_SKY)
        self.cam = pygame.Vector2(being.world.body.torso.position.x, being.world.body.torso.position.y)
        self.mode = 1
        self.paused = False
        self.show_senses = True
        self.mood_lo, self.mood_hi = -1.0, 1.0
        self._sps_t, self._sps_n, self.sps = time.monotonic(), 0, 0.0
        self.clock = pygame.time.Clock()

    @staticmethod
    def _gradient(w, h, top, bot):
        s = pygame.Surface((w, h))
        for y in range(h):
            t = y / h
            s.fill([int(a + (b - a) * t) for a, b in zip(top, bot)], (0, y, w, 1))
        return s

    # ---------------------------------------------------------------- main loop
    def run(self) -> None:
        b = self.being
        acc = 0.0
        last = time.monotonic()
        running = True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        running = False
                    elif e.key == pygame.K_SPACE:
                        self.paused = not self.paused
                    elif e.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                        self.mode = e.key - pygame.K_0
                    elif e.key == pygame.K_s:
                        b.save()
                    elif e.key == pygame.K_v:
                        self.show_senses = not self.show_senses
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and e.pos[0] < VIEW_W:
                    # drop food where you click: you are a visitor too
                    x = self.cam.x + (e.pos[0] - VIEW_W / 2) / PPM
                    b.world.gift(x - b.world.body.torso.position.x, "you")

            now = time.monotonic()
            frame_dt, last = min(now - last, 0.1), now
            if not self.paused:
                budget = MODES[self.mode][1]
                if budget is None:
                    acc += frame_dt * PHYS.control_hz
                    while acc >= 1:
                        b.tick()
                        self._sps_n += 1
                        acc -= 1
                else:
                    end = time.monotonic() + budget
                    while time.monotonic() < end:
                        b.tick()
                        self._sps_n += 1
            if now - self._sps_t > 1.0:
                self.sps = self._sps_n / (now - self._sps_t)
                self._sps_t, self._sps_n = now, 0

            self.draw()
            pygame.display.flip()
            self.clock.tick(60 if self.mode == 1 or self.paused else 0)

        b.sleep()
        pygame.quit()

    # ---------------------------------------------------------------- world view
    def to_screen(self, p) -> tuple[int, int]:
        return (int(VIEW_W / 2 + (p[0] - self.cam.x) * PPM),
                int(H * 0.58 - (p[1] - self.cam.y) * PPM))

    def draw(self) -> None:
        w = self.being.world
        t = w.body.torso.position
        k = 0.12 if self.mode == 1 else 0.5
        self.cam.x += (t.x - self.cam.x) * k
        self.cam.y += (t.y - self.cam.y) * k

        s = self.screen
        s.blit(self.day_sky, (0, 0))
        dark = int(255 * (1.0 - w.daylight))
        if dark:
            self.night_sky.set_alpha(dark)
            s.blit(self.night_sky, (0, 0))
        half = VIEW_W / 2 / PPM + 1
        x0, x1 = self.cam.x - half, self.cam.x + half

        # Distance ticks and the birthplace marker.
        for m in range(int(math.floor(x0)), int(math.ceil(x1)) + 1):
            if m % 5:
                continue
            sx, sy = self.to_screen((m, w.terrain.height(m)))
            pygame.draw.line(s, C["grid"], (sx, 0), (sx, sy), 1)
            if m == 0:
                pygame.draw.line(s, C["accent"], (sx, sy), (sx, sy - 70), 2)
                pygame.draw.polygon(s, C["accent"], [(sx, sy - 70), (sx + 22, sy - 62), (sx, sy - 54)])
            lbl = self.small.render(f"{m} m", True, C["dim"])
            s.blit(lbl, (sx + 3, 4))

        prof = w.terrain.profile(x0, x1, 0.25)
        pts = [self.to_screen(p) for p in prof]
        pygame.draw.polygon(s, C["ground"], pts + [(pts[-1][0], H), (pts[0][0], H)])
        pygame.draw.lines(s, C["ground_edge"], False, pts, 3)

        # Food: the world's own is green, gifts from visitors are pink.
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4)
        for f in w.foods:
            fx, fy = self.to_screen((f.x, f.y))
            col = C["gift"] if f.gift else C["food"]
            if 0 <= fx <= VIEW_W:
                glow = tuple(int(c * 0.35) for c in col)
                pygame.draw.circle(s, glow, (fx, fy), int(16 + 6 * pulse))
                pygame.draw.circle(s, col, (fx, fy), 9)
            elif f is w.food:
                self._edge_arrow(fx < 0, fy, abs(f.x - t.x))

        if self.show_senses:
            o = self.to_screen(t)
            for hit in w.lidar_hits:
                pygame.draw.line(s, C["lidar"], o, self.to_screen(hit), 1)
                pygame.draw.circle(s, C["lidar"], self.to_screen(hit), 2)

        self._draw_creature()
        self._draw_panel()

    def _edge_arrow(self, left: bool, fy: int, dist: float) -> None:
        y = max(40, min(H - 40, fy))
        x = 18 if left else VIEW_W - 18
        d = -1 if left else 1
        col = C["gift"] if self.being.world.food.gift else C["food"]
        pygame.draw.polygon(self.screen, col, [(x + d * 10, y), (x - d * 8, y - 10), (x - d * 8, y + 10)])
        lbl = self.small.render(f"{dist:.1f} m", True, col)
        self.screen.blit(lbl, (x - (0 if left else lbl.get_width()) + (-4 * d), y + 14))

    def _poly(self, shape: pymunk.Poly, color, outline=None) -> None:
        body = shape.body
        pts = [self.to_screen(body.local_to_world(v)) for v in shape.get_vertices()]
        pygame.draw.polygon(self.screen, color, pts)
        if outline:
            pygame.draw.polygon(self.screen, outline, pts, 2)

    def _draw_leg(self, i: int, behind: bool) -> None:
        w = self.being.world
        body = w.body
        for sh in body.shapes:
            if sh.body in (body.thighs[i], body.shins[i]) and isinstance(sh, pymunk.Poly):
                self._poly(sh, C["limb_dark"] if behind else C["limb"])
        foot = body.feet[i]
        p = self.to_screen(foot.body.local_to_world(foot.offset))
        col = C["foot_on"] if w.contacts[i] else C["foot_off"]
        if behind:
            col = tuple(int(c * 0.7) for c in col)
        pygame.draw.circle(self.screen, col, p, max(3, int(foot.radius * PPM)))

    def _draw_creature(self) -> None:
        w = self.being.world
        body, plan = w.body, w.plan
        s = self.screen
        # Far legs go behind the torso; the strider's back leg is drawn darker as before.
        behind = [leg.far or (len(plan.legs) == 2 and i == 0) for i, leg in enumerate(plan.legs)]
        for i in range(len(plan.legs)):
            if behind[i]:
                self._draw_leg(i, True)
        self._poly(body.torso_shape, C["torso"], C["limb_dark"] if not w.contacts[-1] else C["bad"])
        for i in range(len(plan.legs)):
            if not behind[i]:
                self._draw_leg(i, False)

        # An eye at the front of the torso that looks toward the food.
        t = body.torso
        eye_w = t.local_to_world((plan.eye_x, 0.03))
        ex, ey = self.to_screen(eye_w)
        r = 9
        pygame.draw.circle(s, (250, 250, 245), (ex, ey), r)
        dx, dy = w.food.x - eye_w.x, w.food.y - eye_w.y
        dn = math.hypot(dx, dy) + 1e-6
        pygame.draw.circle(s, (30, 30, 40), (int(ex + dx / dn * 4), int(ey - dy / dn * 4)), 4)
        if w.energy <= 0.0:  # exhausted: eyelid drooped
            pygame.draw.rect(s, C["torso"], (ex - r, ey - r, 2 * r, r + 1))

    # ---------------------------------------------------------------- panel
    def _text(self, txt, pos, color=None, font=None):
        surf = (font or self.font).render(txt, True, color or C["text"])
        self.screen.blit(surf, pos)
        return surf.get_height()

    def _bar(self, x, y, w, label, value, color, txt=None):
        self._text(label, (x, y), C["dim"])
        bx = x + 92
        pygame.draw.rect(self.screen, C["grid"], (bx, y + 2, w - 92, 12), border_radius=3)
        fill = max(0.0, min(1.0, value))
        pygame.draw.rect(self.screen, color, (bx, y + 2, int((w - 92) * fill), 12), border_radius=3)
        if txt:
            self._text(txt, (bx + w - 92 + 6, y), C["dim"], self.small)

    def _chart(self, x, y, w, h, series, color, label, lo=None, hi=None):
        pygame.draw.rect(self.screen, (24, 27, 35), (x, y, w, h), border_radius=4)
        self._text(label, (x + 6, y + 3), C["dim"], self.small)
        if len(series) < 2:
            return
        lo = min(series) if lo is None else lo
        hi = max(series) if hi is None else hi
        if hi - lo < 1e-6:
            hi = lo + 1
        n = len(series)
        pts = [(x + 4 + i * (w - 8) / (n - 1), y + h - 4 - (v - lo) / (hi - lo) * (h - 20)) for i, v in enumerate(series)]
        pygame.draw.lines(self.screen, color, False, pts, 2)
        self._text(f"{series[-1]:.2f}", (x + w - 46, y + 3), color, self.small)

    def _draw_panel(self) -> None:
        b = self.being
        w, br, bio = b.world, b.brain, b.bio
        s = self.screen
        x0 = VIEW_W
        pygame.draw.rect(s, C["panel"], (x0, 0, PANEL, H))
        x, y, pw = x0 + 18, 14, PANEL - 36

        self._text(b.name, (x, y), C["accent"], self.big)
        self._text(w.plan.title.lower(), (x + 12 + self.big.size(b.name)[0], y + 9), C["dim"])
        self._text(f"age {fmt_age(w.age)}", (x + pw - 150, y + 8), C["dim"])
        y += 36
        col = STAGE_COLORS[bio.stage]
        self._text(bio.stage.upper(), (x, y), col, self.big)
        sx = x + 170
        for i, st in enumerate(STAGES):
            reached = st == "babbling" or f"stage_{st}" in bio.achieved or st == bio.stage
            pygame.draw.circle(s, STAGE_COLORS[st] if reached else C["grid"], (sx + i * 22, y + 14), 7)
        y += 40

        # Inner state.
        self.mood_lo = min(self.mood_lo * 0.999 + b.mood * 0.001, b.mood)
        self.mood_hi = max(self.mood_hi * 0.999 + b.mood * 0.001, b.mood)
        mood01 = (b.mood - self.mood_lo) / (self.mood_hi - self.mood_lo + 1e-6)
        self._bar(x, y, pw - 50, "energy", w.energy, C["good"] if w.energy > 0.25 else C["bad"], f"{w.energy:.0%}")
        y += 20
        self._bar(x, y, pw - 50, "curiosity", b.novelty / 3, C["violet"], f"{b.novelty:.2f}")
        y += 20
        self._bar(x, y, pw - 50, "mood", mood01, C["blue"], f"{b.mood:+.1f}")
        y += 20
        pain = b.reward_parts.get("pain", 0.0) < 0
        self._bar(x, y, pw - 50, "pain", 1.0 if pain else 0.0, C["bad"])
        y += 26

        # Motor output.
        self._text("motors", (x, y), C["dim"])
        slot = (pw - 92) // len(b.action)
        half_w = max(6, (slot - 8) // 2)
        for i, u in enumerate(b.action):
            cx = x + 92 + i * slot
            pygame.draw.rect(s, C["grid"], (cx, y + 2, 2 * half_w, 12), border_radius=3)
            mid = cx + half_w
            pygame.draw.rect(s, C["accent"], (min(mid, mid + int(u * half_w)), y + 2, abs(int(u * half_w)), 12))
        y += 26

        stats = [
            ("meals", f"{bio.meals}"), ("walked", f"{bio.walked:.0f} m"),
            ("farthest", f"{bio.farthest:.1f} m"), ("speed", f"{bio.speed:.2f} m/s"),
            ("rescued", f"{bio.rescues + bio.lifted}"), ("food at", f"{w.food.x - w.body.torso.position.x:+.1f} m"),
        ]
        for i, (k, v) in enumerate(stats):
            cx = x + (i % 2) * (pw // 2)
            cy = y + (i // 2) * 18
            self._text(k, (cx, cy), C["dim"])
            self._text(v, (cx + 80, cy))
        y += 3 * 18 + 8

        trace = list(b.trace)
        self._chart(x, y, pw // 2 - 4, 70, [t[0] for t in trace], C["accent"], "reward (20 s)")
        self._chart(x + pw // 2 + 4, y, pw // 2 - 4, 70, [t[1] for t in trace], C["violet"], "novelty (20 s)", lo=0)
        y += 78
        hist = bio.history[-240:]
        self._chart(x, y, pw // 2 - 4, 70, [h["speed"] for h in hist], C["good"], "speed / min", lo=0)
        self._chart(x + pw // 2 + 4, y, pw // 2 - 4, 70, [h["meals"] for h in hist], C["food"], "meals / min", lo=0)
        y += 80

        # Brain.
        st = br.stats
        phase = f"babbling {br.steps}/{br.cfg.babbling_steps}" if br.babbling else "learning"
        self._text(f"brain  {phase}   updates {br.updates:,}", (x, y), C["dim"], self.small)
        y += 16
        self._text(f"alpha {st['alpha']:.3f}  entropy {st['entropy']:+.2f}  Q loss {st['critic_loss']:.3f}",
                   (x, y), C["dim"], self.small)
        y += 16
        rt = self.sps / PHYS.control_hz
        self._text(f"{self.sps:.0f} steps/s  ({rt:.1f}x real time)  memory {br.memory.size:,}", (x, y), C["dim"], self.small)
        y += 22

        self._text("life", (x, y), C["dim"])
        y += 18
        for age, text in list(bio.milestones)[-7:][::-1]:
            self._text(f"{fmt_age(age):>11}  {text}", (x, y), C["text"], self.small)
            y += 16

        mode = MODES[self.mode][0] + ("  PAUSED" if self.paused else "")
        self._text(f"[1/2/3] speed: {mode}   [space] pause", (x, H - 36), C["dim"], self.small)
        self._text("[v] senses  [s] save  [click] drop food  [esc] sleep", (x, H - 20), C["dim"], self.small)
