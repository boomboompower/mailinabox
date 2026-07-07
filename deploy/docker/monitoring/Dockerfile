FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# Infrastructure packages not owned by any component def.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    # python3 is required by tools/editconf.py (#!/usr/bin/python3 shebang)
    python3 python3-pip \
    # locales required by munin-node (Perl daemon - fails without a valid locale)
    locales \
    ca-certificates curl \
    && locale-gen en_US.UTF-8 \
    && pip3 install --break-system-packages --quiet doit exclusiveprocess \
    && rm -rf /var/lib/apt/lists/*

# Copy component defs before the full source COPY so this layer is only
# invalidated when component definitions change, not on every code change.
COPY setup/components /opt/mailinabox/setup/components
WORKDIR /opt/mailinabox

# Install component packages (munin, munin-node, libcgi-fast-perl, procps, sudo).
# RUNTIME is unset here so ensure_installed() runs apt normally.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    PYTHONPATH=/opt/mailinabox/setup python3 -m components.runner --build-mode munin

COPY . /opt/mailinabox

COPY deploy/docker/monitoring/supervisord.conf /etc/supervisor/conf.d/monitoring.conf

COPY deploy/docker/monitoring/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# munin-node listens on port 4948 (internal only).
EXPOSE 4948

ENTRYPOINT ["/entrypoint.sh"]
