#!/usr/bin/env sh
# Start the Street Dog Monitoring dashboard (macOS / Linux):
#     ./start.sh            dashboard + phone QR connection
#     ./start.sh --demo     also play the backup demo video
# The first run sets everything up by itself (needs internet once). Only Python 3.10+ is needed.
cd "$(dirname "$0")" || exit 1

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=""
    for candidate in python3.11 python3.12 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>/dev/null; then
            PY="$candidate"
            break
        fi
    done
    if [ -z "$PY" ]; then
        echo "DogWatch needs Python 3.10 or newer (3.11 recommended)."
        echo "  macOS:          brew install python@3.11   (or https://www.python.org/downloads/)"
        echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv"
        exit 1
    fi
fi

"$PY" backend/setup_env.py || exit 1
. .venv/bin/activate
# The dashboard comes ready-built. This rebuilds it only if its code changed and Node.js is installed.
python -m backend.build_frontend
exec python -m backend.server --open --phone "$@"
