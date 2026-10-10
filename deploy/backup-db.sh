#!/usr/bin/env bash
# Consistent online backup of the paper database with SQLite's backup API (safe while the
# engine runs; never copy a live WAL database file directly). Keeps the newest $KEEP copies.
#   sudo -u paper bash deploy/backup-db.sh
set -euo pipefail

APP_DIR="${PAPER_APP_DIR:-/opt/paper-trading-engine}"
DB="${PAPER_BACKUP_DB:-$APP_DIR/data/paper-hermes.db}"
DEST="${PAPER_BACKUP_DIR:-$APP_DIR/data/backups}"
KEEP="${PAPER_BACKUP_KEEP:-14}"

umask 077
mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$DEST/$(basename "${DB%.db}")-$STAMP.db"

"$APP_DIR/.venv/bin/python" - "$DB" "$TARGET" <<'PY'
import sqlite3, sys
source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
check = target.execute("PRAGMA integrity_check").fetchone()[0]
target.close(); source.close()
if check != "ok":
    sys.exit(f"integrity_check failed: {check}")
PY

ls -1t "$DEST"/*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "Backup written: $TARGET"
