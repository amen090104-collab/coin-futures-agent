#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
python -m pip install -r requirements.txt
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
