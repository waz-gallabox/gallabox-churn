#!/usr/bin/env bash
# Backup PocketBase data directory.
# Usage: ./backup_pb.sh [backup_dir]
# Default backup_dir: ~/gallabox_churn_backups

set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${1:-$HOME/gallabox_churn_backups}"
mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/pb_data_$STAMP.tar.gz"

tar -czf "$DEST" -C "$REPO" pb_data/
echo "Backup saved: $DEST ($(du -sh "$DEST" | cut -f1))"

# Keep last 7 backups
ls -t "$BACKUP_DIR"/pb_data_*.tar.gz 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true
