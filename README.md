# robocode-tourney

A self-contained server for running a **Robocode Tank Royale** programming tournament in a computer lab.
Teams write a small Python program that drives a virtual tank, test it on a lab PC, upload it through a web
page, and every team's tank fights in the same arena while everyone watches live on the projector.

Built by the **OIT AI Club** for our club tournament. MIT license.

## What you get

- **Game server:** [Robocode Tank Royale](https://robocode-dev.github.io/tank-royale/) 1.4.0, the open-source
  successor of IBM's classic Robocode. It's the referee: physics, scoring, one battle at a time.
- **Tournament hub** (this project), a small web service on port 8080:
  - **Projector page** `/`: live arena in the browser, energy bars, standings, heat line-up, results podium
  - **Team page** `/submit`: sign-up with an event code, a personal team key, bot upload, and live status
    (*accepted*, *connected*, or a plain-English error)
  - **Downloads** `/downloads`: a no-admin install kit for Windows lab PCs, a starter bot, an install guide
  - Records every battle, makes random heats, picks finalists, and counts heat/final battles automatically
- **Sandboxed bots:** each team's bot runs as its own user, with no network except the game server, no view
  of other teams' code or the secrets, and CPU/RAM caps. Watchdogs stop or restart bots that never connect,
  hang, or lose the server.
- **`robo-admin`:** a menu and commands for event night: sign-up, teams, heats, final, battles without the
  GUI, results, logs, new secrets.
- **One idempotent `setup.sh`** that builds everything on a fresh Ubuntu 24.04 VM.

```
 Lab PCs ── browser: /submit (upload), /downloads (install kit) ──┐
                                                                  ▼
 Projector PC ── projector: live arena + scoreboard ──▶  Server VM (Ubuntu 24.04)
             └── main screen: Robocode GUI (referee)        ├ Tank Royale 1.4.0 game server   :7654
                                                            ├ robocode-hub (pages, uploads)   :8080
                                                            └ one sandboxed process per team's tank
```

## Get the server

### Option A: ready-made Proxmox image (recommended)

Download `vzdump-qemu-106-2026_11_03-17_41_12.vma.zst` from the
**[Releases page](https://github.com/FrostedAuto/robocode-tourney/releases)** (about 930 MB, SHA256 `4989098e7d92ab98…`), then on Proxmox:

1. Copy it into a backup storage's dump folder (e.g. `/var/lib/vz/dump/`) and **Restore** it (tick *Unique*).
2. VM → **Cloud-Init**: set a **User** and **Password** → *Regenerate Image* → **Start**.
3. Console: log in with that user → `sudo robo-admin status` and `sudo robo-admin secrets`.

The image contains **no users, passwords or secrets**: Cloud-Init creates your login, and the server makes its
own secrets on first boot. Full steps: [docs/deploy-proxmox.md](docs/deploy-proxmox.md).

### Option B: build from source

On a fresh **Ubuntu Server 24.04** VM (4 vCPU, 8 GB RAM, 32 GB disk) with internet:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/FrostedAuto/robocode-tourney.git
sudo bash robocode-tourney/setup.sh      # ~10 min
sudo robo-admin secrets                  # controller secret for the Robocode GUI, Samba password
sudo robo-admin status
```

### Then

Open `http://<vm-ip>:8080/` from another PC. Four house bots (SpinBot, Crazy, Walls, Track Fire) are
connected for a first demo. In the **Robocode GUI** (in the lab kit on `/downloads`, or
[Tank Royale releases](https://github.com/robocode-dev/tank-royale/releases/tag/v1.4.0)): Server → Server
Options → remote server `ws://<vm-ip>:7654` + controller secret → Battle → Start Battle.

## Documentation

| | |
|---|---|
| [docs/deploy-proxmox.md](docs/deploy-proxmox.md) | VM size, ports, restore the image or build from this repo, admin access |
| [docs/running-an-event.md](docs/running-an-event.md) | Event checklist, timeline, `robo-admin` commands, what to do when things break |
| [docs/lab-pc-install.md](docs/lab-pc-install.md) | Setting up Windows lab PCs without admin rights; student instructions |
| [docs/security.md](docs/security.md) | Sandboxing, upload checks, secrets, known limits |
| [tests/README.md](tests/README.md) | Rehearsal script and manual checks |
| [image/README.md](image/README.md) | How the Releases image is made (and how to make your own) |

## Secrets and accounts

**This repository contains no secrets.** Each install generates its own. Nothing here is a default password.

| What | How to see it | How to change it |
|---|---|---|
| Controller secret (Robocode GUI, full battle control) | `sudo robo-admin secrets` | `sudo robo-admin rekey` |
| Bot secret (bots joining the server; internal) | `/opt/robocode/secrets.env` (root) | `sudo robo-admin rekey` |
| Samba `teams` password (USB fallback share `\\<vm-ip>\submissions`) | `sudo robo-admin secrets` | `sudo robo-admin rekey` |
| Admin login (the VM's Linux user) | you set it: Proxmox Cloud-Init tab (image) or the Ubuntu installer (source) | `passwd` |
| Event code (team sign-up) | you choose it: `sudo robo-admin open <CODE>` | run `open` again; `close` stops sign-up |
| Team keys (one per team) | shown once, at sign-up or `team add` | `sudo robo-admin team rekey <team-id>` |

The Releases image has no secrets in it; each copy makes its own on first boot. **If you restore a backup of a
server someone else has used, run `sudo robo-admin rekey` first:** it replaces every secret.

## Ports

| Port | Service | Who needs it |
|---|---|---|
| 8080/tcp | hub: projector page, team page, downloads | every lab PC |
| 7654/tcp | Tank Royale game server | the PC running the Robocode GUI |
| 22/tcp | SSH | admins |
| 445/tcp | Samba `[submissions]` | only for the USB fallback |

ufw allows only these. The server needs no internet once installed.

## Layout

```
setup.sh                   installer (Ubuntu 24.04), idempotent
hub/hub.py                 robocode-hub: web pages, uploads, scoreboard, admin API (aiohttp)
hub/static/                projector page, team page, downloads page
hub/hub-import.sh          root worker: imports checked uploads, starts/stops bot units
hub/robo-admin             admin menu + commands (installed to /usr/local/sbin)
downloads/                 build-downloads.sh (lab kit from official sources, SHA256-pinned) + manifest.json
lab-kit/                   install.cmd + README.txt for Windows lab PCs, starter bot MyBot
image/                     prepare-image.sh: turns a fresh build into the shareable Proxmox image
docs/, tests/              documentation, rehearsal script
```

Installed: `/opt/robocode` (jars, venvs, bots, scripts, secrets), `/var/lib/robocode-hub` (teams, results),
systemd units `robocode-server`, `robocode-hub`, `robocode-import.path`, `robocode-team@<Bot>`,
`robocode-house@<Bot>`, `robocode-server-check.timer`, `robocode-firstboot`, slice `robocode-bots.slice`.

## Updating

```bash
cd robocode-tourney && git pull && sudo bash setup.sh
```
Keeps secrets, teams and results. `REBUILD_DOWNLOADS=1` rebuilds the lab kit; `SKIP_DOWNLOADS=1` skips it.
The Tank Royale version is pinned in `setup.sh` (`TR_VERSION`); the GUI, the Python package and the server
must all be the same version.

## Credits

- [Robocode Tank Royale](https://github.com/robocode-dev/tank-royale) by Flemming N. Larsen and contributors
  (Apache-2.0). The sample bots and the GUI come from its releases.
- OIT AI Club: tournament hub, setup, lab kit, image and docs (MIT, see [LICENSE](LICENSE)).
- The image and lab kit include third-party software under its own licenses: [THIRD-PARTY.md](THIRD-PARTY.md).
