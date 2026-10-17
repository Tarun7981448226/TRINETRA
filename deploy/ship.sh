#!/usr/bin/env bash
# Ship TRINETRA to the cloud: run tests, deploy to Vercel, check it's alive.   Usage: deploy/ship.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VERCEL_TOKEN=$(grep '^VERCEL_TOKEN=' .env | cut -d= -f2-)

echo "▶ tests"
(cd backend && ../.venv/bin/python -m pytest -q)

echo "▶ deploying to Vercel"
npx --yes vercel@latest deploy --prod --yes --token "$VERCEL_TOKEN" >/dev/null

echo "▶ health"
curl -fsS https://trinetra-tarun.vercel.app/health && echo && echo "✅ TRINETRA is live: https://trinetra-tarun.vercel.app"
