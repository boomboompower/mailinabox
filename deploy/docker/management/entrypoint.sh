#!/bin/bash
# Management container entrypoint.
#
# Gunicorn starts immediately using the pre-built start script (copied into
# the image at build time). The management component and web_update.py run in
# the background - nginx waits for local.conf to appear before it serves,
# so config generation can happen asynchronously without delaying the API.

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

# Symlink /etc paths that management writes onto the shared storage volume
# so that service containers (dns, mail, nginx) can read the same files.
link_conf_to_storage /etc/nsd nsd
mkdir -p /etc/nsd/nsd.conf.d
link_conf_to_storage /etc/nginx/conf.d nginx/conf.d
if [ "${SPAM_FILTER:-rspamd}" = "spamassassin" ]; then
    link_conf_to_storage /etc/opendkim opendkim
fi

# Symlink munin HTML dir so the management daemon can serve files generated
# by the munin container, which writes to the same storage volume path.
mkdir -p "$STORAGE_ROOT/munin/www" /var/cache/munin
ln -sfn "$STORAGE_ROOT/munin/www" /var/cache/munin/www

# Ensure the mail storage directory and database schema exist before gunicorn
# starts. open_database() in mailconfig.py is a plain connect - it does not
# create tables - so this must happen here, synchronously, before any request.
mkdir -p "$STORAGE_ROOT/mail"
source /usr/local/lib/mailinabox/env/bin/activate
python3 -c "
import sys; sys.path.insert(0, '$MIAB/management')
from core import utils
from mail import mailconfig
env = utils.load_environment()
mailconfig.initialize_database(env)
"
deactivate

# Run setup and nginx config generation in the background so gunicorn
# starts without any delay. nginx waits for local.conf to appear.
(
    echo "[management-setup] Running component runner..."
    cd "$MIAB/setup"
    python3 -m components.runner management
    cd "$MIAB"

    echo "[management-setup] Writing nginx config (web_update)..."
    source /usr/local/lib/mailinabox/env/bin/activate
    cd "$MIAB/management" && python3 -c "
from core import utils
from services import web_update
env = utils.load_environment()
web_update.do_web_update(env)
print('[management-setup] nginx config written to /etc/nginx/conf.d/local.conf')
"
) &
disown

# Generate secret key if it doesn't exist yet. This is used for signing cookies and other secrets.
KEY_FILE="$STORAGE_ROOT/backup/secret_key.txt"

if [ ! -f "$KEY_FILE" ]; then
    echo "[management-setup] Generating secret key..."
    mkdir -p "$(dirname "$KEY_FILE")"
    tmpfile=$(mktemp "$STORAGE_ROOT/backup/secret_key.XXXXXX")
    openssl rand -base64 64 > "$tmpfile" || { echo "Failed to generate secret key"; exit 1; }
    chmod 600 "$tmpfile"
    mv "$tmpfile" "$KEY_FILE"
    echo "[management-setup] Secret key generated."
fi

# Start cron for nightly maintenance tasks (backup, cert renewal, status checks).
# cron runs as a background daemon; gunicorn (below) becomes PID 1 via exec.
cron

echo "Starting management daemon..."
exec /usr/local/lib/mailinabox/start
