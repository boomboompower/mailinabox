#!/bin/bash
set -e

STORAGE_ROOT="${STORAGE_ROOT:-/home/user-data}"
HUB_ENV="${STORAGE_ROOT}/beszel/hub.env"

# Wait for management to write credentials (keygen step runs during setup).
for i in $(seq 1 30); do
    [ -f "$HUB_ENV" ] && break
    echo "Waiting for ${HUB_ENV}..."
    sleep 2
done

if [ ! -f "$HUB_ENV" ]; then
    echo "ERROR: ${HUB_ENV} not found after 60s - management setup may have failed." >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$HUB_ENV"
set +a

exec beszel serve --http "0.0.0.0:8090" --dir "${STORAGE_ROOT}/beszel"
