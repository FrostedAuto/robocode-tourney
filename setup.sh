#!/usr/bin/env bash
# setup.sh - Robocode Tank Royale tournament server setup (Ubuntu 24.04 LTS). Part of robocode-tourney.
#
# Idempotent: safe to re-run.   Usage:  sudo bash setup.sh        (from a git clone, or /opt/robocode/setup.sh)
# From a clone it first copies itself, hub/, downloads/ and lab-kit/ to /opt/robocode, then installs.
# SKIP_DOWNLOADS=1 skips building the lab kit for the /downloads page; REBUILD_DOWNLOADS=1 forces it.
# Re-running keeps existing secrets and the Samba password, re-verifies every download
# against the release SHA256SUMS, and rewrites helper scripts, bot launchers, the systemd
# unit, the Samba share and the firewall rules. Nothing host- or IP-specific is baked in.
#
# Creates:
#   /opt/robocode/bin            Tank Royale jars (+ SHA256SUMS, sample bot zip)
#   /opt/robocode/venv           Python venv with robocode-tank-royale
#   /opt/robocode/bots/samples   Python sample bots      /opt/robocode/bots/teams  imported student bots
#   /opt/robocode/submissions    Samba drop folder [submissions] (user: teams)
#   /opt/robocode/results        battle results
#   /opt/robocode/secrets.env    CONTROLLER_SECRET / BOT_SECRET (mode 600)
#   /opt/robocode/bots.env       SERVER_URL / SERVER_SECRET for booted bots (mode 600)
#   /opt/robocode/HELP.txt       --help output of the server / booter / recorder jars
#   /opt/robocode/import-bot.sh  import student bots from submissions/ into bots/teams/
#   /opt/robocode/boot-bots.sh   boot bots in the background (systemd unit robocode-bots-<group>)
#   robocode-server.service      the server on port 7654 (user robocode)
#   /root/credentials.txt        Samba 'teams' password (mode 600)
#   step 11 (if $ROOT/hub/ exists): robocode-hub.service (port 8080), robocode-import.path/.service,
#   robocode-team@/robocode-house@ bot units in robocode-bots.slice, /usr/local/sbin/robo-admin,
#   the 4 house bots (first install only), and the /downloads files (lab kit, starter bot, ...)
set -euo pipefail

TR_VERSION="1.4.0"
ROOT="/opt/robocode"
PORT="7654"
GH_API="https://api.github.com/repos/robocode-dev/tank-royale/releases/tags/v${TR_VERSION}"
ASSETS=(
  "robocode-tankroyale-server-${TR_VERSION}.jar"
  "robocode-tankroyale-booter-${TR_VERSION}.jar"
  "robocode-tankroyale-runner-${TR_VERSION}.jar"
  "robocode-tankroyale-recorder-${TR_VERSION}.jar"
  "sample-bots-Python-${TR_VERSION}.zip"
)
SERVER_JAR="$ROOT/bin/robocode-tankroyale-server-${TR_VERSION}.jar"
BOOTER_JAR="$ROOT/bin/robocode-tankroyale-booter-${TR_VERSION}.jar"
RECORDER_JAR="$ROOT/bin/robocode-tankroyale-recorder-${TR_VERSION}.jar"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
rand() { python3 -c 'import secrets,string,sys;a=string.ascii_letters+string.digits;print("".join(secrets.choice(a) for _ in range(int(sys.argv[1]))))' "$1"; }
nocolor() { sed -r 's/\x1b\[[0-9;]*[A-Za-z]//g'; }

[ "$(id -u)" -eq 0 ] || die "run as root: sudo bash $0"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

# running from a git clone: install the sources into $ROOT (keeps venvs, secrets and data)
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ "$SRC" != "$ROOT" ] && [ -f "$SRC/hub/hub.py" ]; then
  log "0 installing sources from $SRC into $ROOT"
  install -d -m 755 -o root -g root "$ROOT" "$ROOT/hub" "$ROOT/src"
  install -m 755 "$SRC/setup.sh" "$ROOT/setup.sh"
  cp -r "$SRC/hub/." "$ROOT/hub/"
  rm -rf "$ROOT/src/downloads" "$ROOT/src/lab-kit" "$ROOT/src/docs"
  cp -r "$SRC/downloads" "$SRC/lab-kit" "$ROOT/src/"
  [ -d "$SRC/docs" ] && cp -r "$SRC/docs" "$ROOT/src/"
  chown -R root:root "$ROOT/hub" "$ROOT/src"
  exec bash "$ROOT/setup.sh" "$@"
fi
cd /

# ---------------------------------------------------------------- 1. packages
log "1/10 apt update, upgrade, install packages"
apt-get update
apt-get -y upgrade
apt-get -y install openjdk-21-jre-headless python3 python3-venv python3-pip samba unzip curl jq ufw qemu-guest-agent
systemctl start qemu-guest-agent || true   # static unit on Ubuntu, started by udev when the agent device exists

# ---------------------------------------------------------------- 2. users + folders
log "2/10 users and folders"
for u in robocode robocode-bots teams; do
  id "$u" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$u"
done
install -d -m 755 -o root -g root "$ROOT" "$ROOT/bin" "$ROOT/venv" "$ROOT/bots" "$ROOT/bots/samples" "$ROOT/bots/teams"
install -d -m 2775 -o teams -g teams "$ROOT/submissions"
install -d -m 2775 -o root -g robocode "$ROOT/results"

# ---------------------------------------------------------------- 3. Tank Royale downloads
log "3/10 Tank Royale ${TR_VERSION} jars + Python sample bots (SHA256-verified)"
cd "$ROOT/bin"
sum_line() { awk -v n="$1" '$2==n || $2=="*"n {print $1"  "n; f=1} END {exit !f}' SHA256SUMS; }
verified() { [ -f SHA256SUMS ] && [ -f "$1" ] && sum_line "$1" | sha256sum -c --status - ; }
need=0
for a in "${ASSETS[@]}"; do verified "$a" || need=1; done
if [ "$need" = 1 ]; then
  rel=$(curl -fsSL -H 'Accept: application/vnd.github+json' "$GH_API") || die "cannot read $GH_API"
  asset_url() { jq -er --arg n "$1" '.assets[] | select(.name==$n) | .browser_download_url' <<<"$rel"; }
  curl -fsSL -o SHA256SUMS.part "$(asset_url SHA256SUMS)" && mv SHA256SUMS.part SHA256SUMS
  for a in "${ASSETS[@]}"; do
    verified "$a" && { echo "ok (cached)  $a"; continue; }
    want=$(sum_line "$a" | cut -d' ' -f1) || die "$a is not listed in SHA256SUMS"
    echo "downloading  $a"
    curl -fsSL -o "$a.part" "$(asset_url "$a")"
    got=$(sha256sum "$a.part" | cut -d' ' -f1)
    [ "$got" = "$want" ] || { rm -f "$a.part"; die "SHA256 mismatch for $a"; }
    gh=$(jq -r --arg n "$a" '.assets[] | select(.name==$n) | .digest // empty' <<<"$rel")
    [ -z "$gh" ] || [ "$gh" = "sha256:$got" ] || { rm -f "$a.part"; die "GitHub digest mismatch for $a"; }
    mv "$a.part" "$a"
  done
fi
for a in "${ASSETS[@]}"; do sum_line "$a" | sha256sum -c - ; done
chmod 644 "${ASSETS[@]}" SHA256SUMS
unzip -oq "sample-bots-Python-${TR_VERSION}.zip" -d "$ROOT/bots/samples"
cd /

# ---------------------------------------------------------------- 4. Python venv
log "4/10 venv + robocode-tank-royale==${TR_VERSION}"
[ -x "$ROOT/venv/bin/python" ] || python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/python" -m pip install -q --disable-pip-version-check "robocode-tank-royale==${TR_VERSION}"
"$ROOT/venv/bin/python" -I -c 'import robocode_tank_royale, importlib.metadata as m; print("import robocode_tank_royale OK, version", m.version("robocode-tank-royale"))'

# ---------------------------------------------------------------- 5. --help output
log "5/10 HELP.txt"
{
  echo "# Generated by setup.sh on $(date -Is). Tank Royale ${TR_VERSION}."
  for cmd in "$SERVER_JAR --help" "$SERVER_JAR --version" "$BOOTER_JAR --help" \
             "$BOOTER_JAR boot --help" "$BOOTER_JAR dir --help" "$BOOTER_JAR info --help" \
             "$RECORDER_JAR --help"; do
    echo; echo "### java -jar $cmd"
    # shellcheck disable=SC2086
    timeout 30 java -jar $cmd 2>&1 || true
  done
} | nocolor > "$ROOT/HELP.txt"
chmod 644 "$ROOT/HELP.txt"

# ---------------------------------------------------------------- 6. secrets + server service
log "6/10 secrets + robocode-server.service"
if [ ! -s "$ROOT/secrets.env" ]; then
  ( umask 077; printf 'CONTROLLER_SECRET=%s\nBOT_SECRET=%s\n' "$(rand 24)" "$(rand 24)" > "$ROOT/secrets.env" )
fi
chown root:root "$ROOT/secrets.env"; chmod 600 "$ROOT/secrets.env"
# shellcheck disable=SC1091
. "$ROOT/secrets.env"
( umask 077; printf 'SERVER_URL=ws://localhost:%s\nSERVER_SECRET=%s\n' "$PORT" "$BOT_SECRET" > "$ROOT/bots.env" )
chown root:root "$ROOT/bots.env"; chmod 600 "$ROOT/bots.env"

# first boot of a shared image (image/prepare-image.sh deletes all secrets): make this server's own secrets,
# a Samba password and SSH host keys before anything starts. Does nothing once secrets.env exists.
cat > "$ROOT/firstboot.sh" <<'FIRSTBOOT_EOF'
#!/bin/sh
# Generated by setup.sh. Run by robocode-firstboot.service when /opt/robocode/secrets.env is missing.
set -eu
rand() { python3 -c 'import secrets,string,sys;a=string.ascii_letters+string.digits;print("".join(secrets.choice(a) for _ in range(int(sys.argv[1]))))' "$1"; }
umask 077
cs=$(rand 24); bs=$(rand 24); sp=$(rand 20)
printf 'CONTROLLER_SECRET=%s\nBOT_SECRET=%s\n' "$cs" "$bs" > /opt/robocode/secrets.env.new
mv /opt/robocode/secrets.env.new /opt/robocode/secrets.env
printf 'SERVER_URL=ws://localhost:7654\nSERVER_SECRET=%s\n' "$bs" > /opt/robocode/bots.env
printf '%s\n%s\n' "$sp" "$sp" | smbpasswd -s -a teams >/dev/null
smbpasswd -e teams >/dev/null
printf 'samba user teams password: %s\n' "$sp" > /root/credentials.txt
ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1 || ssh-keygen -A
echo "robocode first boot: new secrets created (sudo robo-admin secrets shows them)"
FIRSTBOOT_EOF
chmod 755 "$ROOT/firstboot.sh"
cat > /etc/systemd/system/robocode-firstboot.service <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Robocode: create this server's secrets on first boot
ConditionPathExists=!$ROOT/secrets.env
# Don't order against ssh.socket / smbd: that makes an ordering cycle and systemd drops ssh.socket.
# Cloud-Init creates the SSH host keys; the ssh-keygen -A below is only a fallback.
After=local-fs.target
Before=robocode-server.service robocode-hub.service

[Service]
Type=oneshot
ExecStart=$ROOT/firstboot.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable robocode-firstboot.service >/dev/null 2>&1

unit=/etc/systemd/system/robocode-server.service
cat > "$unit.new" <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Robocode Tank Royale server ${TR_VERSION} (port ${PORT})
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=robocode
Group=robocode
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/secrets.env
Environment=NO_COLOR=1 TERM=dumb
# After a crash the old connections sit in TIME_WAIT for ~60 s; the server can't bind its port then and
# keeps running without listening. Wait for the port to clear (robocode-server-check.timer is the backstop).
ExecStartPre=/bin/sh -c 'i=0; while [ \$\$i -lt 90 ] && ss -Htan "( sport = :$PORT )" | grep -q .; do i=\$\$((i+1)); sleep 1; done; exit 0'
ExecStart=/usr/bin/java -jar $SERVER_JAR --port=$PORT --controller-secrets=\${CONTROLLER_SECRET} --bot-secrets=\${BOT_SECRET}
Restart=always
RestartSec=3
TimeoutStartSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=robocode-server
CPUWeight=1000
NoNewPrivileges=yes
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
changed=0
cmp -s "$unit.new" "$unit" && rm -f "$unit.new" || { mv "$unit.new" "$unit"; changed=1; }

# health backstop: restart the server if it has been up 40+ s but isn't listening for 3 checks in a row
cat > "$ROOT/server-check.sh" <<CHECK_EOF
#!/bin/sh
# Generated by setup.sh. Run every 10 s by robocode-server-check.timer.
f=/run/robocode-server-check.fails
systemctl is-active -q robocode-server || { rm -f \$f; exit 0; }
if ss -Hltn "sport = :$PORT" | grep -q .; then rm -f \$f; exit 0; fi
up=\$(( \$(date +%s) - \$(date -d "\$(systemctl show -p ActiveEnterTimestamp --value robocode-server)" +%s) ))
[ \$up -ge 40 ] || exit 0
n=\$(( \$(cat \$f 2>/dev/null || echo 0) + 1 )); echo \$n > \$f
if [ \$n -ge 3 ]; then
  echo "robocode-server up \${up}s but not listening on $PORT: restarting"; rm -f \$f; systemctl restart robocode-server
fi
CHECK_EOF
chmod 755 "$ROOT/server-check.sh"
cat > /etc/systemd/system/robocode-server-check.service <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Restart robocode-server if it runs without listening on ${PORT}

[Service]
Type=oneshot
ExecStart=$ROOT/server-check.sh
EOF
cat > /etc/systemd/system/robocode-server-check.timer <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Check robocode-server every 10 s

[Timer]
OnBootSec=60
OnUnitActiveSec=10
AccuracySec=1

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now robocode-server-check.timer >/dev/null 2>&1
systemctl enable robocode-server.service
if [ "$changed" = 1 ]; then systemctl restart robocode-server.service; else systemctl start robocode-server.service; fi

# ---------------------------------------------------------------- 7. import-bot.sh + boot-bots.sh
log "7/10 import-bot.sh + boot-bots.sh"
cat > "$ROOT/import-bot.sh" <<'IMPORT_EOF'
#!/usr/bin/env bash
# /opt/robocode/import-bot.sh - import student bots from the Samba drop folder (generated by setup.sh).
#
# Usage: sudo /opt/robocode/import-bot.sh <BotFolder> [<BotFolder>...]
#        sudo /opt/robocode/import-bot.sh --all
# <BotFolder> is a folder name inside /opt/robocode/submissions (or a path to a folder).
# For each bot: requires <Name>.py and <Name>.json where <Name> is the folder name, valid JSON
# (name, version, authors), valid Python syntax; converts CRLF to LF; writes <Name>.sh that runs
# the venv python; installs to /opt/robocode/bots/teams/<Name> (replacing an older copy only
# if the new one passes). Prints one PASS/FAIL line per bot; exits 1 if any bot failed.
set -uo pipefail

ROOT=/opt/robocode
SUB="$ROOT/submissions"
TEAMS="$ROOT/bots/teams"
PY="$ROOT/venv/bin/python"

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0 $*" >&2; exit 2; }
[ $# -gt 0 ] || { sed -n '4,5p' "$0" >&2; exit 2; }

fails=0
NAME=""; STAGE=""
fail() { echo "FAIL $NAME: $*"; [ -n "$STAGE" ] && rm -rf -- "$STAGE"; fails=$((fails+1)); }

import_one() {
  local arg=${1%/} src out
  STAGE=""
  case $arg in */*) src=$arg ;; *) src="$SUB/$arg" ;; esac
  NAME=$(basename -- "$src")
  [ -d "$src" ] || { fail "folder not found: $src"; return; }
  [[ $NAME =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || { fail "folder name must be letters, digits, _ or - (no spaces)"; return; }
  [ -z "$(find "$src" -type l -print -quit)" ] || { fail "contains symlinks"; return; }

  STAGE=$(mktemp -d "$TEAMS/.import-$NAME.XXXXXX")
  cp -R -- "$src/." "$STAGE/" || { fail "copy failed"; return; }
  find "$STAGE" -depth \( -name __pycache__ -o -name '*.pyc' \) -exec rm -rf {} +

  # Windows line endings -> LF; strip a UTF-8 BOM from JSON (jq rejects it)
  find "$STAGE" -type f \( -iname '*.py' -o -iname '*.json' -o -iname '*.txt' -o -iname '*.md' \
       -o -iname '*.cfg' -o -iname '*.ini' -o -iname '*.yaml' -o -iname '*.yml' -o -iname '*.csv' \) \
       -exec sed -i 's/\r$//' {} +
  find "$STAGE" -type f -iname '*.json' -exec sed -i '1s/^\xEF\xBB\xBF//' {} +

  if [ ! -f "$STAGE/$NAME.json" ]; then
    fail "missing $NAME.json (found: $(cd "$STAGE" && ls -- *.json 2>/dev/null | tr '\n' ' '))"; return
  fi
  if [ ! -f "$STAGE/$NAME.py" ]; then
    fail "missing $NAME.py (found: $(cd "$STAGE" && ls -- *.py 2>/dev/null | tr '\n' ' '))"; return
  fi
  jq -e 'type=="object" and (.name|type=="string" and length>0) and (.version|type=="string")
         and (.authors|type=="array" and length>0)' "$STAGE/$NAME.json" >/dev/null 2>&1 \
    || { fail "$NAME.json is not valid JSON or lacks name/version/authors"; return; }

  out=$(cd / && find "$STAGE" -type f -name '*.py' -print0 | xargs -0 "$PY" -I -c '
import sys
bad = 0
for p in sys.argv[1:]:
    try:
        compile(open(p, "rb").read(), p, "exec")
    except SyntaxError as e:
        print("%s line %s: %s" % (e.filename.rsplit("/", 1)[-1], e.lineno, e.msg)); bad = 1
sys.exit(bad)' 2>&1) || { fail "Python syntax error: $(echo "$out" | head -3 | tr '\n' ' ')"; return; }

  printf '#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec %s "%s.py"\n' "$PY" "$NAME" > "$STAGE/$NAME.sh"
  chown -R root:root "$STAGE"
  find "$STAGE" -type d -exec chmod 755 {} +
  find "$STAGE" -type f -exec chmod 644 {} +
  chmod 755 "$STAGE/$NAME.sh"

  rm -rf -- "${TEAMS:?}/$NAME"
  mv -- "$STAGE" "$TEAMS/$NAME" || { fail "install failed"; return; }
  STAGE=""
  local warn=""
  [ "$(jq -r .name "$TEAMS/$NAME/$NAME.json")" = "$NAME" ] || warn=" (note: json \"name\" is \"$(jq -r .name "$TEAMS/$NAME/$NAME.json")\")"
  echo "PASS $NAME -> $TEAMS/$NAME$warn"
}

if [ "$1" = "--all" ]; then
  set -- ; for d in "$SUB"/*/; do [ -d "$d" ] && set -- "$@" "$d"; done
  [ $# -gt 0 ] || { echo "no folders in $SUB"; exit 0; }
fi
for b in "$@"; do import_one "$b"; done
[ "$fails" -eq 0 ]
IMPORT_EOF

cat > "$ROOT/boot-bots.sh" <<'BOOT_EOF'
#!/usr/bin/env bash
# /opt/robocode/boot-bots.sh - boot bots in the background (generated by setup.sh).
#
# Usage: sudo /opt/robocode/boot-bots.sh <group> <bot_dir>...
#          e.g. sudo /opt/robocode/boot-bots.sh demo samples/SpinBot samples/Crazy samples/Walls samples/TrackFire
#        sudo /opt/robocode/boot-bots.sh --stop <group>     stop the group and all its bot processes
#        sudo /opt/robocode/boot-bots.sh --list             list running groups
# Bot dirs are relative to /opt/robocode/bots (or absolute paths under it).
# Each group is a transient systemd unit robocode-bots-<group> running the Tank Royale booter as
# user robocode-bots, with /opt/robocode/venv/bin first in PATH and SERVER_URL/SERVER_SECRET
# from /opt/robocode/bots.env. Limits: 3 CPUs, 4 GB RAM. Logs: journalctl -u robocode-bots-<group> -f
set -euo pipefail
ROOT=/opt/robocode
BOOTER=$(ls "$ROOT"/bin/robocode-tankroyale-booter-*.jar | sort -V | tail -1)
usage() { sed -n '4,8p' "$0" >&2; exit 2; }
die() { echo "ERROR: $*" >&2; exit 1; }

case "${1:-}" in
  --exec)  # internal: run by the systemd unit. The booter quits when stdin closes, so keep it open.
    shift; exec java -jar "$BOOTER" boot "$@" < <(exec sleep infinity) ;;
  --list)  systemctl list-units --all --no-legend 'robocode-bots-*'; exit 0 ;;
  --stop)  [ -n "${2:-}" ] || usage; systemctl stop "robocode-bots-$2"; echo "stopped robocode-bots-$2"; exit 0 ;;
  ""|-h|--help) usage ;;
esac
[ "$(id -u)" -eq 0 ] || die "run as root: sudo $0 $*"
group=$1; shift
[[ $group =~ ^[A-Za-z0-9_-]+$ ]] || die "group name: letters, digits, _ or -"
[ $# -gt 0 ] || usage
dirs=()
for d in "$@"; do
  case $d in /*) p=$d ;; *) p="$ROOT/bots/$d" ;; esac
  p=$(realpath -e -- "$p" 2>/dev/null) || die "no such bot dir: $d"
  [[ $p == "$ROOT"/bots/* && -d $p ]] || die "not a bot dir under $ROOT/bots: $d"
  dirs+=("$p")
done
unit="robocode-bots-$group"
systemctl is-active --quiet "$unit" && die "$unit is already running (stop it: $0 --stop $group)"
systemctl reset-failed "$unit" >/dev/null 2>&1 || true
systemd-run --quiet --collect --unit="$unit" --description="Robocode bots: $group" \
  -p SuccessExitStatus=143 \
  --uid=robocode-bots --gid=robocode-bots --working-directory="$ROOT/bots" \
  -p EnvironmentFile="$ROOT/bots.env" \
  --setenv=PATH="$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin" \
  --setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=PYTHONUNBUFFERED=1 \
  -p CPUQuota=300% -p MemoryMax=4G -p TasksMax=1024 \
  -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p ProtectProc=invisible \
  "$ROOT/boot-bots.sh" --exec "${dirs[@]}"
echo "started $unit with ${#dirs[@]} bot(s)"
echo "  logs: journalctl -u $unit -f     stop: sudo $0 --stop $group"
BOOT_EOF
chmod 755 "$ROOT/import-bot.sh" "$ROOT/boot-bots.sh"

# ---------------------------------------------------------------- 8. sample bot launchers
log "8/10 sample bot launchers -> venv python"
for d in "$ROOT"/bots/samples/*/; do
  d=${d%/}; n=$(basename "$d")
  [ -f "$d/$n.py" ] || continue
  printf '#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec %s "%s.py"\n' "$ROOT/venv/bin/python" "$n" > "$d/$n.sh"
done
chown -R root:root "$ROOT/bots/samples"
find "$ROOT/bots/samples" -type d -exec chmod 755 {} +
find "$ROOT/bots/samples" -type f -exec chmod 644 {} +
find "$ROOT/bots/samples" -type f -name '*.sh' -exec chmod 755 {} +

# ---------------------------------------------------------------- 9. Samba
log "9/10 Samba share [submissions]"
if ! pdbedit -L 2>/dev/null | cut -d: -f1 | grep -qx teams; then
  pw=$(rand 20)
  printf '%s\n%s\n' "$pw" "$pw" | smbpasswd -s -a teams
  ( umask 077; touch /root/credentials.txt
    sed -i '/^samba user teams password:/d' /root/credentials.txt
    echo "samba user teams password: $pw" >> /root/credentials.txt )
  unset pw
fi
smbpasswd -e teams >/dev/null
chmod 600 /root/credentials.txt
conf=/etc/samba/smb.conf
[ -f "$conf.orig-robocode" ] || cp -p "$conf" "$conf.orig-robocode"
sed -i '/^# BEGIN robocode-submissions$/,/^# END robocode-submissions$/d' "$conf"
cat >> "$conf" <<EOF
# BEGIN robocode-submissions
[submissions]
   comment = Robocode bot submissions
   path = $ROOT/submissions
   valid users = teams
   force user = teams
   force group = teams
   read only = no
   guest ok = no
   browseable = yes
   create mask = 0664
   directory mask = 2775
# END robocode-submissions
EOF
testparm -s >/dev/null 2>&1 || die "smb.conf invalid (testparm)"
systemctl enable smbd >/dev/null 2>&1
systemctl restart smbd

# ---------------------------------------------------------------- 10. firewall
log "10/10 ufw: 22, 445, ${PORT}/tcp"
ufw allow 22/tcp
ufw allow 445/tcp
ufw allow "${PORT}/tcp"
ufw --force enable

# ---------------------------------------------------------------- 11. hub + per-team bot units
# robocode-hub (live arena, scoreboard, team uploads on :$HUB_PORT) needs its sources in $ROOT/hub
# (hub.py, hub-import.sh, robo-admin, static/). Each bot runs as its own sandboxed unit:
# robocode-team@<Bot> (bots/teams/<Bot>) or robocode-house@<Bot> (bots/samples/<Bot>), all in
# robocode-bots.slice (3 CPUs / 5 GB total), localhost-only network, own dynamic user, and no view of
# other bots, the secrets or the hub's data. Enabled units start again on boot.
HUB_PORT="8080"
AIOHTTP_VERSION="3.14.5"
if [ -f "$ROOT/hub/hub.py" ]; then
  log "11/11 robocode-hub + bot units"
  id robocode-hub >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin robocode-hub
  [ -x "$ROOT/hub/venv/bin/python" ] || python3 -m venv "$ROOT/hub/venv"
  "$ROOT/hub/venv/bin/python" -m pip install -q --disable-pip-version-check "aiohttp==${AIOHTTP_VERSION}"
  install -d -m 755 -o root -g root "$ROOT/downloads"   # files + manifest.json for the hub's /downloads page
  install -m 755 "$ROOT/hub/hub-import.sh" "$ROOT/hub-import.sh"
  install -m 755 "$ROOT/hub/robo-admin" /usr/local/sbin/robo-admin
  chown -R root:root "$ROOT/hub/hub.py" "$ROOT/hub/static"
  chmod 644 "$ROOT/hub/hub.py"; find "$ROOT/hub/static" -type d -exec chmod 755 {} +; find "$ROOT/hub/static" -type f -exec chmod 644 {} +

  units=()
  put_unit() {  # name, content on stdin
    local f="/etc/systemd/system/$1"; cat > "$f.new"
    cmp -s "$f.new" "$f" && rm -f "$f.new" || { mv "$f.new" "$f"; units+=("$1"); }
  }
  put_unit robocode-hub.service <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Robocode hub: live arena, scoreboard, team uploads (port ${HUB_PORT})
After=robocode-server.service
Wants=robocode-server.service

[Service]
User=robocode-hub
Group=robocode-hub
EnvironmentFile=$ROOT/secrets.env
Environment=HUB_PORT=${HUB_PORT} HUB_SERVER_URL=ws://localhost:${PORT} PYTHONDONTWRITEBYTECODE=1
ExecStart=$ROOT/hub/venv/bin/python -I $ROOT/hub/hub.py
StateDirectory=robocode-hub
StateDirectoryMode=0750
RuntimeDirectory=robocode-hub
RuntimeDirectoryMode=0750
Restart=always
RestartSec=2
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
LockPersonality=yes
CapabilityBoundingSet=
InaccessiblePaths=-/opt/robocode/bots.env -/root
ReadOnlyPaths=$ROOT/submissions
MemoryMax=512M

[Install]
WantedBy=multi-user.target
EOF
  put_unit robocode-import.path <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Watch the robocode-hub upload queue

[Path]
DirectoryNotEmpty=/var/lib/robocode-hub/queue
MakeDirectory=no

[Install]
WantedBy=multi-user.target
EOF
  put_unit robocode-import.service <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Import queued robocode-hub uploads (root worker)

[Service]
Type=oneshot
ExecStart=$ROOT/hub-import.sh
EOF
  put_unit robocode-bots.slice <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=All Robocode bots (teams + house)

[Slice]
CPUQuota=300%
MemoryMax=5G
EOF
  for kind in team house; do
    # every team bot gets its own dynamic user (rt-<Bot>), so bots can't signal or ptrace each other
    if [ "$kind" = team ]; then dir="$ROOT/bots/teams" user="rt-%i"; else dir="$ROOT/bots/samples" user="robocode-house"; fi
    put_unit "robocode-$kind@.service" <<EOF
# Managed by $ROOT/setup.sh
[Unit]
Description=Robocode $kind bot %i
After=robocode-server.service
Wants=robocode-server.service
ConditionPathExists=$dir/%i/%i.py
# keep retrying while the server is down; the hub's watchdog stops team bots that never connect
StartLimitIntervalSec=0

[Service]
Slice=robocode-bots.slice
DynamicUser=yes
User=$user
WorkingDirectory=$dir/%i
EnvironmentFile=$ROOT/bots.env
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
ExecStart=$ROOT/venv/bin/python %i.py
Restart=always
RestartSec=5
CPUQuota=50%
MemoryMax=400M
TasksMax=64
IPAddressDeny=any
IPAddressAllow=localhost
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
TemporaryFileSystem=$ROOT/bots:ro
BindReadOnlyPaths=$dir/%i
InaccessiblePaths=-/var/lib/robocode-hub -$ROOT/submissions -$ROOT/results -$ROOT/secrets.env -$ROOT/bots.env -/root -/etc/samba -/var/lib/samba
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectProc=invisible
ProcSubset=pid
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
SystemCallArchitectures=native
CapabilityBoundingSet=
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
  done
  systemctl daemon-reload
  install -d -m 750 -o robocode-hub -g robocode-hub /var/lib/robocode-hub
  for d in queue incoming status results; do install -d -m 750 -o robocode-hub -g robocode-hub "/var/lib/robocode-hub/$d"; done
  systemctl enable robocode-hub.service robocode-import.path >/dev/null 2>&1
  systemctl start robocode-import.path
  systemctl restart robocode-hub.service   # picks up hub.py changes; state is on disk, viewers reconnect
  [ ${#units[@]} -eq 0 ] || echo "changed units: ${units[*]} (running bots pick these up on: robo-admin restart-bots)"
  ufw allow "${HUB_PORT}/tcp"

  # first install: the 4 house (sample) bots for demos; later runs leave your choice alone
  if [ ! -e "$ROOT/.house-initialized" ]; then
    for b in SpinBot Crazy Walls TrackFire; do systemctl enable --now "robocode-house@$b" >/dev/null 2>&1 || true; done
    touch "$ROOT/.house-initialized"
  fi

  # files for the hub's /downloads page (lab kit for Windows lab PCs, starter bot, install guide)
  if [ "${SKIP_DOWNLOADS:-0}" != 1 ] && [ -f "$ROOT/src/downloads/build-downloads.sh" ] &&
     { [ "${REBUILD_DOWNLOADS:-0}" = 1 ] || [ ! -f "$ROOT/downloads/manifest.json" ]; }; then
    log "11b building the /downloads files (lab kit, ~140 MB)"
    bash "$ROOT/src/downloads/build-downloads.sh" "$ROOT/downloads"
    systemctl restart robocode-hub.service   # the hub reads the downloads list at start-up
  fi
fi

# ---------------------------------------------------------------- summary
log "verify"
for i in $(seq 1 30); do ss -ltn "sport = :$PORT" | grep -q LISTEN && break; sleep 1; done
systemctl is-active robocode-server.service
ss -ltn "sport = :$PORT" | grep LISTEN || die "nothing listening on $PORT"
echo
echo "Ubuntu:   $(. /etc/os-release; echo "$PRETTY_NAME")"
echo "Java:     $(java -version 2>&1 | head -1)"
echo "Python:   $("$ROOT/venv/bin/python" --version)"
echo "pip pkg:  robocode-tank-royale $("$ROOT/venv/bin/python" -I -c 'import importlib.metadata as m;print(m.version("robocode-tank-royale"))')"
echo "Jars:     $(cd "$ROOT/bin" && ls -- *.jar | tr '\n' ' ')"
echo "Server:   ws://<this-vm-ip>:$PORT   secrets in $ROOT/secrets.env, Samba password in /root/credentials.txt"
echo "DONE"
