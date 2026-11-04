# Deploying on Proxmox VE

Two ways:

- **A. Ready-made image (recommended):** download the VM backup from the
  [Releases page](https://github.com/FrostedAuto/robocode-tourney/releases) and restore it. About 15 minutes,
  no internet needed on the VM.
- **B. Build from source:** install Ubuntu 24.04 in a VM and run `setup.sh`. About 20 minutes, needs internet.

Both give the same server. The image is simply method B followed by `image/prepare-image.sh`.

## VM size and network

| | |
|---|---|
| Resources | 4 vCPU, 8 GB RAM, 32 GB disk, 1 virtio NIC. CPU type `x86-64-v2-AES` (or anything newer) |
| OS | Ubuntu Server 24.04 LTS (included in the image) |
| Network | DHCP on a network the lab PCs can reach |
| Ports from lab PCs | TCP **8080** (pages, uploads, downloads), **7654** (Robocode GUI), **22** (SSH admin), **445** (only for the USB fallback share) |
| Proxmox | VE 9 (the image was made on 9.2; 8.x likely works but is untested) |

## A. Restore the ready-made image

The image is a complete VM (OS included), so you don't need an empty VM first. Restoring onto an existing
VM ID replaces that VM.

**1. Download** `vzdump-qemu-106-2026_11_03-17_41_12.vma.zst` (about 930 MB) and its `.sha256` from Releases.
Keep the file name: Proxmox only lists backups named `vzdump-qemu-<number>-<date>.vma.zst`. Check the hash
(SHA256 `4989098e7d92ab98161df7d8b9234a8bfa415bcfb2045fd5e34567cb265021a2`):
`sha256sum -c vzdump-qemu-106-2026_11_03-17_41_12.vma.zst.sha256` (or `Get-FileHash` in PowerShell).

**2. Copy it to the Proxmox host**, into the `dump` folder of a storage that holds backups, e.g.
`/var/lib/vz/dump/` for storage `local` (WinSCP, `scp`, or `wget <release-url>` in the host shell).

**3. Restore.**
- **Web UI:** Datacenter → that storage → *Backups* → the file → **Restore**. Choose the VM ID and target
  storage, tick **Unique** (new MAC address). Don't start it yet.
- **Shell:**
  ```
  qmrestore /var/lib/vz/dump/vzdump-qemu-106-2026_11_03-17_41_12.vma.zst <VMID> --storage <STORAGE> --unique 1
  # add --force 1 to replace an existing (e.g. empty) VM with this ID
  qm set <VMID> --net0 virtio,bridge=<BRIDGE>        # only if your bridge isn't vmbr0
  ```

**4. Set the login in Cloud-Init, then start.** The image has **no user and no password**. VM → **Cloud-Init**:
- **User:** e.g. `robo` (any name)
- **Password:** a strong one
- **SSH public key:** optional
- **IP Config:** DHCP (the default)

Then click **Regenerate Image** and **Start**. Shell equivalent:
`qm set <VMID> --ciuser robo --cipassword '<password>' --ipconfig0 ip=dhcp && qm start <VMID>`

**5. First boot (about 1 minute).** Cloud-Init creates your user and the network config, and the server
creates **its own new secrets** (controller secret, bot secret, Samba password) and SSH host keys. Open the
VM's **Console**: the login screen shows the server's address. Log in with your Cloud-Init user, then:
```
sudo robo-admin status       # server active, hub connected, 4 house bots connected
sudo robo-admin secrets      # controller secret for the Robocode GUI, Samba password
```
No `rekey` is needed: nothing in the image is shared with anyone else.

If you started it before setting the Cloud-Init user: set it, *Regenerate Image*, and reboot the VM.

## B. Build from source

1. Create a VM as above and install **Ubuntu Server 24.04** (tick *OpenSSH server*).
2. Log in with the user you created during the install, then:
   ```
   sudo apt update && sudo apt install -y git
   git clone https://github.com/FrostedAuto/robocode-tourney.git
   sudo bash robocode-tourney/setup.sh       # ~10 min: packages, Tank Royale 1.4.0, hub, lab kit, firewall
   sudo robo-admin secrets                   # controller secret + Samba password (new, made by setup.sh)
   ```
3. Open `http://<vm-ip>:8080/` from a lab PC.

`setup.sh` is idempotent. Run it again after a `git pull` to update; it keeps secrets, teams and results.

To make your own shareable image from such a build, see [image/README.md](../image/README.md).

## After either way

- From a lab PC: `http://<vm-ip>:8080/`, `/downloads` and `/submit` load.
- Projector PC: install the lab kit (from `/downloads`), start Robocode → Server → Server Options → remote
  `ws://<vm-ip>:7654`, controller secret from `sudo robo-admin secrets` → Battle → Start Battle: the house
  bots appear under *Joined Bots*. Run one battle; the projector page shows it.
- Take a snapshot (e.g. `event_ready`) so you can roll back mid-event.

## Admin access

- **Console:** Proxmox → the VM → Console → log in → `sudo robo-admin`.
- **SSH** from a Windows PC (OpenSSH is built in): `ssh <user>@<vm-ip>`, then `sudo robo-admin`. Password login
  is on; the first time, type `yes` to trust the server's key.
- New secrets at any time: `sudo robo-admin rekey`. Do it on any copy someone else has used.
