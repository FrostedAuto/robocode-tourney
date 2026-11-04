# Making the shareable Proxmox image

The image on the Releases page is made like this, so anyone can rebuild it and check that it matches the
source. Nothing in it comes from a server that has been used: it is a fresh build that has never held a
secret anyone else knows.

1. **VM:** Ubuntu 24.04 cloud image (`noble-server-cloudimg-amd64.img` from cloud-images.ubuntu.com),
   4 vCPU, 8 GB, 32 GB disk on VirtIO SCSI, virtio NIC, CPU `x86-64-v2-AES`, a Cloud-Init drive, QEMU guest
   agent on. A temporary build user from Cloud-Init.
2. **Build:** copy this repo onto it and run `sudo bash setup.sh` (installs everything and builds the lab kit).
3. **Prepare:** `sudo bash image/prepare-image.sh`. It deletes:
   - the secrets and the Samba password
   - all teams, results and logs
   - the SSH host keys and the machine ID
   - the cloud-init state
   - the build user

   It also enables SSH password login for the future Cloud-Init user, writes the console banner, and powers
   off.
4. **On the Proxmox host:** overwrite the free space with zeros (deleted files otherwise survive in ext4's
   reserved free blocks, and we found old secrets and keys there), remove the build login from the VM
   config, then back it up:
   ```
   sudo bash image/zero-free-blocks.sh /dev/<vg>/vm-<VMID>-disk-0
   qm set <VMID> --delete ciuser,cipassword,sshkeys,cicustom
   qm set <VMID> --description "Robocode Tank Royale tournament server (github.com/FrostedAuto/robocode-tourney)"
   vzdump <VMID> --mode stop --compress zstd --storage <backup-storage>
   sha256sum <file>.vma.zst > <file>.vma.zst.sha256
   ```
5. **Check:**
   - restore the image to a new VM, set a Cloud-Init user, start it, log in
   - `sudo robo-admin status`
   - run `tests/rehearse.py`
   - search the whole backup stream for any old secret, e.g.
     `zstd -dc <file>.vma.zst | grep -a -c -E "(CONTROLLER|BOT|SERVER)_SECRET=[A-Za-z0-9]{20}"` must print 0

On first start of a restored copy, `robocode-firstboot.service` creates new secrets, a Samba password and SSH
host keys (it runs only while `/opt/robocode/secrets.env` is missing), and Cloud-Init creates the login.
