#!/bin/zsh
# Installs (or refreshes) the nightly iCloud backup as a launchd job for this user. Undo: deploy/install-backup.sh --remove
set -euo pipefail
ROOT="${0:A:h:h}"
PLIST="$HOME/Library/LaunchAgents/com.trinetra.backup.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
if [[ "${1:-}" == "--remove" ]]; then rm -f "$PLIST"; echo "removed"; exit 0; fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.trinetra.backup</string>
  <key>ProgramArguments</key><array><string>/bin/zsh</string><string>$ROOT/deploy/backup.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/trinetra-backup.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/trinetra-backup.log</string>
</dict></plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: nightly at 03:30 → iCloud Drive/TRINETRA Backups (log: ~/Library/Logs/trinetra-backup.log)"
