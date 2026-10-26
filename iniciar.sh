#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! python3 run.py --json doctor >/dev/null 2>&1; then
    python3 run.py setup
fi
exec python3 run.py "$@"
