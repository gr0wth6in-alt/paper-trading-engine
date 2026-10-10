#!/usr/bin/env bash
# Create and enable a swap file. Idempotent: safe to run again.
#   sudo bash deploy/setup-swap.sh        # 2G (default)
#   sudo bash deploy/setup-swap.sh 4G     # 4G variant
set -euo pipefail

SIZE="${1:-2G}"
SWAPFILE="${SWAPFILE:-/swapfile}"

if [[ $EUID -ne 0 ]]; then echo "Run as root (sudo)." >&2; exit 1; fi
if [[ ! "$SIZE" =~ ^[1-8]G$ ]]; then echo "Size must be 1G..8G, got $SIZE" >&2; exit 1; fi

if swapon --show=NAME --noheadings | grep -qx "$SWAPFILE"; then
  echo "$SWAPFILE is already active:"
else
  if [[ ! -f "$SWAPFILE" ]]; then
    # fallocate is fast; some filesystems (btrfs, some XFS/ZFS setups) need dd instead.
    if ! fallocate -l "$SIZE" "$SWAPFILE" 2>/dev/null; then
      rm -f "$SWAPFILE"
      dd if=/dev/zero of="$SWAPFILE" bs=1M count=$(( ${SIZE%G} * 1024 )) status=progress
    fi
  fi
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE" >/dev/null
  swapon "$SWAPFILE"
fi

grep -qE "^${SWAPFILE}[[:space:]]" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab

cat > /etc/sysctl.d/99-paper-swap.conf <<'EOF'
# Use swap only under real memory pressure; keep filesystem caches a little longer.
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl -q -p /etc/sysctl.d/99-paper-swap.conf

swapon --show
free -h
