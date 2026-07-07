#!/bin/bash
# FileBrowser container entrypoint.
#
# Runs the filebrowser component (downloads binary, writes auth hook,
# initialises database), then starts FileBrowser.
# The auth hook calls the management daemon's /auth/verify endpoint - no
# Dovecot dependency.
#
# Environment variables:
#   PRIMARY_HOSTNAME   - used by the setup script for branding
#   STORAGE_ROOT       - path to the persistent data volume
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

echo "Configuring FileBrowser..."
cd "$MIAB/setup"
python3 -m components.runner filebrowser
cd "$MIAB"

echo "FileBrowser setup complete. Starting FileBrowser and control socket server via supervisord..."
exec /usr/bin/supervisord -c /opt/mailinabox/deploy/docker/optional/filebrowser/supervisord.conf
