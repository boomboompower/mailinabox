FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    # Munin master and node.
    munin munin-node \
    # libcgi-fast-perl is required by munin-cgi-graph.
    libcgi-fast-perl \
    # python3 is required by tools/editconf.py (#!/usr/bin/python3 shebang)
    python3 \
    # sudo is required by munin.sh to run munin-cron as the munin user
    sudo \
    # locales required by munin-node (Perl daemon - fails without a valid locale)
    locales \
    # Utilities used by the setup script.
    ca-certificates curl \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/monitoring/supervisord.conf /etc/supervisor/conf.d/monitoring.conf

COPY deploy/docker/monitoring/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# munin-node listens on port 4948 (internal only).
EXPOSE 4948

ENTRYPOINT ["/entrypoint.sh"]
