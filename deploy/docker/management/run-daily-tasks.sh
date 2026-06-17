#!/bin/bash
# Wrapper that runs management/scripts/daily_tasks.sh from the correct working directory
# with the MIAB environment sourced.  Called by cron inside the management container.
source /etc/mailinabox.conf
export RUNTIME=docker
export LANGUAGE=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_TYPE=en_US.UTF-8
cd /opt/mailinabox
exec /bin/bash management/scripts/daily_tasks.sh
