#!/bin/bash
# Radicale CardDAV/CalDAV container entrypoint.
#
# Writes /etc/mailinabox.conf from env vars, then runs the component runner
# for the radicale component (venv, plugin, config, log, namespace steps).
# The component reads MANAGEMENT_HOST and RUNTIME from the conf file and
# writes /etc/radicale/config with the correct bind address and management
# host - no sed patching needed.
#
# Environment variables:
#   PRIMARY_HOSTNAME   - required by write_mailinabox_conf
#   STORAGE_ROOT       - path to persistent data volume
#   MANAGEMENT_HOST    - management container service name (default: management)
#   WEBMAIL_CLIENT     - which webmail is running (default: oxi); controls
#                        whether the oxi SQLite storage plugin is used

set -euo pipefail

MIAB=/opt/mailinabox
source "$MIAB/deploy/docker/common-entrypoint.sh"

install_systemctl_stub
write_mailinabox_conf

export RUNTIME=docker
export LANGUAGE=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_TYPE=en_US.UTF-8

source /etc/mailinabox.conf
mkdir -p "$STORAGE_ROOT"

echo "Configuring Radicale..."
cd "$MIAB/setup"
python3 -m components.runner radicale

echo "Radicale setup complete. Starting Radicale..."

# OXI_DATA_DIR is only needed when using the oxi SQLite storage backend.
if [ "${WEBMAIL_CLIENT:-oxi}" = "oxi" ]; then
    export OXI_DATA_DIR="$STORAGE_ROOT/oxi"
fi

# The radicale_miab plugin lives outside the venv; mirror what the systemd unit sets.
export PYTHONPATH=/usr/local/lib/radicale-miab
exec /usr/local/lib/radicale/bin/python3 -m radicale \
    --config /etc/radicale/config
