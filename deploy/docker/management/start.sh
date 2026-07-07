#!/bin/bash
# Management daemon start script.
# Pre-written at image build time so gunicorn starts immediately at container
# startup without waiting for the management component to run.
# The component also writes this file and may overwrite it - that is fine
# because exec has already happened by then.

export LANGUAGE=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_TYPE=en_US.UTF-8

mkdir -p /var/lib/mailinabox
tr -cd '[:xdigit:]' < /dev/urandom | head -c 32 > /var/lib/mailinabox/api.key
chmod 640 /var/lib/mailinabox/api.key

source /usr/local/lib/mailinabox/env/bin/activate
export PYTHONPATH=/opt/mailinabox/management
exec gunicorn -b 0.0.0.0:10222 -w 1 --timeout 630 core.wsgi:app
