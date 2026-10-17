#!/usr/bin/env python3
"""Staged load test for a running Campus LMS stack (PRD sections 14.4, 15.2 and 15.3).

Simulates N students who sign in, browse, authorize a lesson and then stream it the
way the Android player does: an open-ended Range request per playback segment, read
at the video's own bitrate (a sustained load, not a download race), a seek now and
then, and a progress save every 20 s. Standard library only.

    python3 deploy/scripts/load_test.py --base-url http://192.168.10.10 --clients 10 --duration 120

Accounts: create them once (password in LMS_LOAD_PASSWORD for the run):

    printf '%s\\n' "$PW" | deploy/scripts/lms-admin.sh create-load-students --count 100 --class "Class 12" --password-stdin
    deploy/scripts/lms-admin.sh delete-load-students      # afterwards

Nginx limits logins to 10/min (+5 burst) per source address, so from one load host the
sign-in phase takes about (clients - 15) x 6 s; the harness retries 429s. Each client
streams for --duration seconds after its own sign-in.

This exercises the server, its NIC and the switch. It does NOT validate Wi-Fi capacity;
run the same stages with physical tablets too. Exit code 1 if any 5xx occurred.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from urllib.parse import urlsplit

CHUNK = 256 * 1024          # bytes per read, like a player's buffer fill
BUFFER_AHEAD = 30.0         # seconds of media the simulated player keeps buffered
PROGRESS_EVERY = 20.0       # seconds, as the app does
MAX_RETRIES = 40


class Metrics:
    """Shared, lock-protected counters."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latency: dict[str, list[float]] = defaultdict(list)
        self.statuses: Counter[str] = Counter()
        self.bytes = 0
        self.rebuffers = 0
        self.seeks = 0
        self.completions = 0
        self.service_busy = 0
        self.rate_limited = 0
        self.errors: list[str] = []
        self.clients_streaming = 0
        self.bitrates: dict[str, float] = {}  # media bitrate of the lesson each client streams

    def timed(self, key: str, seconds: float) -> None:
        with self.lock:
            self.latency[key].append(seconds)

    def status(self, key: str, code: int) -> None:
        with self.lock:
            self.statuses[f"{key} {code}"] += 1

    def add_bytes(self, n: int) -> None:
        with self.lock:
            self.bytes += n

    def count(self, field: str, n: int = 1) -> None:
        with self.lock:
            setattr(self, field, getattr(self, field) + n)

    def error(self, message: str) -> None:
        with self.lock:
            self.errors.append(message)


class Stop(Exception):
    pass


class Client(threading.Thread):
    def __init__(self, index: int, cfg: argparse.Namespace, metrics: Metrics, password: str) -> None:
        super().__init__(name=f"client-{index:03d}", daemon=True)
        self.index = index
        self.cfg = cfg
        self.m = metrics
        self.username = f"{cfg.username_prefix}{index:03d}"
        self.password = password
        self.token: str | None = None
        self.deadline = 0.0
        self.rng = random.Random(index)

    # ----------------------------------------------------------------- API calls

    def api(self, method: str, path: str, body: dict | None = None, *, key: str, auth: bool = True):
        """JSON request through Nginx with retries on 429 and 503 service_busy."""
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(self.cfg.base_url + path, data=data, method=method)
            if data is not None:
                req.add_header("Content-Type", "application/json")
            if auth and self.token:
                req.add_header("Authorization", f"Bearer {self.token}")
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = resp.read()
                    status = resp.status
                    headers = resp.headers
            except urllib.error.HTTPError as err:
                payload = err.read()
                status = err.code
                headers = err.headers
            except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
                self.m.status(key, 0)
                self.m.error(f"{self.username} {key}: {err}")
                time.sleep(2)
                continue
            elapsed = time.perf_counter() - started
            self.m.status(key, status)
            if status == 429:
                self.m.count("rate_limited")
                time.sleep(float(headers.get("Retry-After") or 6) + self.rng.uniform(0, 1.5))
                continue
            if status == 503:
                self.m.count("service_busy")
                time.sleep(float(headers.get("Retry-After") or 2) + self.rng.uniform(0, 0.5))
                continue
            self.m.timed(key, elapsed)
            if status >= 400:
                self.m.error(f"{self.username} {key}: HTTP {status} {payload[:120]!r}")
                raise Stop()
            return json.loads(payload) if payload else None
        self.m.error(f"{self.username} {key}: gave up after {MAX_RETRIES} attempts")
        raise Stop()

    def head(self, url: str) -> int:
        req = urllib.request.Request(url, method="HEAD")
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.m.timed("media HEAD", time.perf_counter() - started)
            self.m.status("media HEAD", resp.status)
            return int(resp.headers["Content-Length"])

    # ----------------------------------------------------------------- flow

    def run(self) -> None:
        try:
            self._run()
        except Stop:
            pass
        except Exception as exc:  # noqa: BLE001 - a client's failure is a result, not a crash
            self.m.error(f"{self.username}: {type(exc).__name__}: {exc}")

    def _run(self) -> None:
        time.sleep(self.index * self.cfg.ramp)
        login = self.api("POST", "/api/v1/auth/login",
                         {"username": self.username, "password": self.password}, key="login", auth=False)
        self.token = login["access_token"]

        videos = []
        for subject in self.api("GET", "/api/v1/subjects", key="subjects"):
            for module in self.api("GET", f"/api/v1/subjects/{subject['id']}/modules", key="modules"):
                contents = self.api("GET", f"/api/v1/modules/{module['id']}/contents", key="contents")
                videos += [item for item in contents if item.get("type") == "video"]
        if not videos:
            self.m.error(f"{self.username}: no published lessons visible")
            return
        video = videos[self.index % len(videos)]

        self.deadline = time.monotonic() + self.cfg.duration
        self.m.count("clients_streaming")
        while time.monotonic() < self.deadline:
            self.watch(video)
        self.api("POST", "/api/v1/auth/logout", key="logout")

    def watch(self, video: dict) -> None:
        """One playback session: authorize, then stream with seeks until the deadline."""
        started = time.perf_counter()
        info = self.api("POST", f"/api/v1/contents/{video['id']}/open", key="playback")
        url = info["url"]
        size = self.head(url)
        duration = float(info.get("duration_seconds") or 0) or 600.0
        bitrate = size * 8 / duration  # bits per second of media
        with self.m.lock:
            self.m.bitrates[self.username] = bitrate
        parts = urlsplit(url)
        path = parts.path + ("?" + parts.query if parts.query else "")

        position = float(info.get("resume_position_seconds") or 0)
        if position > duration - 30:
            position = 0.0
        next_seek = time.monotonic() + self.rng.uniform(0.5, 1.5) * self.cfg.seek_every
        next_progress = time.monotonic() + PROGRESS_EVERY
        first_segment = True

        while time.monotonic() < self.deadline:
            offset = int(position * bitrate / 8)
            if offset >= size:
                self.api("PUT", f"/api/v1/contents/{video['id']}/progress",
                         {"position_seconds": int(duration), "duration_seconds": int(duration), "is_completed": True},
                         key="progress")
                self.m.count("completions")
                return  # watch() again: a new playback authorization, from the start

            conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=30)
            t0 = time.perf_counter()
            try:
                conn.request("GET", path, headers={"Range": f"bytes={offset}-", "User-Agent": "campus-lms-load-test"})
                resp = conn.getresponse()
                self.m.status("media GET", resp.status)
                if resp.status != 206:
                    self.m.error(f"{self.username}: media GET at {offset} -> HTTP {resp.status}")
                    conn.close()
                    time.sleep(2)
                    return
                play_clock = time.monotonic() - position  # wall time at which media time 0 played
                first_chunk = True
                while True:
                    chunk = resp.read(CHUNK)
                    if first_chunk:
                        ttfb = time.perf_counter() - t0
                        if first_segment:
                            self.m.timed("startup (authorize+first byte)", time.perf_counter() - started)
                            first_segment = False
                        else:
                            self.m.timed("seek first byte", ttfb)
                        first_chunk = False
                    if not chunk:
                        position = duration  # end of file
                        break
                    self.m.add_bytes(len(chunk))
                    offset += len(chunk)
                    buffered_until = offset * 8 / bitrate     # media time we hold
                    now_pos = time.monotonic() - play_clock   # media time being played
                    if buffered_until < now_pos:
                        # Data arrived later than it was needed: the real player would stall.
                        self.m.count("rebuffers")
                        play_clock = time.monotonic() - buffered_until
                        now_pos = buffered_until
                    position = now_pos
                    if time.monotonic() >= next_progress:
                        self.api("PUT", f"/api/v1/contents/{video['id']}/progress",
                                 {"position_seconds": int(position), "duration_seconds": int(duration)}, key="progress")
                        next_progress = time.monotonic() + PROGRESS_EVERY
                    if time.monotonic() >= self.deadline:
                        break
                    if time.monotonic() >= next_seek:
                        position = self.rng.uniform(0.1, 0.8) * duration
                        next_seek = time.monotonic() + self.rng.uniform(0.7, 1.3) * self.cfg.seek_every
                        self.m.count("seeks")
                        break  # reopen at the new offset
                    # The buffer is full: stop reading until playback catches up, as a player does
                    # (in short steps so the deadline and the progress timer are still honoured).
                    ahead = buffered_until - now_pos - BUFFER_AHEAD
                    while ahead > 0 and time.monotonic() < self.deadline:
                        step = min(ahead, 0.5)
                        time.sleep(step)
                        ahead -= step
            finally:
                conn.close()

        self.api("PUT", f"/api/v1/contents/{video['id']}/progress",
                 {"position_seconds": int(position), "duration_seconds": int(duration)}, key="progress")


# --------------------------------------------------------------------- reporting


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def docker_stats() -> str:
    if not shutil.which("docker"):
        return "docker not available on this host"
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}: CPU {{.CPUPerc}}, mem {{.MemUsage}}, net {{.NetIO}}"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return f"docker stats failed: {exc}"
    lines = [line for line in out.splitlines() if "campus-lms" in line]
    return "; ".join(lines) if lines else "no campus-lms containers on this host (run on the server to capture them)"


def ms(value: float) -> str:
    return "n/a" if value != value else f"{value * 1000:.0f} ms"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1")
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--duration", type=float, default=120, help="streaming seconds per client after its sign-in")
    parser.add_argument("--username-prefix", default="load", help="accounts <prefix>001.. (create-load-students)")
    parser.add_argument("--ramp", type=float, default=0.5, help="seconds between client starts")
    parser.add_argument("--seek-every", type=float, default=90, help="average seconds between seeks per client")
    parser.add_argument("--no-docker-stats", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="also write raw results as JSON")
    cfg = parser.parse_args()
    cfg.base_url = cfg.base_url.rstrip("/")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows consoles with a legacy code page
    password = os.environ.get("LMS_LOAD_PASSWORD")
    if not password:
        print("Set LMS_LOAD_PASSWORD to the load-test students' password.", file=sys.stderr)
        return 2

    started_at = datetime.now(UTC)
    metrics = Metrics()
    clients = [Client(i, cfg, metrics, password) for i in range(1, cfg.clients + 1)]
    print(f"Campus LMS load test: {cfg.clients} clients x {cfg.duration:.0f} s against {cfg.base_url}")
    wall_start = time.monotonic()
    for client in clients:
        client.start()

    stats_snapshot = "skipped"
    snapshot_taken = False
    while any(c.is_alive() for c in clients):
        time.sleep(5)
        with metrics.lock:
            streaming, received, errors = metrics.clients_streaming, metrics.bytes, len(metrics.errors)
        elapsed = time.monotonic() - wall_start
        print(f"  t+{elapsed:5.0f}s  streaming {streaming}/{cfg.clients}  {received / 1e6:8.1f} MB  errors {errors}", flush=True)
        if not snapshot_taken and not cfg.no_docker_stats and streaming == cfg.clients:
            stats_snapshot = docker_stats()
            snapshot_taken = True
    wall = time.monotonic() - wall_start

    lat = metrics.latency
    five_xx = sum(n for key, n in metrics.statuses.items() if key.split()[-1].startswith("5"))
    mbps = metrics.bytes * 8 / wall / 1e6
    sustained_mbps = sum(metrics.bitrates.values()) / 1e6
    print()
    print(f"## Load test - {started_at:%Y-%m-%d %H:%M} UTC")
    print()
    print("| Item | Value |")
    print("|---|---|")
    print(f"| Base URL | {cfg.base_url} |")
    print(f"| Clients / streaming seconds each | {cfg.clients} / {cfg.duration:.0f} |")
    print(f"| Wall time (incl. sign-in ramp) | {wall:.0f} s |")
    print(f"| Media received | {metrics.bytes / 1e6:.0f} MB ({mbps:.1f} Mbps averaged over the wall time) |")
    print(f"| Sustained rate with all clients playing | {sustained_mbps:.1f} Mbps "
          f"({sustained_mbps / max(len(metrics.bitrates), 1):.2f} Mbps per client; each also buffers {BUFFER_AHEAD:.0f} s ahead) |")
    print(f"| Startup (authorize + first byte) p50 / p95 | {ms(percentile(lat['startup (authorize+first byte)'], 50))} / {ms(percentile(lat['startup (authorize+first byte)'], 95))} |")
    print(f"| Seek first byte p50 / p95 | {ms(percentile(lat['seek first byte'], 50))} / {ms(percentile(lat['seek first byte'], 95))} (n={len(lat['seek first byte'])}) |")
    print(f"| Rebuffer events (data later than needed) | {metrics.rebuffers} |")
    print(f"| Seeks / lesson completions | {metrics.seeks} / {metrics.completions} |")
    print(f"| 429 rate-limited logins / 503 service_busy | {metrics.rate_limited} / {metrics.service_busy} |")
    print(f"| 5xx responses | {five_xx} |")
    print(f"| Client errors | {len(metrics.errors)} |")
    print(f"| Server containers at full load | {stats_snapshot} |")
    print()
    print("| API endpoint | n | p50 | p95 | max |")
    print("|---|---:|---:|---:|---:|")
    for key in ("login", "subjects", "modules", "contents", "playback", "media HEAD", "progress", "logout"):
        values = lat.get(key, [])
        if values:
            print(f"| {key} | {len(values)} | {ms(percentile(values, 50))} | {ms(percentile(values, 95))} | {ms(max(values))} |")
    print()
    print("Status codes: " + ", ".join(f"{k}: {v}" for k, v in sorted(metrics.statuses.items())))
    if metrics.errors:
        print("\nErrors (first 10):")
        for line in metrics.errors[:10]:
            print("  " + line)
    verdict = "PASS" if five_xx == 0 and not metrics.errors else "FAIL"
    print(f"\n{verdict}: {cfg.clients} clients, {five_xx} server errors, {len(metrics.errors)} client errors, "
          f"{metrics.rebuffers} rebuffers. Server-side only; Wi-Fi capacity is not validated by this test.")

    if cfg.json:
        with open(cfg.json, "w", encoding="utf-8") as fh:
            json.dump({
                "started_at": started_at.isoformat(), "config": vars(cfg), "wall_seconds": wall,
                "bytes": metrics.bytes, "mbps": mbps, "rebuffers": metrics.rebuffers, "seeks": metrics.seeks,
                "completions": metrics.completions, "rate_limited": metrics.rate_limited,
                "sustained_mbps": sustained_mbps,
                "service_busy": metrics.service_busy, "statuses": dict(metrics.statuses),
                "latency": {k: v for k, v in lat.items()}, "errors": metrics.errors, "docker_stats": stats_snapshot,
            }, fh, indent=1)
    return 0 if five_xx == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
