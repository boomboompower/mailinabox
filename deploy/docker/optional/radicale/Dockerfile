FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # Python venv for the Radicale installation.
    python3 python3-venv python3-pip \
    # envsubst used by radicale.sh to stamp the systemd unit file.
    gettext-base \
    ca-certificates \
    # locales required for en_US.UTF-8
    locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# Copy just the setup script so this pip layer is only invalidated when
# the Radicale package versions change, not on every source change.
COPY setup/optional/radicale.sh /tmp/radicale.sh

# Pre-install Radicale venv so container startup skips the pip install step.
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /usr/local/lib/radicale && \
    /usr/local/lib/radicale/bin/python3 -m ensurepip --upgrade && \
    /usr/local/lib/radicale/bin/pip install --upgrade pip && \
    /usr/local/lib/radicale/bin/pip install "radicale>=3.1,<4" "passlib[bcrypt]"

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

# Write the stamp so radicale.sh's needs_build check passes at startup.
RUN mkdir -p /usr/local/lib/mailinabox/stamps && \
    /bin/bash -c 'source /opt/mailinabox/setup/functions.sh && \
    hash_files /opt/mailinabox/setup/optional/radicale.sh \
        > /usr/local/lib/mailinabox/stamps/radicale-pip'

COPY deploy/docker/optional/radicale/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Radicale listens on port 5232 (internal only - nginx proxies /.well-known/caldav etc.).
EXPOSE 5232

ENTRYPOINT ["/entrypoint.sh"]
