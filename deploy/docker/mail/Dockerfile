FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# Infrastructure packages not owned by any component def.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # Supervisor manages multiple processes inside the container
    supervisor \
    # Python used by management tools called from mail setup.
    # python3-idna: mailconfig.py imports idna at module level - on bare metal this
    # rides in as a transitive dep of certbot, but this container never installs certbot.
    python3 python3-pip python3-idna \
    # locales required for en_US.UTF-8 (Postfix, Dovecot, and Python all need it)
    locales \
    # Misc utilities
    ca-certificates curl wget git \
    && locale-gen en_US.UTF-8 \
    && pip3 install --break-system-packages --quiet doit exclusiveprocess \
    && rm -rf /var/lib/apt/lists/*

# Copy component defs before the full source COPY so this layer is only
# invalidated when component definitions change, not on every code change.
COPY setup/components /opt/mailinabox/setup/components
WORKDIR /opt/mailinabox

# Install component packages (postfix, dovecot, openssl, etc.) derived from
# component defs - no manual list to keep in sync.
# RUNTIME is unset here so ensure_installed() runs apt normally.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    PYTHONPATH=/opt/mailinabox/setup python3 -m components.runner --build-mode ssl postfix dovecot

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

# supervisord configuration
COPY deploy/docker/mail/supervisord.conf /etc/supervisor/conf.d/mail.conf

COPY deploy/docker/mail/handlers/ /etc/miab/handlers/
COPY deploy/docker/control-socket-server.py /usr/local/sbin/control-socket-server
COPY deploy/docker/mail/entrypoint.sh /entrypoint.sh
RUN chmod +x /usr/local/sbin/control-socket-server /etc/miab/handlers/* /entrypoint.sh

EXPOSE 25 465 587 993 4190

ENTRYPOINT ["/entrypoint.sh"]
