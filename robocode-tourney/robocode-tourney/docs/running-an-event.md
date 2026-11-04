# Running an event

A 2-hour club tournament for up to 16 teams (configurable). Replace `<vm-ip>` with the server's address; the
VM's console login screen shows it.

## Addresses

| What | Where |
|---|---|
| **Projector page** (live arena + standings) | `http://<vm-ip>:8080/`, browser full screen (F11) |
| Team page (sign-up, upload, status) | `http://<vm-ip>:8080/submit`; put it on the board |
| Downloads (lab kit, starter bot) | `http://<vm-ip>:8080/downloads` |
| Robocode GUI (referee control) | Server → Server Options → remote `ws://<vm-ip>:7654` + **controller secret** |
| Admin | VM console or `ssh <admin>@<vm-ip>`, then `sudo robo-admin` (menu) |

`sudo robo-admin secrets` shows the controller secret and logins. Don't show that screen on the projector.

## Screens

- **Projector:** the projector page. It shows the live arena during battles, standings, the heat line-up
  between battles, a results podium after each battle, and the upload link.
- **Main screen:** the Robocode GUI (you pick bots and start battles), the admin terminal, and the team page
  for helping teams.

The hub records every battle the GUI starts. Battles count automatically when the bots in it are exactly a
heat (or the final). Anything else (house bots, mixed teams) is an **Exhibition** and doesn't count.

## Before the event

- [ ] Server installed (README) or restored (`deploy-proxmox.md`), and on a new copy `sudo robo-admin rekey`.
- [ ] From a lab PC: the three pages load.
- [ ] Projector PC: lab kit installed, GUI connects, one house-bot battle runs and shows on the projector page.
- [ ] Lab PCs: lab kit installed (`lab-pc-install.md`). If profiles are wiped at logout, install on the day.
- [ ] Snapshot of the VM, so you can roll back mid-event.
- [ ] USB stick: the unzipped lab kit and an empty folder for bot submissions.

## Timeline

**Setup (45 min before)**
```
sudo robo-admin status                    # server, hub, house bots connected?
sudo robo-admin title "Our Club Robocode Tournament"
sudo robo-admin max 16                    # cap on teams
sudo robo-admin open <EVENT-CODE>         # sign-up open; write the code + the /submit link on the board
```

**Install help desk (30 min before).** Teams sign up at `/submit` and write down their key. Staff can also
make teams: `sudo robo-admin team add "Red Baron"` (prints the key once).

**Intro (10 min):** a house-bot exhibition (GUI: SpinBot, Crazy, Walls, Track Fire → Start). Explain:
write a Python bot, test it locally, upload it, heats, final.

**Build time (~60 min).** Uploads open. Exhibition battles with uploaded bots keep the projector busy.
`sudo robo-admin status`: green ● = connected, yellow = starting/not connected, **STOPPED** = the watchdog
stopped a bot that never connected (the team page says why).

**Heats**
```
sudo robo-admin close                     # no new teams
sudo robo-admin uploads off               # freeze bots
sudo robo-admin heats 8                   # random heats of up to 8 connected bots; shown on the projector
```
Run each heat in the GUI (select exactly that heat's bots, **5 rounds**, normal speed ≈ 1.5–2 min), or
without the GUI: `sudo robo-admin battle heat 1 5`.

**Final**
```
sudo robo-admin final 2                   # best 2 of each heat (or: final set "A" "B" "C" ...)
```
GUI: select the finalists, **10 rounds**, or `sudo robo-admin battle final 10`. The podium shows on the
projector for 20 s; standings stay.

**Awards.** `sudo robo-admin results` has every number. Results stay in `/var/lib/robocode-hub/results/`
(one JSON file per battle). Afterwards: `sudo robo-admin reset --teams` archives them and removes the teams.

## Submissions

- **Normal:** teams upload on `/submit` with their team key (`.py` + `.json`, or a `.zip` of the folder).
  The page shows *accepted* and *connected ✔*, or what's wrong. The newest upload counts.
- **USB fallback:** copy the team's bot **folder** into `\\<vm-ip>\submissions` (File Explorer, user `teams`,
  password from `robo-admin secrets`), then `sudo robo-admin team import <team-id> <FolderName>`
  (`sudo robo-admin team add "Name"` first if the team doesn't exist).

## When something goes wrong

| Symptom | What to do |
|---|---|
| A heat was run twice / started wrong | `sudo robo-admin results` → `sudo robo-admin exclude <battle-id>` |
| Team's bot "not connected" | Usually loops/crashes before `start()`. The team page shows it; they fix + re-upload. Logs: `sudo robo-admin logs <BotName>` |
| Bot STOPPED by watchdog, team says it's fixed | They upload again (restarts it), or `sudo robo-admin team start <team-id>` |
| A bot hangs during a battle | The battle goes on (it just stops moving). After the battle the hub restarts it by itself |
| All bots gone from Joined Bots | Wait 15 s (the hub restarts them). Else `sudo robo-admin restart-bots` (≈ 8 s) |
| Server crashed | Comes back **by itself in ~1.5 min**, bots too. Re-run the interrupted battle |
| Team lost its key | `sudo robo-admin team rekey <team-id>` |
| Lab PCs can't open the pages | Check the VM's address; a firewall may block port 8080 → USB fallback |
| VM broken | Roll back to your snapshot (note the results first) |

## robo-admin reference

`sudo robo-admin help` lists everything: status, open/close, uploads on|off, max, title, url, team
add/list/remove/rekey/start/import, heats, final, battle, stop/pause/resume/tps, house on|off, results,
exclude/include, logs, restart-bots, reset, secrets, rekey.
