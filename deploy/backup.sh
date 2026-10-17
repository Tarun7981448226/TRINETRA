#!/bin/zsh
# Nightly backup of everything TRINETRA knows → iCloud Drive/TRINETRA Backups (30 days kept).
# Installed as a launchd job by deploy/install-backup.sh; runs at 03:30 (or when the Mac next wakes).
set -euo pipefail
ROOT="${0:A:h:h}"
DEST="$HOME/Library/Mobile Documents/com~apple~CloudDocs/TRINETRA Backups"
URL="https://trinetra-tarun.vercel.app/export"
PASS=$(grep -E '^TRINETRA_PASSCODE=' "$ROOT/.env" | cut -d= -f2- | tr -d '"')
mkdir -p "$DEST"
OUT="$DEST/trinetra-$(date +%F).json.gz"
TMP=$(mktemp)
curl -sf --max-time 120 -H "Authorization: Bearer $PASS" "$URL" -o "$TMP"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['tables']['messages'] is not None" "$TMP"  # a real export, not an error page
gzip -c "$TMP" > "$OUT"
rm -f "$TMP"
find "$DEST" -name 'trinetra-*.json.gz' -mtime +30 -delete
echo "$(date '+%F %T') backup ok → $OUT ($(du -h "$OUT" | cut -f1))"
