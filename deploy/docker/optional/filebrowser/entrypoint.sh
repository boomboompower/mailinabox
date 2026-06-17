#!/bin/bash
# FileBrowser container entrypoint.
#
# Sources setup/optional/filebrowser.sh (which downloads the binary, writes
# the auth hook, and initialises the database), then starts FileBrowser.
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
source setup/optional/filebrowser.sh

echo "FileBrowser setup complete. Starting FileBrowser and control socket server via supervisord..."
exec /usr/bin/supervisord -c /opt/mailinabox/deploy/docker/optional/filebrowser/supervisord.conf
