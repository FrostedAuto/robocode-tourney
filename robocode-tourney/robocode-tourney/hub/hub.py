#!/usr/bin/env python3
"""robocode-hub: live arena, scoreboard and team uploads for the Tank Royale server.

Installed by /opt/robocode/setup.sh (step 11) as /opt/robocode/hub/hub.py and run by
robocode-hub.service as user robocode-hub. It:

  * connects to the server as a controller (CONTROLLER_SECRET from secrets.env), records every
    battle in $STATE_DIRECTORY/results/ and relays a cleaned-up live view to browsers;
  * serves the projector page (/) and the team page (/submit) on HUB_PORT (8080);
  * lets teams register (event code) and upload a bot with their team key. Uploads are checked,
    staged in incoming/ and queued for the root-only import worker (robocode-import.service),
    which runs import-bot.sh and starts the team's own sandboxed unit robocode-team@<Bot>;
  * offers an admin API on a unix socket ($RUNTIME_DIRECTORY/admin.sock), used by robo-admin.

Secrets never reach browsers: they get positions, names, scores and their own team status.
"""
import asyncio
import hashlib
import hmac
import io
import json
import logging
import math
import os
import random
import re
import secrets
import shutil
import stat
import time
import zipfile
from pathlib import Path

from aiohttp import ClientSession, WSMsgType, web

VERSION = "1.0"
SERVER_URL = os.environ.get("HUB_SERVER_URL", "ws://localhost:7654")
CONTROLLER_SECRET = os.environ.get("CONTROLLER_SECRET", "")
STATE = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/robocode-hub").split(":")[0])
RUN = Path(os.environ.get("RUNTIME_DIRECTORY", "/run/robocode-hub").split(":")[0])
PORT = int(os.environ.get("HUB_PORT", "8080"))
STATIC = Path(__file__).resolve().with_name("static")
SUBMISSIONS = Path("/opt/robocode/submissions")
DOWNLOADS = Path("/opt/robocode/downloads")   # root-owned; manifest.json lists what /downloads offers
SAMPLES = Path("/opt/robocode/bots/samples")

MAX_UPLOAD = 3 * 1024 * 1024          # request body
MAX_FILES = 60
MAX_FILE = 1024 * 1024                # one file, unpacked
MAX_TOTAL = 4 * 1024 * 1024           # whole bot, unpacked
ALLOWED_EXT = {".py", ".json", ".txt", ".md", ".csv", ".cfg", ".ini", ".yaml", ".yml"}
SKIP_PARTS = {"__pycache__", "__MACOSX", ".git", ".idea", ".vscode"}
BOT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,23}$")   # <= 24 chars: unit user rt-<Bot> must fit 31
CGROUP = Path("/sys/fs/cgroup/robocode.slice/robocode-bots.slice")
HANG_CPU = 0.4          # share of a core a bot may use while no battle runs (its cap is 0.5)
HANG_SECS = 15
TEAM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _'.\-]{1,23}$")
KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
FRAME_HZ = 30
WATCHDOG_SECS = 90

log = logging.getLogger("hub")


# ------------------------------------------------------------------ helpers
def now() -> float:
    return time.time()


def write_json(path: Path, data) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, path)


def norm_key(key: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (key or "").upper())


def key_hash(key: str) -> str:
    return hashlib.sha256(b"robocode-hub-key:" + norm_key(key).encode()).hexdigest()


def code_hash(code: str) -> str:
    return hashlib.sha256(b"robocode-hub-code:" + (code or "").strip().lower().encode()).hexdigest()


def new_key() -> str:
    raw = "".join(secrets.choice(KEY_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "team"


class Bucket:
    """Token bucket: `rate` events per `per` seconds (global, since every lab PC comes via one relay)."""

    def __init__(self, rate: int, per: float):
        self.rate, self.per, self.tokens, self.t = rate, per, float(rate), now()

    def take(self) -> bool:
        t = now()
        self.tokens = min(self.rate, self.tokens + (t - self.t) * self.rate / self.per)
        self.t = t
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Problem(Exception):
    """A user-facing error (shown to the team as-is)."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ------------------------------------------------------------------ state
DEFAULT_SETTINGS = {
    "title": "Robocode Tank Royale Tournament",
    "reg_open": False,
    "reg_code_hash": "",
    "max_teams": 16,
    "public_url": "",
    "uploads_open": True,
}


class Hub:
    def __init__(self):
        for d in ("results", "incoming", "queue", "status"):
            (STATE / d).mkdir(parents=True, exist_ok=True)
        self.state_file = STATE / "state.json"
        self.state = {"settings": dict(DEFAULT_SETTINGS), "teams": {}, "heats": [], "final": [], "excluded": []}
        if self.state_file.exists():
            loaded = json.loads(self.state_file.read_text())
            self.state.update(loaded)
            self.state["settings"] = {**DEFAULT_SETTINGS, **loaded.get("settings", {})}
        self.battles = self._load_battles()
        self.bots = []                  # BotListUpdate.bots
        self.game = None                # current game (dict)
        self.frame = None               # latest tick frame for browsers
        self.frame_seq = 0
        self.sent_seq = 0
        self.fx = []                    # effects since the last frame
        self.tps = None
        self.server_ok = False
        self.server_since = 0.0         # when the hub (re)connected to the server
        self.not_connected = {}         # team id -> first time seen with a bot but not connected
        self.left_out = []              # teams the last heat plan skipped
        self.cpu_seen = {}              # bot -> (time, cpu usage_usec, seconds busy while idle)
        self.game_ended_at = 0.0
        self.ws_server = None           # controller connection to the server
        self.clients = set()
        self.key_fail = Bucket(30, 60)
        self.reg_bucket = Bucket(20, 60)
        self.lock = asyncio.Lock()
        self.save()

    # -- persistence
    def save(self):
        write_json(self.state_file, self.state)

    def _load_battles(self):
        out = []
        for p in sorted((STATE / "results").glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                log.warning("skipping unreadable result %s", p)
        return out

    @property
    def settings(self):
        return self.state["settings"]

    @property
    def teams(self):
        return self.state["teams"]

    def team_by_key(self, key: str):
        h = key_hash(key)
        for tid, t in self.teams.items():
            if hmac.compare_digest(t["key_hash"], h):
                return tid, t
        return None, None

    def team_by_name(self, name: str):
        for tid, t in self.teams.items():
            if t["name"] == name:
                return tid
        return None

    def connected_names(self):
        return {b.get("name") for b in self.bots}

    # -- teams
    def add_team(self, name: str):
        name = " ".join((name or "").split())
        if not TEAM_RE.match(name):
            raise Problem("Team name: 2-24 characters, letters, digits, spaces, _ ' . -")
        if any(t["name"].lower() == name.lower() for t in self.teams.values()):
            raise Problem("That team name is taken.")
        if len(self.teams) >= int(self.settings["max_teams"]):
            raise Problem(f"The tournament is full ({self.settings['max_teams']} teams). Ask an officer.", 409)
        tid = base = slug(name)
        i = 2
        while tid in self.teams:
            tid, i = f"{base}-{i}", i + 1
        key = new_key()
        self.teams[tid] = {"name": name, "key_hash": key_hash(key), "bot": None, "created": now(),
                           "pending": None, "last_import": None}
        self.save()
        log.info("team added: %s (%s)", tid, name)
        return tid, key

    def remove_team(self, tid: str):
        t = self.teams.pop(tid, None)
        if not t:
            raise Problem("no such team", 404)
        for b in {t.get("bot"), (t.get("pending") or {}).get("bot")} - {None}:
            self.queue("remove", b)
        self.state["heats"] = [{**h, "teams": [x for x in h["teams"] if x != tid]} for h in self.state["heats"]]
        self.state["final"] = [x for x in self.state["final"] if x != tid]
        self.save()

    def rekey_team(self, tid: str):
        t = self.teams.get(tid)
        if not t:
            raise Problem("no such team", 404)
        key = new_key()
        t["key_hash"] = key_hash(key)
        self.save()
        return key

    # -- uploads
    def queue(self, action: str, bot: str):
        assert action in ("import", "remove", "stop", "start", "restartall") and BOT_RE.match(bot)
        (STATE / "queue" / f"{int(now() * 1000)}-{secrets.token_hex(3)}-{action}-{bot}.req").touch()

    def bot_owner(self, bot: str):
        for tid, t in self.teams.items():
            if bot in (t.get("bot"), (t.get("pending") or {}).get("bot")):
                return tid
        return None

    async def stage_upload(self, tid: str, files: dict):
        """files: relative path -> bytes. Validates, rewrites the .json and queues the import."""
        t = self.teams[tid]
        if not self.settings.get("uploads_open", True):
            raise Problem("Uploads are closed right now. Ask an officer.", 409)
        pend = t.get("pending")
        if pend and now() - pend["at"] < 60:
            raise Problem("Your last upload is still being checked. Wait a few seconds.", 409)
        files = clean_paths(files)
        bot, warnings = check_bot(files)
        owner = self.bot_owner(bot)
        if owner and owner != tid:
            raise Problem(f"Another team already uses the bot name '{bot}'. Rename your bot class "
                          f"and its .py/.json files.", 409)
        meta = json.loads(files[f"{bot}.json"].decode("utf-8-sig"))
        meta["name"] = t["name"]
        meta["version"] = str(meta.get("version") or "1.0")[:20]
        if not isinstance(meta.get("authors"), list) or not meta["authors"]:
            meta["authors"] = [t["name"]]
        meta["authors"] = [str(a)[:40] for a in meta["authors"][:8]]
        meta.pop("gameTypes", None)     # a stray list here would keep the bot out of classic battles
        files[f"{bot}.json"] = (json.dumps(meta, indent=2) + "\n").encode()

        incoming = STATE / "incoming"
        tmp = incoming / f".{bot}.{secrets.token_hex(4)}"
        tmp.mkdir()
        for rel, data in files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        dest = incoming / bot
        if dest.exists():
            shutil.rmtree(dest)
        os.rename(tmp, dest)
        t["pending"] = {"bot": bot, "at": now(), "old_bot": t.get("bot")}
        self.save()
        self.queue("import", bot)
        log.info("upload staged: team %s bot %s (%d files)", tid, bot, len(files))
        return bot, warnings

    def poll_status(self):
        changed = False
        for p in (STATE / "status").glob("*.json"):
            try:
                st = json.loads(p.read_text())
            except ValueError:
                continue
            finally:
                p.unlink(missing_ok=True)
            if st.get("action") != "import":
                continue
            bot = st.get("bot")
            for tid, t in self.teams.items():
                pend = t.get("pending") or {}
                if pend.get("bot") != bot:
                    continue
                t["last_import"] = {"bot": bot, "result": st.get("result"), "detail": st.get("detail", "")[:600],
                                    "at": now()}
                t["pending"] = None
                if st.get("result") == "PASS":
                    old = pend.get("old_bot")
                    t["bot"] = bot
                    t["stopped"] = t["notice"] = None
                    self.not_connected.pop(tid, None)
                    if old and old != bot:
                        self.queue("remove", old)
                changed = True
        if changed:
            self.save()

    def watchdog(self):
        """Stop team bots that stay unconnected (a loop before start(), a crash loop) so they don't eat CPU."""
        t_now = now()
        if not self.server_ok or t_now - self.server_since < 30:   # give bots time to reconnect
            self.not_connected.clear()
            return
        connected = self.connected_names()
        for tid, t in self.teams.items():
            if not t.get("bot") or t.get("pending") or t.get("stopped") or t["name"] in connected:
                self.not_connected.pop(tid, None)
                continue
            since = self.not_connected.setdefault(tid, t_now)
            if t_now - since >= WATCHDOG_SECS:
                self.queue("stop", t["bot"])
                t["stopped"] = (f"Stopped at {time.strftime('%H:%M')}: the bot did not connect within "
                                f"{WATCHDOG_SECS} s. It probably crashes or loops before start(). Fix it and upload again.")
                self.not_connected.pop(tid, None)
                self.save()
                log.warning("watchdog stopped %s (%s)", t["bot"], tid)

    def hang_check(self):
        """Restart team bots stuck burning CPU between battles (e.g. an endless loop in an event handler)."""
        t_now = now()
        idle = self.game is None and t_now - self.game_ended_at > 5
        connected = self.connected_names()
        for tid, t in self.teams.items():
            bot = t.get("bot")
            if not bot or t.get("pending") or t.get("stopped") or t["name"] not in connected:
                self.cpu_seen.pop(bot, None)    # never-connected bots are the watchdog's job
                continue
            try:
                usage = int((CGROUP / f"robocode-team@{bot}.service" / "cpu.stat").read_text().split()[1])
            except (OSError, ValueError, IndexError):
                self.cpu_seen.pop(bot, None)
                continue
            prev = self.cpu_seen.get(bot)
            self.cpu_seen[bot] = (t_now, usage, prev[2] if prev else 0)
            if not prev or not idle:
                self.cpu_seen[bot] = (t_now, usage, 0)
                continue
            share = (usage - prev[1]) / 1e6 / max(t_now - prev[0], 0.1)
            busy = prev[2] + (t_now - prev[0]) if share > HANG_CPU else 0
            self.cpu_seen[bot] = (t_now, usage, busy)
            if busy >= HANG_SECS:
                self.queue("start", bot)
                t["notice"] = (f"Restarted at {time.strftime('%H:%M')}: the bot was stuck using full CPU after a "
                               f"battle (an endless loop in an event handler?).")
                self.cpu_seen.pop(bot, None)
                self.save()
                log.warning("hang check restarted %s (%s)", bot, tid)

    def start_team(self, tid):
        t = self.teams.get(tid)
        if not t or not t.get("bot"):
            raise Problem("no such team, or it has no bot", 404)
        t["stopped"] = None
        self.not_connected.pop(tid, None)
        self.save()
        self.queue("start", t["bot"])

    # -- heats / final / standings
    def plan_heats(self, size: int):
        size = max(2, min(int(size), 20))
        connected = self.connected_names()
        ids = [tid for tid, t in self.teams.items() if t["name"] in connected]
        self.left_out = sorted(t["name"] for tid, t in self.teams.items() if tid not in ids)
        if len(ids) < 2:
            raise Problem("Need at least 2 teams with a connected bot.")
        random.shuffle(ids)
        n = math.ceil(len(ids) / size)
        heats = [[] for _ in range(n)]
        for i, tid in enumerate(ids):
            heats[i % n].append(tid)
        self.state["heats"] = [{"name": f"Heat {i + 1}", "teams": h} for i, h in enumerate(heats)]
        self.state["final"] = []
        self.save()
        return self.state["heats"]

    def set_final(self, top: int = 0, names=None):
        if names:
            ids = []
            for n in names:
                tid = n if n in self.teams else self.team_by_name(n)
                if not tid:
                    raise Problem(f"unknown team: {n}")
                ids.append(tid)
        else:
            table = self.standings()
            ids = []
            for h in self.state["heats"]:
                rows = table.get(h["name"], [])
                ids += [r["team"] for r in rows[:int(top)]]
            if len(ids) < 2:
                raise Problem("Not enough heat results yet to pick finalists.")
        self.state["final"] = ids
        self.save()
        return ids

    def classify(self, team_ids):
        """Stage for a battle with these participants (None in team_ids = a house bot)."""
        ids = set(team_ids)
        if None in ids or len(ids) < 2:
            return "Exhibition", False
        final = set(self.state["final"])
        if final and ids <= final:
            return "Final", True
        for h in self.state["heats"]:
            if ids <= set(h["teams"]):
                return h["name"], True
        return "Exhibition", False

    def standings(self):
        excluded = set(self.state["excluded"])
        table = {}
        for b in self.battles:
            if not b.get("counted") or b["id"] in excluded:
                continue
            rows = table.setdefault(b["stage"], {})
            for r in b["results"]:
                if not r.get("team"):
                    continue
                row = rows.setdefault(r["team"], {"team": r["team"], "name": r["name"], "score": 0,
                                                  "firsts": 0, "wins": 0, "battles": 0})
                row["score"] += r["total"]
                row["firsts"] += r["firsts"]
                row["wins"] += 1 if r["rank"] == 1 else 0
                row["battles"] += 1
        out = {}
        for stage, rows in table.items():
            ranked = sorted(rows.values(), key=lambda r: (-r["score"], -r["firsts"], r["name"]))
            for i, r in enumerate(ranked, 1):
                r["rank"] = i
                if r["team"] in self.teams:
                    r["name"] = self.teams[r["team"]]["name"]
            out[stage] = ranked
        return out

    # -- views
    def public(self):
        connected = self.connected_names()
        teams = sorted(({"name": t["name"], "has_bot": bool(t.get("bot")), "connected": t["name"] in connected}
                        for t in self.teams.values()), key=lambda x: x["name"].lower())
        name = lambda tid: self.teams.get(tid, {}).get("name", tid)
        excluded = set(self.state["excluded"])
        battles = [{"id": b["id"], "stage": b["stage"], "counted": b["counted"] and b["id"] not in excluded,
                    "ended": b["ended"], "rounds": b["rounds"],
                    "results": [{"name": r["name"], "rank": r["rank"], "total": r["total"], "house": not r.get("team")}
                                for r in b["results"]]}
                   for b in self.battles[-12:]][::-1]
        s = self.settings
        return {
            "title": s["title"], "reg_open": s["reg_open"], "uploads_open": s.get("uploads_open", True),
            "max_teams": s["max_teams"], "public_url": s["public_url"], "server_ok": self.server_ok,
            "teams": teams, "joined": len(self.bots),
            "heats": [{"name": h["name"], "teams": [name(t) for t in h["teams"]]} for h in self.state["heats"]],
            "final": [name(t) for t in self.state["final"]],
            "standings": self.standings(), "battles": battles, "game": self.game_public(), "tps": self.tps,
        }

    def game_public(self):
        g = self.game
        if not g:
            return None
        return {"stage": g["stage"], "counted": g["counted"], "round": g["round"], "rounds": g["rounds"],
                "arena": g["arena"], "paused": g["paused"],
                "bots": {str(k): {"name": v["name"], "house": v["team"] is None, "colors": v["colors"]}
                         for k, v in g["participants"].items()},
                "round_results": g.get("round_results")}

    def team_view(self, tid):
        t = self.teams[tid]
        connected = t["name"] in self.connected_names()
        return {"team": t["name"], "bot": t.get("bot"), "pending": bool(t.get("pending")),
                "last_import": t.get("last_import"), "connected": connected, "stopped": t.get("stopped"),
                "notice": t.get("notice"),
                "uploads_open": self.settings.get("uploads_open", True)}

    # -- server connection
    async def server_loop(self):
        delay = 1
        while True:
            try:
                async with ClientSession() as http:
                    async with http.ws_connect(SERVER_URL, heartbeat=20, max_msg_size=16 * 1024 * 1024) as ws:
                        hs = json.loads((await ws.receive(timeout=10)).data)
                        await ws.send_str(json.dumps({
                            "type": "ControllerHandshake", "sessionId": hs["sessionId"],
                            "name": "robocode-hub", "version": VERSION, "author": "club officers",
                            "secret": CONTROLLER_SECRET}))
                        self.ws_server, self.server_ok, delay = ws, True, 1
                        self.server_since = now()
                        log.info("connected to %s (server %s)", SERVER_URL, hs.get("version"))
                        await self.broadcast_state()
                        asyncio.get_running_loop().create_task(self.rejoin_check())
                        async for msg in ws:
                            if msg.type == WSMsgType.TEXT:
                                try:
                                    self.on_server(json.loads(msg.data))
                                except Exception:
                                    log.exception("bad server message")
                            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                                break
                        log.warning("server connection closed: %s", ws.close_code)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("server connection failed: %s", e)
            self.ws_server, self.server_ok, self.bots = None, False, []
            if self.game:
                self.game = None
            await self.broadcast_state()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10)

    async def rejoin_check(self):
        """Bots don't reconnect on their own after a server restart: restart them if team bots are missing."""
        since = self.server_since
        await asyncio.sleep(10)
        if self.server_since != since or not self.server_ok:
            return
        connected = self.connected_names()
        missing = [t["name"] for t in self.teams.values()
                   if t.get("bot") and not t.get("pending") and not t.get("stopped") and t["name"] not in connected]
        if missing or not self.bots:
            log.warning("after (re)connect %d bots joined, missing teams: %s -> restarting all bots",
                        len(self.bots), ", ".join(missing) or "-")
            self.queue("restartall", "All")
            self.not_connected.clear()

    def on_server(self, m):
        t = m.get("type")
        if t == "TickEventForObserver":
            g = self.game
            if not g:
                return
            g["round"] = m.get("roundNumber", g["round"])
            bots = []
            for b in m.get("botStates", []):
                p = g["participants"].get(b["id"])
                if p is not None:
                    cols = {k: b.get(k) for k in ("bodyColor", "turretColor", "radarColor", "gunColor",
                                                  "bulletColor", "scanColor") if b.get(k)}
                    if cols and cols != p["colors"]:
                        p["colors"] = cols
                        g["colors_dirty"] = True
                bots.append([b["id"], round(b["x"], 1), round(b["y"], 1), round(b["direction"], 1),
                             round(b.get("gunDirection", 0), 1), round(b.get("radarDirection", 0), 1),
                             round(b.get("radarSweep", 0), 1), round(b["energy"], 1)])
            bullets = [[round(u["x"], 1), round(u["y"], 1), round(u.get("power", 1), 2), u.get("ownerId")]
                       for u in m.get("bulletStates", [])]
            for e in m.get("events", []):
                et = e.get("type")
                if et == "BotDeathEvent":
                    self.fx.append(["death", e.get("victimId")])
                elif et == "BulletHitBotEvent":
                    self.fx.append(["hit", e.get("victimId")])
            self.frame = {"t": "tick", "round": g["round"], "turn": m.get("turnNumber"), "bots": bots,
                          "bullets": bullets}
            self.frame_seq += 1
        elif t == "BotListUpdate":
            self.bots = m.get("bots", [])
            self.schedule_state()
        elif t == "GameStartedEventForObserver":
            setup = m.get("gameSetup", {})
            parts = {}
            for p in m.get("participants", []):
                parts[p["id"]] = {"name": p.get("name"), "version": p.get("version"),
                                  "team": self.team_by_name(p.get("name")), "colors": {}}
            stage, counted = self.classify([p["team"] for p in parts.values()])
            self.game = {"setup": setup, "participants": parts, "started": now(), "round": 1,
                         "rounds": setup.get("numberOfRounds"), "paused": False, "stage": stage, "counted": counted,
                         "arena": [setup.get("arenaWidth", 800), setup.get("arenaHeight", 600)]}
            self.frame = None
            log.info("game started: %s, %d bots, %s rounds", stage, len(parts), setup.get("numberOfRounds"))
            self.schedule_state()
        elif t == "RoundStartedEvent":
            if self.game:
                self.game["round"] = m.get("roundNumber", self.game["round"])
                self.game["round_results"] = None
                self.schedule_state()
        elif t == "RoundEndedEventForObserver":
            if self.game:
                self.game["round_results"] = [{"name": r["name"], "rank": r["rank"], "total": r["totalScore"]}
                                              for r in sorted(m.get("results", []), key=lambda r: r["rank"])]
                self.schedule_state()
        elif t == "GameEndedEventForObserver":
            self.record(m)
        elif t == "GameAbortedEvent":
            log.info("game aborted")
            self.game, self.frame, self.game_ended_at = None, None, now()
            self.schedule_state()
        elif t in ("GamePausedEventForObserver", "GameResumedEventForObserver"):
            if self.game:
                self.game["paused"] = t.startswith("GamePaused")
                self.schedule_state()
        elif t == "TpsChangedEvent":
            self.tps = m.get("tps")
            self.schedule_state()

    def record(self, m):
        g = self.game or {"stage": "Exhibition", "counted": False, "participants": {}, "started": now(),
                          "setup": {}}
        results = []
        for r in sorted(m.get("results", []), key=lambda r: r["rank"]):
            team = self.team_by_name(r.get("name"))
            results.append({"name": r.get("name"), "version": r.get("version"), "team": team, "rank": r["rank"],
                            "total": r["totalScore"], "survival": r.get("survival"),
                            "bullet_damage": r.get("bulletDamage"), "firsts": r.get("firstPlaces", 0)})
        stage, counted = g["stage"], g["counted"]
        if not g["participants"]:
            stage, counted = self.classify([r["team"] for r in results])
        bid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        battle = {"id": bid, "stage": stage, "counted": counted, "started": g["started"], "ended": now(),
                  "rounds": m.get("numberOfRounds"), "game_type": g["setup"].get("gameType"), "results": results}
        write_json(STATE / "results" / f"{bid}.json", battle)
        self.battles.append(battle)
        log.info("game ended: %s %s winner=%s", bid, stage, results[0]["name"] if results else "-")
        self.game, self.frame, self.game_ended_at = None, None, now()
        self.schedule_state(final=battle)

    # -- control (admin)
    async def send_server(self, msg):
        if not self.ws_server:
            raise Problem("not connected to the Tank Royale server", 503)
        await self.ws_server.send_str(json.dumps(msg))

    async def start_battle(self, who, rounds=5, tps=None):
        """who: 'heat N' / 'final' / list of team ids or names."""
        if self.game:
            raise Problem("a battle is already running (stop it first)", 409)
        if isinstance(who, str):
            w = who.strip().lower()
            if w == "final":
                ids = self.state["final"]
            elif w.startswith("heat"):
                n = int(w.split()[-1])
                if not 1 <= n <= len(self.state["heats"]):
                    raise Problem(f"no heat {n}")
                ids = self.state["heats"][n - 1]["teams"]
            else:
                raise Problem("use 'heat N', 'final' or a list of teams")
            names = [self.teams[t]["name"] for t in ids if t in self.teams]
        else:
            names = [self.teams[x]["name"] if x in self.teams else x for x in who]
        by_name = {b.get("name"): b for b in self.bots}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise Problem("not connected: " + ", ".join(missing), 409)
        if len(names) < 2:
            raise Problem("need at least 2 bots")
        setup = {"gameType": "classic", "arenaWidth": 800, "isArenaWidthLocked": False, "arenaHeight": 600,
                 "isArenaHeightLocked": False, "minNumberOfParticipants": 2,
                 "isMinNumberOfParticipantsLocked": False, "isMaxNumberOfParticipantsLocked": False,
                 "numberOfRounds": int(rounds), "isNumberOfRoundsLocked": False, "gunCoolingRate": 0.1,
                 "isGunCoolingRateLocked": False, "maxInactivityTurns": 450, "isMaxInactivityTurnsLocked": False,
                 "turnTimeout": 30000, "isTurnTimeoutLocked": False, "readyTimeout": 1000000,
                 "isReadyTimeoutLocked": False, "defaultTurnsPerSecond": 30}
        addrs = [{"host": by_name[n]["host"], "port": by_name[n]["port"]} for n in names]
        await self.send_server({"type": "StartGame", "gameSetup": setup, "botAddresses": addrs})
        if tps:
            await asyncio.sleep(0.5)
            await self.send_server({"type": "ChangeTps", "tps": int(tps)})
        return names

    # -- browser push
    def schedule_state(self, final=None):
        asyncio.get_running_loop().create_task(self.broadcast_state(final))

    async def broadcast_state(self, final=None):
        msg = {"t": "state", "state": self.public()}
        if final:
            msg["final"] = {"stage": final["stage"], "results": final["results"]}
        await self.send_all(json.dumps(msg))

    async def send_all(self, text):
        if not self.clients:
            return

        async def one(ws):
            try:
                await asyncio.wait_for(ws.send_str(text), 2)
            except Exception:
                self.clients.discard(ws)
                await ws.close()

        await asyncio.gather(*(one(ws) for ws in list(self.clients)))

    async def frame_loop(self):
        while True:
            await asyncio.sleep(1 / FRAME_HZ)
            if self.game and self.game.pop("colors_dirty", False):
                await self.broadcast_state()
            if self.frame and self.frame_seq != self.sent_seq:
                self.sent_seq = self.frame_seq
                f = dict(self.frame, fx=self.fx)
                self.fx = []
                await self.send_all(json.dumps(f, separators=(",", ":")))

    async def status_loop(self):
        while True:
            await asyncio.sleep(1)
            try:
                before = json.dumps(self.state["teams"], sort_keys=True)
                self.poll_status()
                self.watchdog()
                self.hang_check()
                if json.dumps(self.state["teams"], sort_keys=True) != before:
                    await self.broadcast_state()
            except Exception:
                log.exception("status poll failed")


# ------------------------------------------------------------------ upload checks
def clean_paths(files: dict) -> dict:
    out = {}
    for raw, data in files.items():
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." or ":" in p or p.startswith("~") for p in parts):
            raise Problem(f"bad file name: {raw}")
        if any(p in SKIP_PARTS for p in parts) or parts[-1] in (".DS_Store", "Thumbs.db", "desktop.ini") \
                or parts[-1].endswith(".pyc"):
            continue
        if any(len(p) > 64 or not re.match(r"^[\w .\-()]+$", p) for p in parts):
            raise Problem(f"unsupported characters in file name: {raw}")
        ext = os.path.splitext(parts[-1])[1].lower()
        if ext not in ALLOWED_EXT:
            raise Problem(f"file type not allowed: {parts[-1]} (allowed: {', '.join(sorted(ALLOWED_EXT))})")
        out["/".join(parts)] = data
    # zip of the bot folder, or a folder upload: drop the shared top folder
    while out and all("/" in k for k in out) and len({k.split("/", 1)[0] for k in out}) == 1:
        out = {k.split("/", 1)[1]: v for k, v in out.items()}
    if not out:
        raise Problem("no usable files in the upload")
    if len(out) > MAX_FILES:
        raise Problem(f"too many files (max {MAX_FILES})")
    if sum(len(v) for v in out.values()) > MAX_TOTAL:
        raise Problem("upload too big (max 4 MB unpacked)")
    return out


def unzip(data: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Problem("that .zip file is damaged")
    files, total = {}, 0
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES * 2:
        raise Problem("too many files in the zip")
    for i in infos:
        if stat.S_ISLNK(i.external_attr >> 16):
            raise Problem(f"links are not allowed in the zip: {i.filename}")
        if i.file_size > MAX_FILE:
            raise Problem(f"file too big: {i.filename}")
        total += i.file_size
        if total > MAX_TOTAL:
            raise Problem("zip too big (max 4 MB unpacked)")
        with zf.open(i) as f:
            files[i.filename] = f.read(MAX_FILE + 1)
    return files


def check_bot(files: dict):
    top = {k for k in files if "/" not in k}
    pairs = sorted(os.path.splitext(k)[0] for k in top if k.endswith(".py") and k[:-3] + ".json" in top)
    if not pairs:
        raise Problem("Your bot needs a <BotName>.py and a <BotName>.json with the same name, side by side "
                      "(like MyFirstBot.py + MyFirstBot.json).")
    if len(pairs) > 1:
        raise Problem("Found more than one bot (" + ", ".join(pairs) + "). Upload one bot at a time.")
    bot = pairs[0]
    if not BOT_RE.match(bot):
        raise Problem(f"Bot name '{bot}': start with a letter; letters, digits and _ only (no spaces), "
                      f"at most 24 characters.")
    try:
        meta = json.loads(files[f"{bot}.json"].decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Problem(f"{bot}.json is not valid JSON: {e}")
    if not isinstance(meta, dict):
        raise Problem(f"{bot}.json must be a JSON object like the sample bots'.")
    for name, data in files.items():
        if name.endswith(".py"):
            try:
                compile(data.decode("utf-8-sig"), name, "exec")
            except UnicodeDecodeError:
                raise Problem(f"{name} is not UTF-8 text")
            except SyntaxError as e:
                raise Problem(f"Python syntax error in {name} line {e.lineno}: {e.msg}")
    src = files[f"{bot}.py"].decode("utf-8-sig")
    if not re.search(rf"^\s*class\s+{re.escape(bot)}\b", src, re.M):
        raise Problem(f"{bot}.py has no 'class {bot}'. The bot class, the .py and the .json must all have "
                      f"the same name.")
    warnings = []
    if "start()" not in src:
        warnings.append(f"{bot}.py never calls start(); the bot may not connect.")
    return bot, warnings


# ------------------------------------------------------------------ downloads
def load_downloads():
    """Files listed in DOWNLOADS/manifest.json (name, title, about), hashed once at start-up."""
    try:
        manifest = json.loads((DOWNLOADS / "manifest.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for item in manifest:
        name = str(item.get("name", ""))
        p = DOWNLOADS / name
        if not re.match(r"^[\w.\-]{1,80}$", name) or not p.is_file() or p.is_symlink():
            log.warning("download skipped: %s", name)
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out.append({"name": name, "title": str(item.get("title", name)), "about": str(item.get("about", "")),
                    "size": p.stat().st_size, "sha256": h.hexdigest(), "path": p})
    log.info("downloads: %d files", len(out))
    return out


# ------------------------------------------------------------------ web: public
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


@web.middleware
async def security(request, handler):
    try:
        resp = await handler(request)
    except Problem as e:
        resp = web.json_response({"ok": False, "error": str(e)}, status=e.status)
    except web.HTTPRequestEntityTooLarge:
        resp = web.json_response({"ok": False, "error": "Upload too big (max 3 MB)."}, status=413)
    except web.HTTPException as e:
        if e.status < 400:
            raise
        resp = web.json_response({"ok": False, "error": e.reason}, status=e.status)
    except (ValueError, KeyError) as e:
        resp = web.json_response({"ok": False, "error": f"bad request: {e}"[:200]}, status=400)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


def make_public_app(hub: Hub) -> web.Application:
    app = web.Application(middlewares=[security], client_max_size=MAX_UPLOAD)
    r = app.router

    async def index(req):
        return web.FileResponse(STATIC / "index.html")

    async def submit(req):
        return web.FileResponse(STATIC / "submit.html")

    downloads = load_downloads()

    async def downloads_page(req):
        return web.FileResponse(STATIC / "downloads.html")

    async def downloads_list(req):
        return web.json_response([{k: d[k] for k in ("name", "title", "about", "size", "sha256")} for d in downloads])

    async def download_file(req):
        d = next((d for d in downloads if d["name"] == req.match_info["name"]), None)
        if not d:
            raise Problem("no such file", 404)
        resp = web.FileResponse(d["path"])
        resp.headers["Content-Disposition"] = f'attachment; filename="{d["name"]}"'
        return resp

    r.add_get("/", index)
    r.add_get("/submit", submit)
    r.add_get("/downloads", downloads_page)
    r.add_get("/api/downloads", downloads_list)
    r.add_get("/files/{name}", download_file)
    r.add_static("/static", STATIC, show_index=False, follow_symlinks=False)

    async def public(req):
        return web.json_response(hub.public())

    async def team_auth(req):
        key = req.headers.get("X-Team-Key", "")
        tid, t = hub.team_by_key(key) if norm_key(key) else (None, None)
        if not tid:
            if not hub.key_fail.take():
                raise Problem("Too many wrong keys. Wait a minute.", 429)
            raise Problem("Unknown team key. Check it with your officer.", 403)
        return tid

    async def team(req):
        tid = await team_auth(req)
        return web.json_response({"ok": True, **hub.team_view(tid)})

    async def register(req):
        if not hub.reg_bucket.take():
            raise Problem("Too many sign-ups at once. Try again in a minute.", 429)
        body = await req.json()
        if not hub.settings["reg_open"] or not hub.settings["reg_code_hash"]:
            raise Problem("Team sign-up is closed. Ask an officer.", 409)
        if not hmac.compare_digest(code_hash(body.get("code", "")), hub.settings["reg_code_hash"]):
            raise Problem("Wrong event code.", 403)
        async with hub.lock:
            tid, key = hub.add_team(body.get("name", ""))
        await hub.broadcast_state()
        return web.json_response({"ok": True, "team": hub.teams[tid]["name"], "key": key})

    async def upload(req):
        tid = await team_auth(req)
        if not req.content_type.startswith("multipart/"):
            raise Problem("send the files as a form upload")
        files, size = {}, 0
        reader = await req.multipart()
        async for part in reader:
            if part.name != "files" or not part.filename:
                continue
            data = await part.read()
            size += len(data)
            if size > MAX_UPLOAD:
                raise Problem("upload too big", 413)
            if part.filename.lower().endswith(".zip"):
                files.update(unzip(bytes(data)))
            else:
                files[part.filename] = bytes(data)
        if not files:
            raise Problem("choose your bot's files (or a .zip of its folder)")
        async with hub.lock:
            bot, warnings = await hub.stage_upload(tid, files)
        await hub.broadcast_state()
        return web.json_response({"ok": True, "bot": bot, "warnings": warnings,
                                  "message": f"Uploaded {bot}. Checking it now..."})

    async def live(req):
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=4096)
        if len(hub.clients) >= 300:
            raise Problem("too many viewers", 503)
        await ws.prepare(req)
        hub.clients.add(ws)
        try:
            await ws.send_str(json.dumps({"t": "state", "state": hub.public()}))
            async for _ in ws:      # viewers don't send anything we use
                pass
        finally:
            hub.clients.discard(ws)
        return ws

    r.add_get("/api/public", public)
    r.add_get("/api/team", team)
    r.add_post("/api/register", register)
    r.add_post("/api/upload", upload)
    r.add_get("/ws/live", live)
    return app


# ------------------------------------------------------------------ web: admin (unix socket)
def make_admin_app(hub: Hub) -> web.Application:
    app = web.Application(middlewares=[security], client_max_size=64 * 1024)
    r = app.router

    async def body(req):
        return await req.json() if req.can_read_body else {}

    async def state(req):
        connected = hub.connected_names()
        teams = {tid: {"name": t["name"], "bot": t.get("bot"), "connected": t["name"] in connected,
                       "pending": t.get("pending"), "last_import": t.get("last_import"),
                       "stopped": t.get("stopped")}
                 for tid, t in hub.teams.items()}
        s = {k: v for k, v in hub.settings.items() if k != "reg_code_hash"}
        s["reg_code_set"] = bool(hub.settings["reg_code_hash"])
        return web.json_response({"settings": s, "teams": teams, "heats": hub.state["heats"],
                                  "final": hub.state["final"], "excluded": hub.state["excluded"],
                                  "bots": [b.get("name") for b in hub.bots], "server_ok": hub.server_ok,
                                  "game": hub.game_public(), "standings": hub.standings(),
                                  "battles": [{k: b[k] for k in ("id", "stage", "counted", "ended")} |
                                              {"winner": b["results"][0]["name"] if b["results"] else None}
                                              for b in hub.battles[-30:]]})

    async def settings(req):
        b = await body(req)
        s = hub.settings
        for k in ("title", "public_url"):
            if k in b:
                s[k] = str(b[k])[:120]
        for k in ("reg_open", "uploads_open"):
            if k in b:
                s[k] = bool(b[k])
        if "max_teams" in b:
            s["max_teams"] = max(2, min(int(b["max_teams"]), 40))
        if "reg_code" in b:
            code = str(b["reg_code"]).strip()
            if len(code) < 4:
                raise Problem("event code: at least 4 characters")
            s["reg_code_hash"] = code_hash(code)
        hub.save()
        await hub.broadcast_state()
        return web.json_response({"ok": True})

    async def team_add(req):
        b = await body(req)
        tid, key = hub.add_team(b.get("name", ""))
        await hub.broadcast_state()
        return web.json_response({"ok": True, "id": tid, "name": hub.teams[tid]["name"], "key": key})

    async def team_remove(req):
        hub.remove_team((await body(req)).get("id", ""))
        await hub.broadcast_state()
        return web.json_response({"ok": True})

    async def team_rekey(req):
        tid = (await body(req)).get("id", "")
        return web.json_response({"ok": True, "id": tid, "key": hub.rekey_team(tid)})

    async def team_start(req):
        hub.start_team((await body(req)).get("id", ""))
        return web.json_response({"ok": True})

    async def team_import(req):
        """USB / Samba fallback: import /opt/robocode/submissions/<folder> for a team."""
        b = await body(req)
        tid, folder = b.get("id", ""), b.get("folder", "")
        if tid not in hub.teams:
            raise Problem("no such team", 404)
        if not re.match(r"^[\w.\- ]{1,64}$", folder):
            raise Problem("bad folder name")
        src = SUBMISSIONS / folder
        if not src.is_dir() or src.is_symlink():
            raise Problem(f"not a folder: {src}")
        files = {}
        for p in src.rglob("*"):
            if p.is_symlink():
                raise Problem(f"links are not allowed: {p}")
            if p.is_file():
                if p.stat().st_size > MAX_FILE:
                    raise Problem(f"file too big: {p}")
                files[str(p.relative_to(src))] = p.read_bytes()
        async with hub.lock:
            bot, warnings = await hub.stage_upload(tid, files)
        return web.json_response({"ok": True, "bot": bot, "warnings": warnings})

    async def heats(req):
        heats = hub.plan_heats((await body(req)).get("size", 8))
        await hub.broadcast_state()
        return web.json_response({"ok": True, "heats": heats, "left_out": hub.left_out})

    async def final(req):
        b = await body(req)
        if b.get("clear"):
            hub.state["final"] = []
            hub.save()
            ids = []
        else:
            ids = hub.set_final(b.get("top", 2), b.get("teams"))
        await hub.broadcast_state()
        return web.json_response({"ok": True, "final": ids})

    async def battle(req):
        b = await body(req)
        names = await hub.start_battle(b.get("who"), b.get("rounds", 5), b.get("tps"))
        return web.json_response({"ok": True, "bots": names})

    async def control(req):
        action = req.match_info["action"]
        msgs = {"stop": "StopGame", "pause": "PauseGame", "resume": "ResumeGame"}
        if action == "tps":
            await hub.send_server({"type": "ChangeTps", "tps": int((await body(req)).get("tps", 30))})
        elif action in msgs:
            await hub.send_server({"type": msgs[action]})
        else:
            raise Problem("unknown action", 404)
        return web.json_response({"ok": True})

    async def exclude(req):
        b = await body(req)
        bid = b.get("id", "")
        if not any(x["id"] == bid for x in hub.battles):
            raise Problem("no such battle", 404)
        ex = set(hub.state["excluded"])
        ex.add(bid) if b.get("exclude", True) else ex.discard(bid)
        hub.state["excluded"] = sorted(ex)
        hub.save()
        await hub.broadcast_state()
        return web.json_response({"ok": True})

    async def reset(req):
        """Archive all battle results (keeps teams). Used after the rehearsal."""
        arch = STATE / f"archive-{time.strftime('%Y%m%d-%H%M%S')}"
        (STATE / "results").rename(arch)
        (STATE / "results").mkdir()
        hub.battles, hub.state["excluded"] = [], []
        if (await body(req)).get("teams"):
            for tid in list(hub.teams):
                hub.remove_team(tid)
            hub.state["heats"], hub.state["final"] = [], []
        hub.save()
        await hub.broadcast_state()
        return web.json_response({"ok": True, "archive": str(arch)})

    r.add_get("/state", state)
    r.add_post("/settings", settings)
    r.add_post("/team/add", team_add)
    r.add_post("/team/remove", team_remove)
    r.add_post("/team/rekey", team_rekey)
    r.add_post("/team/import", team_import)
    r.add_post("/team/start", team_start)
    r.add_post("/heats", heats)
    r.add_post("/final", final)
    r.add_post("/battle", battle)
    r.add_post("/control/{action}", control)
    r.add_post("/exclude", exclude)
    r.add_post("/reset", reset)
    return app


# ------------------------------------------------------------------ main
async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not CONTROLLER_SECRET:
        log.warning("CONTROLLER_SECRET is empty; the server will refuse the hub")
    hub = Hub()
    runners = []
    pub = web.AppRunner(make_public_app(hub), access_log=None)
    await pub.setup()
    await web.TCPSite(pub, "0.0.0.0", PORT).start()
    runners.append(pub)
    sock = RUN / "admin.sock"
    sock.unlink(missing_ok=True)
    adm = web.AppRunner(make_admin_app(hub), access_log=None)
    await adm.setup()
    old = os.umask(0o177)
    await web.UnixSite(adm, str(sock)).start()
    os.umask(old)
    runners.append(adm)
    log.info("robocode-hub %s on :%d, admin socket %s", VERSION, PORT, sock)
    await asyncio.gather(hub.server_loop(), hub.frame_loop(), hub.status_loop())


if __name__ == "__main__":
    asyncio.run(main())
