#!/bin/bash
# Radicale CardDAV/CalDAV container entrypoint.
#
# Sources setup/optional/radicale.sh to install the Python venv, write the
# auth/storage plugins, and generate /etc/radicale/config.  After that, patches
# the management_host in the config so the auth plugin connects to the management
# container instead of 127.0.0.1.
#
# Environment variables:
#   PRIMARY_HOSTNAME   - required by write_mailinabox_conf
#   STORAGE_ROOT       - path to persistent data volume
#   MANAGEMENT_HOST    - management container service name (default: management)

set -euo pipefail

MIAB=/opt/mailinabox
source "$MIAB/deploy/docker/common-entrypoint.sh"

install_systemctl_stub
write_mailinabox_conf

export RUNTIME=docker

cd "$MIAB"

export LANGUAGE=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_TYPE=en_US.UTF-8

source /etc/mailinabox.conf
mkdir -p "$STORAGE_ROOT"

echo "Configuring Radicale..."
source setup/optional/radicale.sh

# Patch /etc/radicale/config for the Docker environment:
# 1. The server must bind to 0.0.0.0 so nginx (in a separate container) can
#    reach it over the Docker bridge.
# 2. The management_host must point to the management container, not 127.0.0.1.
sed -i 's/^hosts = 127\.0\.0\.1:/hosts = 0.0.0.0:/' /etc/radicale/config

MANAGEMENT_HOST="${MANAGEMENT_HOST:-management}"
if [ "$MANAGEMENT_HOST" != "127.0.0.1" ]; then
    sed -i "s/^management_host = .*/management_host = ${MANAGEMENT_HOST}/" /etc/radicale/config
fi

# OXI_DATA_DIR is required by the storage plugin to locate user SQLite databases.
export OXI_DATA_DIR="$STORAGE_ROOT/oxi"

echo "Radicale setup complete. Starting Radicale..."
# The radicale_miab plugin lives outside the venv; mirror what the systemd unit sets.
export PYTHONPATH=/usr/local/lib/radicale-miab
exec /usr/local/lib/radicale/bin/python3 -m radicale \
    --config /etc/radicale/config
