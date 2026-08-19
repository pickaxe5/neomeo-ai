#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [ ! -f .venv/bin/pip ]; then
  python3 -m venv --clear .venv
fi
.venv/bin/pip install -r requirements.txt python-dotenv -q

pm2 restart neomeo-ai-closure neomeo-ai-briefing

# personal-progress는 이번에 새로 추가된 프로세스라 서버에 아직 없을 수 있음 —
# 없으면 시작하고, 있으면 재시작한다 (pm2 restart는 미존재 프로세스에 실패하므로).
pm2 describe neomeo-ai-personal-progress > /dev/null 2>&1 \
  && pm2 restart neomeo-ai-personal-progress \
  || pm2 start pipeline/run_personal_progress_fill.py \
       --name neomeo-ai-personal-progress \
       --interpreter .venv/bin/python
