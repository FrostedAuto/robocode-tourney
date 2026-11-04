#!/usr/bin/env bash
# zero-free-blocks.sh - on the Proxmox host: overwrite every free block of the image's root filesystem with
# zeros, so deleted files (old secrets, keys, logs) can't be recovered from the shared backup.
# Deleting files and fstrim are not enough: ext4 keeps reserved free blocks that still hold old data.
#
# Usage (VM stopped):  sudo bash image/zero-free-blocks.sh /dev/<vg>/vm-<vmid>-disk-0 [partition-number]
#   partition-number defaults to 1 (the root filesystem of the Ubuntu cloud image)
set -euo pipefail
DISK=${1:?usage: $0 /dev/<vg>/vm-<vmid>-disk-0 [partition]}
PART=${2:-1}
L=$(losetup -P -f --show "$DISK")
trap 'losetup -d "$L"' EXIT
P="${L}p${PART}"
findmnt -rn -S "$P" >/dev/null && { echo "$P is mounted; stop the VM first" >&2; exit 1; }
e2fsck -fp "$P" >/dev/null
dumpe2fs "$P" 2>/dev/null | sed -n 's/^  Free blocks: //p' | python3 -c "
import os, sys
bs = 4096
fd = os.open(sys.argv[1], os.O_WRONLY); z = bytes(bs * 256); n = 0
for line in sys.stdin:
    for part in line.strip().split(', '):
        if not part:
            continue
        a, _, b = part.partition('-'); a = int(a); b = int(b) if b else a
        while a <= b:
            k = min(256, b - a + 1); os.pwrite(fd, z[:bs * k], a * bs); a += k; n += k
os.fsync(fd); os.close(fd)
print('zeroed %d free blocks (%.1f GB)' % (n, n * bs / 1e9))
" "$P"
e2fsck -fn "$P" >/dev/null && echo "filesystem check: clean"
