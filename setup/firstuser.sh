#!/bin/bash
# First admin account creation is now handled by the management daemon.
#
# - Automated installs: set MAILINABOX_BOOTSTRAP_EMAIL and
#   MAILINABOX_BOOTSTRAP_PASSWORD before starting the daemon.
# - Interactive installs: visit https://$PRIMARY_HOSTNAME/admin/ and
#   run `sudo boxctl bootstrap` to get a one-time setup code.
