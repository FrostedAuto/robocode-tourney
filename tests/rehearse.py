# Rehearsal: register 16 teams and upload good + bad bots through the public API, like lab PCs would.
# Run ON the server, after `sudo robo-admin reset --teams` and `sudo robo-admin open <event-code>`:
#   sudo /opt/robocode/hub/venv/bin/python -I tests/rehearse.py http://localhost:8080 <event-code>
# Afterwards: sudo robo-admin reset --teams
import asyncio, io, json, re, sys, time, zipfile
from pathlib import Path
from aiohttp import ClientSession, FormData

BASE, CODE = sys.argv[1], sys.argv[2]
SAMPLES = Path("/opt/robocode/bots/samples")
GOOD = ["Corners", "Crazy", "Fire", "RamFire", "SpinBot", "TrackFire", "VelociBot", "Walls", "Target"]
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def mock(sample, new, inject=None, top=None):
    py = (SAMPLES / sample / f"{sample}.py").read_text()
    py = re.sub(rf"\b{sample}\b", new, py)
    if inject:  # put code at the start of on_scanned_bot
        py = re.sub(r"(def on_scanned_bot\(self, [^)]*\)[^:]*:\n)", r"\1        " + inject + "\n", py, count=1)
        assert inject in py, f"inject failed for {sample}"
    if top:
        py = top + "\n" + py
    js = (SAMPLES / sample / f"{sample}.json").read_text()
    return {f"{new}.py": py.encode(), f"{new}.json": js.encode()}


def as_zip(files, folder=None, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(f"{folder}/{n}" if folder else n, d)
        for info, d in (extra or []):
            z.writestr(info, d)
    return {"bot.zip": buf.getvalue()}


PROBE = '''import os, socket, struct
def _gateway():
    try:   # the sandbox hides /proc/net, so this usually falls back
        for line in open("/proc/net/route").read().splitlines()[1:]:
            f = line.split()
            if f[1] == "00000000":
                return socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
    except OSError:
        pass
    return "192.168.0.1"
def _probe():
    out = []
    for p in ["/opt/robocode/secrets.env", "/opt/robocode/bots.env", "/var/lib/robocode-hub/state.json",
              "/root/credentials.txt", "/proc/net/route", "/opt/robocode/bots/teams", "/opt/robocode/bots/samples", "/home/robo"]:
        try:
            out.append(p + (": LIST " + str(os.listdir(p)[:6]) if os.path.isdir(p) else ": READ " + open(p).read(20)))
        except Exception as e:
            out.append(p + ": blocked " + type(e).__name__)
    for h, port in [(_gateway(), 80), ("1.1.1.1", 443), ("8.8.8.8", 53)]:
        s = socket.socket(); s.settimeout(2)
        try:
            s.connect((h, port)); out.append(f"{h}:{port} CONNECTED")
        except Exception as e:
            out.append(f"{h}:{port} blocked " + type(e).__name__)
        finally:
            s.close()
    print("PROBE " + " | ".join(out), flush=True)
_probe()'''


async def main():
    t0 = time.time()
    async with ClientSession() as s:
        async def post(path, key=None, js=None, files=None):
            h = {"X-Team-Key": key} if key else {}
            if files is not None:
                fd = FormData()
                for n, d in files.items():
                    fd.add_field("files", d, filename=n, content_type="application/octet-stream")
                r = await s.post(BASE + path, data=fd, headers=h)
            else:
                r = await s.post(BASE + path, json=js, headers=h)
            try:
                return r.status, await r.json()
            except Exception:
                return r.status, {"error": "non-JSON reply: " + (await r.text())[:80]}

        # --- sign-up
        st, r = await post("/api/register", js={"name": "Wrong Code", "code": "nope"})
        check("register with wrong event code is refused", st == 403, r.get("error"))
        teams = {}
        names = [f"Team {c}" for c in "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet Kilo Lima Mike November Oscar Papa".split()]
        for n in names:
            st, r = await post("/api/register", js={"name": n, "code": CODE})
            if st == 200:
                teams[n] = r["key"]
        check("16 teams registered", len(teams) == 16, f"{len(teams)}")
        st, r = await post("/api/register", js={"name": "Team Seventeen", "code": CODE})
        check("17th team refused (max 16)", st == 409, r.get("error"))
        st, r = await post("/api/register", js={"name": "team alpha", "code": CODE})
        check("duplicate team name refused", st in (400, 409), r.get("error"))
        st, r = await post("/api/register", js={"name": "<script>x</script>", "code": CODE})
        check("HTML in team name refused", st == 400, r.get("error"))

        keys = list(teams.values())
        # --- good uploads: 13 normal bots (mix of plain files, zip with folder)
        for i, n in enumerate(names[:13]):
            sample = GOOD[i % len(GOOD)]
            bot = re.sub(r"\W", "", n.split()[1]) + "Bot"
            files = mock(sample, bot)
            if i % 2:
                files = as_zip(files, folder=bot)
            st, r = await post("/api/upload", key=teams[n], files=files)
            check(f"upload {n} ({sample} as {bot})", st == 200, r.get("error") or r.get("message"))
        # problem bots that import fine but misbehave in battle
        st, r = await post("/api/upload", key=teams["Team November"],
                           files=mock("SpinBot", "CrashBot", inject="1 / 0  # crash mid-round"))
        check("upload CrashBot (crashes when it sees a tank)", st == 200, r.get("error"))
        st, r = await post("/api/upload", key=teams["Team Oscar"],
                           files=mock("TrackFire", "HangBot", inject="while True: pass  # hang mid-round"))
        check("upload HangBot (hangs when it sees a tank)", st == 200, r.get("error"))
        st, r = await post("/api/upload", key=teams["Team Papa"], files=mock("Walls", "SneakyBot", top=PROBE))
        check("upload SneakyBot (probes the sandbox, then plays)", st == 200, r.get("error"))

        # --- bad uploads (all with Team Alpha's key; Alpha's bot must keep running)
        k = teams["Team Alpha"]
        for _ in range(60):
            r = await (await s.get(BASE + "/api/team", headers={"X-Team-Key": k})).json()
            if not r.get("pending"):
                break
            await asyncio.sleep(1)
        t_imp = time.time() - t0
        check("Team Alpha's upload checked and accepted", r.get("bot") == "AlphaBot", f"after {t_imp:.0f}s")
        bad = {
            "syntax error": {"BadSyntax.py": b"class BadSyntax(:\n  pass\n", "BadSyntax.json": b'{"name":"x"}'},
            "missing .json": {"NoJson.py": b"class NoJson: pass\n"},
            "class name differs from files": {"Mismatch.py": b"class Other: pass\n", "Mismatch.json": b"{}"},
            "invalid json": {"BadJson.py": b"class BadJson: pass\n", "BadJson.json": b"{name: x"},
            "two bots in one upload": {**mock("SpinBot", "OneBot"), **mock("Crazy", "TwoBot")},
            "exe file": {**mock("SpinBot", "ExeBot"), "evil.exe": b"MZ"},
            "path traversal in zip": as_zip(mock("SpinBot", "SlipBot"), extra=[("../../evil.py", b"x")]),
            "symlink in zip": as_zip(mock("SpinBot", "LinkBot"), extra=[(_symlink("link.txt"), b"/etc/passwd")]),
            "too big": {**mock("SpinBot", "BigBot"), "big.txt": b"x" * (3 * 1024 * 1024 + 10)},
            "bot name owned by another team": mock("Crazy", "BravoBot"),
            "bad bot name": {"my-bot.py": b"class x: pass\n", "my-bot.json": b"{}"},
        }
        for label, files in bad.items():
            st, r = await post("/api/upload", key=k, files=files)
            check(f"rejected: {label}", st >= 400, f"{st} {r.get('error', '')[:110]}")
            await asyncio.sleep(0.2)
        st, r = await post("/api/upload", key="AAAA-BBBB-CCCC", files=mock("SpinBot", "NoKey"))
        check("upload with a wrong key refused", st == 403, r.get("error"))
        # a bot that loops before start(): imports fine, never connects (replaces Team Mike's first bot)
        for _ in range(60):
            r = await (await s.get(BASE + "/api/team", headers={"X-Team-Key": teams["Team Mike"]})).json()
            if not r.get("pending"):
                break
            await asyncio.sleep(1)
        st, r = await post("/api/upload", key=teams["Team Mike"],
                           files=mock("Corners", "LoopBot", top="while True:\n    pass"))
        check("upload LoopBot (loops before connecting)", st == 200, r.get("error"))

        # --- wait for imports + connections
        deadline = time.time() + 120
        while time.time() < deadline:
            pub = await (await s.get(BASE + "/api/public")).json()
            conn = [t for t in pub["teams"] if t["connected"]]
            if len(conn) >= 15 and not any(t["name"] == "Team Mike" for t in conn):
                break
            await asyncio.sleep(3)
        conn_names = {t["name"] for t in pub["teams"] if t["connected"]}
        check("15 team bots connected (LoopBot team must not be)", len(conn_names) == 15 and "Team Mike" not in conn_names,
              f"{len(conn_names)} connected; missing: {sorted(set(names) - conn_names)}")
        r = await (await s.get(BASE + "/api/team", headers={"X-Team-Key": teams["Team Alpha"]})).json()
        check("Team Alpha still has its first bot after the bad uploads", r.get("bot") == "AlphaBot" and r.get("connected"),
              json.dumps(r)[:200])
        r = await (await s.get(BASE + "/api/team", headers={"X-Team-Key": teams["Team Mike"]})).json()
        check("Team Mike page says bot uploaded but not connected", r.get("bot") == "LoopBot" and not r.get("connected"),
              json.dumps(r)[:200])
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} checks passed in {time.time() - t0:.0f}s")


def _symlink(name):
    info = zipfile.ZipInfo(name)
    info.external_attr = (0o120777 << 16)
    return info


asyncio.run(main())
