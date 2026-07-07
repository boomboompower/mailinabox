#!/bin/bash
# Wrapper that runs daily_tasks.py from the correct working directory
# with the MIAB environment sourced. Called by cron inside the management container.
source /etc/mailinabox.conf
export RUNTIME=docker
cd /opt/mailinabox
exec management/scripts/daily_tasks.py
