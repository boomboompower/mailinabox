#!/bin/bash
# Munin monitoring container entrypoint.
#
# Sources setup/monitoring/munin.sh to write the Munin configuration and
# activate plugins, then starts munin and munin-node via supervisord.

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

# Redirect munin's HTML output to the shared storage volume so the management
# daemon (on a separate container) can serve it at /admin/munin/.
mkdir -p "$STORAGE_ROOT/munin/www"
chown munin:munin "$STORAGE_ROOT/munin/www" 2>/dev/null || true
rm -rf /var/cache/munin/www
mkdir -p /var/cache/munin
ln -sfn "$STORAGE_ROOT/munin/www" /var/cache/munin/www

echo "Configuring Munin..."
source setup/monitoring/munin.sh

echo "Munin setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
