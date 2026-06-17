FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    rspamd \
    # Setup script dependencies
    python3 python3-idna \
    # locales required for en_US.UTF-8
    locales \
    ca-certificates curl wget git \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/rspamd/supervisord.conf /etc/supervisor/conf.d/rspamd.conf
COPY deploy/docker/rspamd/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Milter port (Postfix connects here) and controller port (rspamadm/web UI)
EXPOSE 11332 11334

ENTRYPOINT ["/entrypoint.sh"]
