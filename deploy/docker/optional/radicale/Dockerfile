FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python venv for the Radicale installation.
    python3 python3-venv python3-pip \
    # envsubst used by radicale.sh to stamp the systemd unit file.
    gettext-base \
    ca-certificates \
    # locales required for en_US.UTF-8
    locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/optional/radicale/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Radicale listens on port 5232 (internal only - nginx proxies /.well-known/caldav etc.).
EXPOSE 5232

ENTRYPOINT ["/entrypoint.sh"]
