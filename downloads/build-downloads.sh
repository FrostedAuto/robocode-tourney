#!/usr/bin/env bash
# build-downloads.sh - build the files the hub offers on /downloads (run by setup.sh; needs internet).
#
# Usage: sudo bash downloads/build-downloads.sh [OUT_DIR]        (default /opt/robocode/downloads)
#
# Builds robocode-lab-kit.zip for Windows lab PCs without admin rights: Python 3.13 (per-user installer),
# robocode-tank-royale 1.4.0 + dependencies as Windows wheels (offline install), a Java 21 runtime (zip),
# the Robocode Tank Royale GUI 1.4.0, the Python sample bots and the starter bot. Every downloaded file is
# checked against the SHA256 pinned below; the kit's install.cmd checks them again on the PC.
# Also writes MyBot-starter.zip, Install-guide.md, the GUI jar, the sample bots and manifest.json.
set -euo pipefail

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)     # repo root (or /opt/robocode/src)
OUT=${1:-/opt/robocode/downloads}
PY=${PY:-/opt/robocode/hub/venv/bin/python}              # any python3 with pip, to fetch the Windows wheels

# url  sha256   (official sources: adoptium.net, python.org, github.com/robocode-dev/tank-royale)
FILES=(
  "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip 2332c0b4cff6bed722da3567c91d5e47568bcba863fa4945d0a8d6fc76158628"
  "https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe 5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190"
  "https://github.com/robocode-dev/tank-royale/releases/download/v1.4.0/robocode-tankroyale-gui-1.4.0.jar d4b90a08421336fb3a79cf40ac18e881b138dd5ee92c2ad3bd1eedfaefe3a11b"
  "https://github.com/robocode-dev/tank-royale/releases/download/v1.4.0/sample-bots-Python-1.4.0.zip bb5f25772e4d0a092f1066a8a264cdb465c27a96f91c2f6d968565ff9eed5b1d"
)
# Windows (cp313, win_amd64) wheels: the bot API and its dependencies, versions as tested
WHEELS=(robocode-tank-royale==1.4.0 mypy==2.4.1 mypy_extensions==1.1.0 pathspec==1.1.1 librt==0.16.0
        ast_serialize==0.13.1 typing_extensions==4.16.0 websockets==17.4 PyYAML==6.0.3 pycountry==26.2.16
        setuptools==84.2.1 pip==26.2.2)

die() { echo "ERROR: $*" >&2; exit 1; }
[ -x "$PY" ] || PY=python3
"$PY" -m pip --version >/dev/null 2>&1 || die "need a python with pip ($PY)"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
KIT="$WORK/robocode-lab-kit"
mkdir -p "$KIT/downloads" "$KIT/wheels"

for entry in "${FILES[@]}"; do
  url=${entry% *} sum=${entry##* } name=$(basename "${entry% *}")
  echo "downloading  $name"
  curl -fsSL --retry 3 -o "$KIT/downloads/$name" "$url" || die "download failed: $url"
  echo "$sum  $KIT/downloads/$name" | sha256sum -c --quiet - || die "SHA256 mismatch: $name"
done

echo "downloading  Windows wheels (${#WHEELS[@]})"
(cd "$WORK" && "$PY" -m pip download -q --disable-pip-version-check --no-cache-dir --only-binary=:all: \
   --platform win_amd64 --python-version 3.13 --implementation cp -d "$KIT/wheels" "${WHEELS[@]}")
ls "$KIT"/wheels/robocode_tank_royale-1.4.0-*.whl >/dev/null || die "bot API wheel missing"

cp -r "$SRC/lab-kit/." "$KIT/"
for f in install.cmd README.txt; do sed -i 's/\r\?$/\r/' "$KIT/$f"; done      # Windows line endings
(cd "$KIT" && find downloads wheels starter -type f | LC_ALL=C sort | while read -r f; do
   printf '%s  %s\r\n' "$(sha256sum "$f" | cut -d' ' -f1)" "${f//\//\\}"; done > SHA256SUMS.txt)

python3 - "$WORK" <<'PY'
import os, sys, zipfile
work = sys.argv[1]
def zipdir(target, base, folder):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(os.path.join(base, folder)):
            for f in sorted(files):
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, base))
zipdir(os.path.join(work, "robocode-lab-kit.zip"), work, "robocode-lab-kit")
zipdir(os.path.join(work, "MyBot-starter.zip"), os.path.join(work, "robocode-lab-kit", "starter"), "MyBot")
PY

GUIDE="$SRC/docs/lab-pc-install.md"
[ -f "$GUIDE" ] && sed 's/\r\?$/\r/' "$GUIDE" > "$WORK/Install-guide.md" || echo "(see the project README)" > "$WORK/Install-guide.md"

install -d -m 755 -o root -g root "$OUT"
install -m 644 -o root -g root "$WORK/robocode-lab-kit.zip" "$WORK/MyBot-starter.zip" "$WORK/Install-guide.md" \
  "$KIT/downloads/robocode-tankroyale-gui-1.4.0.jar" "$KIT/downloads/sample-bots-Python-1.4.0.zip" \
  "$SRC/downloads/manifest.json" "$OUT/"
echo "downloads ready in $OUT:"
ls -la "$OUT"
