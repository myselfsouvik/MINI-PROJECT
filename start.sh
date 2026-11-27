#!/usr/bin/env sh
# Start the Street Dog Monitoring dashboard (macOS / Linux):
#     ./start.sh            dashboard + phone QR connection
#     ./start.sh --demo     also play the backup demo video
cd "$(dirname "$0")" || exit 1
if [ -f .venv/bin/activate ]; then
    . .venv/bin/activate
else
    echo "No .venv folder found. First-time setup:"
    echo "    python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
# Builds the dashboard the first time and after a git pull changes it (needs Node.js).
python -m backend.build_frontend
exec python -m backend.server --open --phone "$@"
