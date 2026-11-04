# Tests

## Rehearsal script (on the server)

Signs up 16 teams through the public API, uploads 16 bots (13 normal ones made from the sample bots, plus
three problem bots: one crashes mid-round, one hangs mid-round, one probes the sandbox), then 12 kinds of bad
upload and a bot that loops before connecting. It checks every answer.

```bash
sudo robo-admin reset --teams            # start empty
sudo robo-admin open TEST-CODE
sudo /opt/robocode/hub/venv/bin/python -I tests/rehearse.py http://localhost:8080 TEST-CODE
sudo robo-admin heats 8 && sudo robo-admin battle heat 1 3 -1 && sudo robo-admin results
sudo robo-admin logs SneakyBot           # the PROBE line: every secret, LAN and internet target "blocked"
sudo robo-admin reset --teams            # clean up
```

Expected: all checks PASS. The sandbox probe lists only its own folder under `/opt/robocode/bots/teams`.

## Manual checks before an event

- Pages: `/`, `/submit`, `/downloads` load from a lab PC; the lab kit downloads in full.
- Recovery: `sudo systemctl kill -s KILL robocode-server` during a battle → server and all bots back by
  themselves within ~1.5 min. `sudo reboot` → all bots back within about a minute of boot.
- Hang handling: the HangBot from the rehearsal is restarted by the hub ~20 s after its battle
  (`journalctl -u robocode-hub | grep hang`).
- After `sudo robo-admin rekey`, the old controller secret is refused (`Invalid secret` in the GUI).
