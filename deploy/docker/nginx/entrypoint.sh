#!/bin/bash
# Nginx container entrypoint.
#
# Runs nginx in the foreground (single process - no supervisord needed).
# The nginx configuration is written by the management daemon's web_update
# tool, so nginx may be reloaded via 'nginx -s reload' at runtime.

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

link_conf_to_storage /etc/nginx/conf.d nginx/conf.d

echo "Configuring nginx..."
cd "$MIAB/setup"
python3 -m components.runner web
cd "$MIAB"

echo "Nginx setup complete. Waiting for management to write local.conf..."
# web_update.py (running in the management container) writes local.conf to the
# shared nginx-conf volume.  Without it nginx has no server blocks and won't
# listen on any port.
_deadline=$((SECONDS + 300))
until [ -f /etc/nginx/conf.d/local.conf ]; do
    if [ $SECONDS -ge $_deadline ]; then
        echo "ERROR: timed out after 300s waiting for management to write local.conf" >&2
        exit 1
    fi
    sleep 2
done
unset _deadline

echo "Starting nginx and control socket server via supervisord..."
exec /usr/bin/supervisord -c /opt/mailinabox/deploy/docker/nginx/supervisord.conf
