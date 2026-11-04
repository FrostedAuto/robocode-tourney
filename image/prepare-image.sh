#!/usr/bin/env bash
# prepare-image.sh - turn a freshly built server into a shareable Proxmox image (no secrets, no users).
#
# Run inside the VM after `sudo bash setup.sh`, as the build user:   sudo bash image/prepare-image.sh
# It deletes this server's secrets, Samba password, teams, results, logs, SSH host keys and machine ID,
# removes the build user, resets cloud-init and powers off. Then, on the Proxmox host:
#   qm set <vmid> --delete ciuser,cipassword,sshkeys,cicustom      # no login baked into the image
#   vzdump <vmid> --mode stop --compress zstd --storage <backup-storage>
# On the first start of a restored copy, cloud-init creates the login from the VM's Cloud-Init tab and
# robocode-firstboot.service makes new secrets.
set -euo pipefail
ROOT=/opt/robocode
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
BUILD_USER=${SUDO_USER:-}
echo "This wipes this server's secrets, teams, results, logs, SSH host keys and the build user '${BUILD_USER:-?}',"
echo "then powers the VM off. Only do this on a VM you are turning into an image."
if [ "${1:-}" != "--yes" ]; then read -rp "Type yes: " a; [ "$a" = yes ] || exit 1; fi

systemctl stop robocode-hub robocode-import.path robocode-server robocode-server-check.timer 2>/dev/null || true
mapfile -t bots < <(systemctl list-units --all --no-legend --plain 'robocode-team@*' | awk '{print $1}')
for u in "${bots[@]}"; do systemctl disable --now "$u" >/dev/null 2>&1 || true; done
systemctl stop 'robocode-house@*' 2>/dev/null || true

# secrets and passwords
rm -f "$ROOT/secrets.env" "$ROOT/bots.env" /root/credentials.txt
pdbedit -x teams >/dev/null 2>&1 || true
systemctl stop smbd nmbd 2>/dev/null || true
rm -f /var/lib/samba/private/passdb.tdb            # freed tdb records keep old hashes; firstboot recreates it
find /root /home -name authorized_keys -delete     # cloud-init also puts the build key into root's file
# event data
rm -rf "$ROOT"/bots/teams/* "$ROOT"/submissions/* "$ROOT"/results/* /var/lib/robocode-hub/state.json \
       /var/lib/robocode-hub/archive-* /var/lib/robocode-hub/{results,incoming,queue,status}/*
# identity: SSH host keys, machine ID, cloud-init state (cloud-init + firstboot recreate them)
rm -f /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id; rm -f /var/lib/dbus/machine-id
rm -f /etc/cloud/cloud-init.disabled
cloud-init clean --logs --seed >/dev/null 2>&1 || true
rm -f /etc/netplan/50-cloud-init.yaml
cat > /etc/netplan/60-robocode-any-nic.yaml <<'EOF'
# Fallback: DHCP on a NIC that Cloud-Init didn't configure (Cloud-Init's own config renames it to eth0).
# optional: boot never waits for this one.
network:
  version: 2
  ethernets:
    anynic:
      match:
        name: "en*"
      dhcp4: true
      dhcp-identifier: mac
      optional: true
EOF
chmod 600 /etc/netplan/60-robocode-any-nic.yaml
# SSH: password login for the Cloud-Init user (the cloud image turns it off); root login stays off
cat > /etc/ssh/sshd_config.d/10-robocode.conf <<'EOF'
# robocode-tourney image: allow password login for the admin user set in Proxmox Cloud-Init.
PasswordAuthentication yes
PermitRootLogin no
EOF
# console login screen: where to start
cat > /etc/issue <<'EOF'
Ubuntu 24.04 LTS \n \l

  ROBOCODE TANK ROYALE TOURNAMENT SERVER  (github.com/FrostedAuto/robocode-tourney)
  Projector / scoreboard :  http://\4:8080/
  Team uploads           :  http://\4:8080/submit
  Downloads (lab kit)    :  http://\4:8080/downloads
  Robocode GUI           :  ws://\4:7654   (controller secret: sudo robo-admin secrets)
  Login                  :  the user + password from the VM's Cloud-Init tab in Proxmox
  Admin                  :  sudo robo-admin

EOF
# logs, caches, history
apt-get clean
journalctl --rotate >/dev/null 2>&1 || true; journalctl --vacuum-time=1s >/dev/null 2>&1 || true
rm -rf /tmp/* /var/tmp/* /root/.bash_history /root/.cache "$ROOT"/hub/venv/.cache 2>/dev/null || true
find /var/log -type f \( -name '*.gz' -o -name '*.1' -o -name '*.old' \) -delete
find /var/log -type f -exec truncate -s 0 {} +
# last step runs detached (deleting the build user ends this session): remove the build user, trim, power off.
# Cloud-Init creates the real admin user on first boot.
DEL=""
[ -n "$BUILD_USER" ] && [ "$BUILD_USER" != root ] && id "$BUILD_USER" >/dev/null 2>&1 && DEL="$BUILD_USER"
systemd-run --quiet --unit=robocode-image-finish --on-active=5 /bin/sh -c "
  if [ -n '$DEL' ]; then pkill -KILL -u '$DEL'; sleep 1; userdel -r -f '$DEL'; rm -f /etc/sudoers.d/90-cloud-init-users; fi
  rm -rf /tmp/* /var/tmp/*; journalctl --rotate; rm -rf /var/log/journal/*; fstrim -a; sync; systemctl poweroff"
echo "image prepared; the build user is removed and the VM powers off in ~5 s"
