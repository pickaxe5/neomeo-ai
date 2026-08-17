#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [ ! -f .venv/bin/pip ]; then
  python3 -m venv --clear .venv
fi
.venv/bin/pip install -r requirements.txt python-dotenv -q

pm2 restart neomeo-ai-closure neomeo-ai-briefing
