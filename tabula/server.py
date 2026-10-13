"""Tabula online: one creature living in real time on a server, watched over HTTP.

    python -m tabula.server --life Ona --body strider --port 8790

The creature lives on its own thread at 30 decisions per simulated second, in step with the clock. Its
mind is the small single-threaded one (config.SMALL_BRAIN). The HTTP side only reads snapshots:

    GET  /state            who it is, its body plan, biography and history (JSON)
    GET  /stream           server-sent events, ten frames a second: pose, food, energy, light
    GET  /terrain?x0=&x1=  the ground line between two points (at most 200 m)
    POST /feed             {"side": -1 or 1}: drop food behind or ahead of it, once a minute per visitor

It is meant to sit behind nginx on 127.0.0.1, which passes the visitor's address in X-Real-IP.
SIGTERM or Ctrl+C puts the creature to sleep (saves everything) before the process ends.
"""

import argparse
import hashlib
import json
import math
import queue
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .being import Being
from .config import PHYS, SMALL_BRAIN
from .life import STAGES

FRAME_HZ = 10
FEED_COOLDOWN = 60.0       # seconds between gifts from one visitor
FEED_DISTANCE = (2.5, 5.0)  # metres from the creature
MAX_STREAMS = 300
HISTORY_POINTS = 720       # per-minute rows sent in /state (12 hours)


class Life:
    """The creature on its own thread, plus the latest frame and state for the web side."""

    def __init__(self, being: Being):
        self.being = being
        self.lock = threading.Lock()
        self.frame: dict = {}
        self.frame_no = 0
        self.frame_ready = threading.Condition()
        self.gifts: queue.Queue = queue.Queue()
        self.alive = True
        self.thread = threading.Thread(target=self._live, name="life", daemon=True)

    def start(self) -> None:
        self._publish()
        self.thread.start()

    def stop(self) -> None:
        self.alive = False
        self.thread.join(timeout=30)
        self.being.sleep()

    def _live(self) -> None:
        dt = 1.0 / PHYS.control_hz
        every = PHYS.control_hz // FRAME_HZ
        next_t = time.monotonic()
        n = 0
        while self.alive:
            while not self.gifts.empty():
                side, reply = self.gifts.get()
                d = FEED_DISTANCE[0] + (FEED_DISTANCE[1] - FEED_DISTANCE[0]) * (n % 7) / 6
                with self.lock:
                    reply.put(self.being.world.gift(side * d, "a visitor"))
            with self.lock:
                self.being.tick()
            n += 1
            if n % every == 0:
                self._publish()
            next_t += dt
            lag = next_t - time.monotonic()
            if lag > 0:
                time.sleep(lag)
            elif lag < -2.0:
                next_t = time.monotonic()   # fell behind (busy server): live on from now, do not race

    def _publish(self) -> None:
        b = self.being
        w = b.world
        parts = [[round(p.position.x, 3), round(p.position.y, 3), round(p.angle, 3)] for p in w.body.bodies]
        frame = {
            "age": round(w.age, 2),
            "parts": parts,
            "contacts": [int(c) for c in w.contacts],
            "foods": [[round(f.x, 2), round(f.y, 2), 1 if f.gift else 0] for f in w.foods],
            "target": [round(w.food.x, 2), round(w.food.y, 2)],
            "energy": round(w.energy, 3),
            "light": round(w.daylight, 3),
            "stage": b.bio.stage,
            "speed": round(b.bio.speed, 3),
            "meals": b.bio.meals,
            "x": round(w.body.torso.position.x, 2),
            "novelty": round(b.novelty, 3),
            "babbling": b.brain.babbling,
        }
        with self.frame_ready:
            self.frame = frame
            self.frame_no += 1
            self.frame_ready.notify_all()

    def state(self) -> dict:
        with self.lock:
            b = self.being
            w, bio, plan = b.world, b.bio, b.world.plan
            history = bio.history
            step = max(1, math.ceil(len(history) / HISTORY_POINTS))
            return {
                "name": b.name,
                "born": bio.born,
                "body": {
                    "key": plan.key, "title": plan.title, "about": plan.about,
                    "torso": plan.torso_size, "thigh": plan.thigh_len, "shin": plan.shin_len,
                    "limb": plan.limb_width, "foot": plan.foot_radius, "eye": plan.eye_x,
                    "legs": [{"x": leg.hip_x, "far": leg.far, "name": leg.name} for leg in plan.legs],
                },
                "stages": STAGES,
                "stage": bio.stage,
                "achieved": sorted(bio.achieved),
                "age": w.age,
                "meals": bio.meals, "gifts": bio.gifts, "walked": bio.walked, "farthest": bio.farthest,
                "rescues": bio.rescues + bio.lifted,
                "milestones": bio.milestones[-40:],
                "history": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in h.items()}
                            for h in history[::-1][::step][::-1]],
                "steps": b.brain.steps,
                "updates": b.brain.updates,
                "frame": self.frame,
            }

    def terrain(self, x0: float, x1: float) -> list:
        x1 = min(x1, x0 + 200.0)
        with self.lock:
            pts = self.being.world.terrain.points(x0, x1, 0.25)
        return [[round(x, 3), round(y, 3)] for x, y in pts]

    def feed(self, side: int) -> bool:
        reply: queue.Queue = queue.Queue()
        self.gifts.put((side, reply))
        try:
            return reply.get(timeout=5)
        except queue.Empty:
            return False


class Handler(BaseHTTPRequestHandler):
    life: Life
    fed: dict[str, float] = {}
    fed_lock = threading.Lock()
    streams = 0
    streams_lock = threading.Lock()
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args) -> None:   # nginx keeps the access log
        pass

    dev = False   # --dev: let a page on another local port call the API

    def send_response(self, code, message=None) -> None:
        super().send_response(code, message)
        if self.dev:
            self.send_header("Access-Control-Allow-Origin", "*")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code: int, body: dict | list, cache: str = "no-store") -> None:
        data = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _visitor(self) -> str:
        ip = self.headers.get("X-Real-IP") or self.client_address[0]
        return hashlib.sha256(ip.encode()).hexdigest()[:16]   # only a hash is kept, and only in memory

    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path.rstrip("/").rsplit("/api", 1)[-1] or "/"
        if path == "/state":
            self._send(200, self.life.state())
        elif path == "/terrain":
            q = parse_qs(url.query)
            try:
                x0, x1 = float(q["x0"][0]), float(q["x1"][0])
            except (KeyError, ValueError):
                self._send(400, {"error": "x0 and x1 needed"})
                return
            if not (math.isfinite(x0) and math.isfinite(x1)) or x1 <= x0:
                self._send(400, {"error": "bad range"})
                return
            self._send(200, self.life.terrain(x0, x1), cache="public, max-age=3600")
        elif path == "/stream":
            self._stream()
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/").rsplit("/api", 1)[-1]
        if path != "/feed":
            self._send(404, {"error": "not found"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 256)
            side = int(json.loads(self.rfile.read(length) or b"{}").get("side", 1))
        except (ValueError, AttributeError):
            self._send(400, {"error": "bad request"})
            return
        side = -1 if side < 0 else 1
        who, now = self._visitor(), time.monotonic()
        with self.fed_lock:
            last = self.fed.get(who, -1e9)
            if now - last < FEED_COOLDOWN:
                self._send(429, {"ok": False, "reason": "cooldown", "wait": round(FEED_COOLDOWN - (now - last))})
                return
            self.fed[who] = now
            if len(self.fed) > 10000:
                cutoff = now - FEED_COOLDOWN
                for k in [k for k, t in self.fed.items() if t < cutoff]:
                    del self.fed[k]
        if self.life.feed(side):
            self._send(200, {"ok": True, "wait": FEED_COOLDOWN})
        else:
            with self.fed_lock:
                self.fed.pop(who, None)
            self._send(200, {"ok": False, "reason": "full"})

    def _stream(self) -> None:
        with Handler.streams_lock:
            if Handler.streams >= MAX_STREAMS:
                self._send(503, {"error": "busy"})
                return
            Handler.streams += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            life = self.life
            seen = -1
            while life.alive:
                with life.frame_ready:
                    life.frame_ready.wait_for(lambda: life.frame_no != seen or not life.alive, timeout=15)
                    frame, seen = life.frame, life.frame_no
                self.wfile.write(b"data: " + json.dumps(frame, separators=(",", ":")).encode() + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with Handler.streams_lock:
                Handler.streams -= 1
            self.close_connection = True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--life", help="the creature's name (resumed if it exists)")
    ap.add_argument("--body", default="strider", help="body plan for a newborn")
    ap.add_argument("--seed", type=int, help="world seed for a newborn")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--dev", action="store_true", help="allow cross-origin calls (a local page on another port)")
    args = ap.parse_args()

    being = Being(args.life, seed=args.seed, body=args.body, brain_config=SMALL_BRAIN)
    print(("Woke " if being.resumed else "Born: ") + f"{being.name} the {being.world.plan.title.lower()}", flush=True)
    life = Life(being)
    Handler.life = life
    Handler.dev = args.dev
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    life.start()
    print(f"Listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        print("Going to sleep (saving)...", flush=True)
        life.stop()
        server.server_close()


if __name__ == "__main__":
    main()
