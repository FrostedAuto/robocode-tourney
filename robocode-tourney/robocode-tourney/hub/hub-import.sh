#!/usr/bin/env bash
# /opt/robocode/hub-import.sh - root worker for robocode-hub uploads (run by robocode-import.service).
#
# robocode-hub (unprivileged) stages a checked bot in /var/lib/robocode-hub/incoming/<Bot>/ and drops an
# empty request file queue/<ms>-<rand>-<action>-<Bot>.req. robocode-import.path starts this script whenever
# the queue is not empty. Actions:
#   import  run import-bot.sh on incoming/<Bot>; on PASS enable + restart robocode-team@<Bot>
#   remove  stop + disable robocode-team@<Bot> and delete bots/teams/<Bot>
#   stop    stop robocode-team@<Bot> (hub watchdog: never connected)   start  restart it
#   restartall  restart every running team + house bot (hub: bots missing after a server restart)
# The result goes to status/<Bot>.json for the hub. Only the file NAME is trusted, and only after the
# strict pattern check below; the hub never passes commands or paths.
set -uo pipefail
HUB=/var/lib/robocode-hub
TEAMS=/opt/robocode/bots/teams
shopt -s nullglob

status() {  # bot action result detail
  jq -n --arg bot "$1" --arg action "$2" --arg result "$3" --arg detail "$4" \
     '{bot:$bot, action:$action, result:$result, detail:$detail}' > "$HUB/status/.$1.tmp" \
    && chmod 644 "$HUB/status/.$1.tmp" && mv -f "$HUB/status/.$1.tmp" "$HUB/status/$1.json"
}

for req in "$HUB"/queue/*.req; do
  name=$(basename "$req")
  rm -f -- "$req"
  if [[ ! $name =~ ^[0-9]+-[0-9a-f]+-(import|remove|stop|start|restartall)-([A-Za-z][A-Za-z0-9_]{1,23})\.req$ ]]; then
    echo "ignored bad request name: $name"; continue
  fi
  action=${BASH_REMATCH[1]} bot=${BASH_REMATCH[2]}
  unit="robocode-team@$bot.service"
  case $action in
    import)
      src="$HUB/incoming/$bot"
      if [ ! -d "$src" ] || [ -L "$src" ]; then status "$bot" import FAIL "upload folder missing"; continue; fi
      out=$(/opt/robocode/import-bot.sh "$src" 2>&1); rc=$?
      rm -rf -- "$src"
      echo "$out"
      if [ $rc -eq 0 ] && grep -q "^PASS $bot " <<<"$out"; then
        systemctl enable "$unit" >/dev/null 2>&1
        systemctl reset-failed "$unit" >/dev/null 2>&1 || true
        systemctl restart "$unit"
        status "$bot" import PASS "$out"
      else
        status "$bot" import FAIL "$(sed "s#$HUB/incoming/##g" <<<"$out")"
      fi ;;
    remove)
      systemctl disable --now "$unit" >/dev/null 2>&1 || true
      rm -rf -- "${TEAMS:?}/$bot"
      status "$bot" remove PASS "removed"
      echo "removed $bot" ;;
    stop)   # watchdog: never connected. Disabled too (no restart on boot); an upload or start enables it again.
      systemctl disable --now "$unit" >/dev/null 2>&1; echo "stopped $bot (watchdog)" ;;
    restartall)   # after a server restart: bots stay alive but never reconnect by themselves
      mapfile -t u < <(systemctl list-units --no-legend --plain 'robocode-team@*' 'robocode-house@*' | awk '{print $1}')
      [ ${#u[@]} -eq 0 ] || { systemctl reset-failed "${u[@]}" 2>/dev/null; systemctl restart "${u[@]}"; }
      echo "restarted ${#u[@]} bots after a server restart" ;;
    start)
      [ -d "$TEAMS/$bot" ] || { echo "no bot dir for $bot"; continue; }
      systemctl reset-failed "$unit" >/dev/null 2>&1 || true
      systemctl enable "$unit" >/dev/null 2>&1; systemctl restart "$unit"; echo "started $bot" ;;
  esac
done
