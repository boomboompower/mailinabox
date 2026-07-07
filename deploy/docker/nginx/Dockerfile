FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# Infrastructure packages not owned by any component def.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # python3 is required by tools/editconf.py and control-socket-server
    python3 python3-pip \
    # supervisor manages nginx + control socket server
    supervisor \
    ca-certificates curl \
    # locales required for en_US.UTF-8
    locales \
    && locale-gen en_US.UTF-8 \
    && pip3 install --break-system-packages --quiet doit exclusiveprocess \
    && rm -rf /var/lib/apt/lists/*

# Copy component defs before the full source COPY so this layer is only
# invalidated when component definitions change, not on every code change.
COPY setup/components /opt/mailinabox/setup/components
WORKDIR /opt/mailinabox

# Install component packages (nginx, idn2).
# RUNTIME is unset here so ensure_installed() runs apt normally.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    PYTHONPATH=/opt/mailinabox/setup python3 -m components.runner --build-mode web

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/nginx/supervisord.conf /etc/supervisor/conf.d/nginx.conf
COPY deploy/docker/nginx/handlers/ /etc/miab/handlers/
COPY deploy/docker/control-socket-server.py /usr/local/sbin/control-socket-server
COPY deploy/docker/nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /usr/local/sbin/control-socket-server /etc/miab/handlers/* /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
