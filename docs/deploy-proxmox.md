# Deploying on Proxmox VE

Two ways: **restore** a ready-made backup of the server VM, or **build** a fresh one from this repo.

## VM size and network

| | |
|---|---|
| Resources | 4 vCPU, 8 GB RAM, 32 GB disk, 1 virtio NIC. CPU type `x86-64-v2-AES` (or anything newer) |
| OS | Ubuntu Server 24.04 LTS |
| Network | DHCP on a network the lab PCs can reach |
| Ports from lab PCs | TCP **8080** (pages, uploads, downloads), **7654** (Robocode GUI), **22** (SSH admin), **445** (only for the USB fallback share) |
| Internet | Needed only while building. A running server needs none |

## A. Restore a backup (`vzdump-qemu-….vma.zst`)

A backup is a complete VM (OS included), so you don't need an empty VM first. Restoring onto an existing VM
ID replaces that VM.

1. Copy the file into the dump folder of a storage that holds backups, e.g. `/var/lib/vz/dump/` (storage
   `local`), with WinSCP or `scp`. Check its SHA256 against the one you were given: `sha256sum <file>`.
2. **Web UI:** Datacenter → that storage → *Backups* → the file → **Restore**. Pick the VM ID and the target
   storage, tick **Unique** (new MAC address) and *Start after restore*.
   **Shell:**
   ```
   qmrestore /var/lib/vz/dump/<file>.vma.zst <VMID> --storage <STORAGE> --unique 1   # add --force 1 to replace a VM
   qm set <VMID> --net0 virtio,bridge=<BRIDGE>     # only if your bridge isn't vmbr0
   qm start <VMID>
   ```
3. Open the VM's **Console**. The login screen shows the server's address. Log in with the account you were
   given, then make every secret new, so nothing from the original copy works on yours:
   ```
   sudo robo-admin rekey        # new game-server secrets, login + Samba passwords, team keys; write them down
   sudo robo-admin status       # server active, hub connected, house bots connected
   ```

The VM finds its network by itself with any MAC address.

## B. Build from this repo

1. Create a VM as above and install **Ubuntu Server 24.04** (minimal is fine; tick *OpenSSH server*). Turn on
   the QEMU guest agent option in Proxmox if you like (`setup.sh` installs the agent).
2. Log in with the user you created during the install, then:
   ```
   sudo apt update && sudo apt install -y git
   git clone https://github.com/FrostedAuto/robocode-tourney.git
   sudo bash robocode-tourney/setup.sh       # ~10 min: packages, Tank Royale 1.4.0, hub, lab kit, firewall
   sudo robo-admin secrets                   # controller secret + Samba password (new, made by setup.sh)
   ```
3. Open `http://<vm-ip>:8080/` from a lab PC.

`setup.sh` is idempotent. Run it again after a `git pull` to update; it keeps secrets, teams and results.
A fresh build makes its own secrets, so it needs no `rekey`.

## After either way

- From a lab PC: `http://<vm-ip>:8080/`, `/downloads`, `/submit` load.
- Projector PC: install the lab kit, start Robocode → Server → Server Options → remote `ws://<vm-ip>:7654`,
  controller secret from `sudo robo-admin secrets` → Battle → Start Battle: the house bots appear under
  *Joined Bots*. Run one battle; the projector page shows it.
- Take a snapshot (e.g. `event_ready`) so you can roll back mid-event.

## Admin access

- **Console:** Proxmox → the VM → Console → log in → `sudo robo-admin`.
- **SSH** from a Windows PC (OpenSSH is built in): `ssh <user>@<vm-ip>`, then `sudo robo-admin`. Password login
  is on; the first time, type `yes` to trust the server's key.
