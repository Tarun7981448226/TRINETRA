#!/usr/bin/env bash
# Free Vercel's Function Storage (10 GB on the free plan): every deploy keeps its own ~70 MB copy of the server.
# Keeps the newest KEEP deploys (the live one is always the newest) and removes the rest.
# Usage: bash deploy/prune.sh            (asks before removing)
#        KEEP=5 bash deploy/prune.sh --yes
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP="${KEEP:-5}"
VERCEL_TOKEN=$(grep '^VERCEL_TOKEN=' .env | cut -d= -f2-)
vc() { npx --yes vercel@latest "$@" --token "$VERCEL_TOKEN" 2>&1 | sed -E 's/vcp_[A-Za-z0-9]+/***/g'; }

all=() next=()
while :; do
  out=$(vc ls trinetra ${next[@]+"${next[@]}"})
  while read -r u; do all+=("$u"); done < <(grep -o 'https://trinetra-[a-z0-9]*-tarun-74c3\.vercel\.app' <<<"$out")
  n=$(grep -o -- '--next [0-9]*' <<<"$out" | head -1 || true)
  [ -z "$n" ] && break
  read -r -a next <<<"$n"
done

uniq=()  # each deploy appears twice in the listing
while read -r u; do uniq+=("$u"); done < <(printf '%s\n' "${all[@]}" | awk '!seen[$0]++')
all=("${uniq[@]}")

live=$(vc inspect trinetra-tarun.vercel.app | awk '$1 == "url" {print $2; exit}')
echo "deploys: ${#all[@]}  live: $live  keeping the newest $KEEP"
old=()
for u in "${all[@]:$KEEP}"; do [ "$u" != "$live" ] && old+=("$u"); done
[ ${#old[@]} -eq 0 ] && { echo "nothing to remove"; exit 0; }

if [ "${1:-}" != "--yes" ]; then
  read -r -p "remove ${#old[@]} old deploys? [y/N] " ok
  [ "$ok" = "y" ] || { echo "cancelled"; exit 0; }
fi
for ((i = 0; i < ${#old[@]}; i += 20)); do
  vc rm "${old[@]:i:20}" --yes | grep -iE 'removed|error' || true
done
echo "done — the live site was not touched"
