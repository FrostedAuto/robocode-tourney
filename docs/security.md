# Security design

The server runs code written by students during the event, so it treats every bot as untrusted.

## Secrets

None are in this repository. Every install creates its own; `sudo robo-admin rekey` replaces all of them
(use it on any copy restored from someone else's backup).

| Secret | Used for | Stored (root only, mode 600) |
|---|---|---|
| Controller secret | Robocode GUI and the hub control battles | `/opt/robocode/secrets.env` |
| Bot secret | Bots joining the game server | `secrets.env`, `bots.env` (passed to bot processes) |
| Samba `teams` password | USB fallback share | `/root/credentials.txt` |
| Team keys | One per team, to upload its bot | Only SHA-256 hashes, `/var/lib/robocode-hub/state.json` |
| Event code | Team sign-up | Only a hash, in `state.json` |

## Bots (untrusted code)

Each team's bot runs as its own systemd unit `robocode-team@<Bot>`:
- its own dynamic user `rt-<Bot>`, so bots can't signal or trace each other
- network: localhost only (`IPAddressAllow=localhost`), so no LAN and no internet
- file system: read-only; it sees only its own folder. Other teams' bots, uploads, hub data, secrets
  and `/root` are hidden
- limits: 50 % of a CPU and 400 MB each; all bots share a slice capped at 3 CPUs and 5 GB
- no privileges: empty capability set, `NoNewPrivileges`, private `/tmp` and `/dev`, hidden processes of other
  users, kernel tunables/modules/logs protected, no namespaces, native system calls only

The hub watches them:
- a bot that never connects (a loop before `start()`, a crash loop) is stopped after 90 s, and the team page
  says why
- a bot stuck using CPU between battles (an endless loop in an event handler) is restarted
- after a server restart, all bots are restarted (they don't reconnect on their own)

## Uploads

- Teams need their key. Wrong keys are rate-limited across the whole server.
- One bot per upload: `<Name>.py` + `<Name>.json` plus optional helper files. Allowed types: `.py .json .txt
  .md .csv .cfg .ini .yaml .yml`.
- Limits: 3 MB request, 1 MB per file, 4 MB total, 60 files.
- Zips: path traversal (`../`), drive letters and symlinks are refused. Absolute paths are made relative to
  the bot folder.
- Python is syntax-checked (compiled, never run) and the class name must match the files.
- A bot name already used by another team is refused. The JSON `name` is replaced with the team's
  registered name, so a team can't pose as another in the arena or the results.
- Privilege separation: the web service (user `robocode-hub`, no root) only stages files and drops a request
  in a queue. A root-only worker (`robocode-import.service`, started by a path unit) trusts nothing but a
  strictly checked file name, runs `import-bot.sh`, and starts the bot's unit.

## Web pages

Public, read-only except sign-up and upload. Strict Content-Security-Policy (no inline scripts, no external
resources), `X-Frame-Options: DENY`, `nosniff`, no caching. Browsers never receive a secret. Admin
functions are only on a unix socket (`/run/robocode-hub/admin.sock`) used by `robo-admin` as root.
`/downloads` serves only the files listed in a root-owned manifest.

## Server

The game server requires the controller and bot secrets. It runs as user `robocode`, restarts on failure,
and has a health timer that restarts it if it runs without listening. The firewall (ufw) allows only 22,
445, 7654 and 8080.

## Known limits

- Pages and uploads use plain HTTP on the local network, so team keys cross the LAN unencrypted. Put the
  server on a trusted lab network.
- The secrets appear on the game server's command line, visible to local users with a shell (bots can't see
  other users' processes).
- SSH allows password login for the admin account; use a strong password (`rekey` makes one).
- Bots can use their CPU share during a battle however they like. A bot that hangs only loses its own turns.
