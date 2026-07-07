#!/bin/bash
set -e

STORAGE_ROOT="${STORAGE_ROOT:-/home/user-data}"
AGENT_ENV="${STORAGE_ROOT}/beszel/agent.env"

for i in $(seq 1 30); do
    [ -f "$AGENT_ENV" ] && break
    echo "Waiting for ${AGENT_ENV}..."
    sleep 2
done

if [ ! -f "$AGENT_ENV" ]; then
    echo "ERROR: ${AGENT_ENV} not found after 60s - management setup may have failed." >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$AGENT_ENV"
set +a

exec beszel-agent
