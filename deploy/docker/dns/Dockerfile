FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    # Authoritative DNS (public zones)
    nsd \
    # Recursive/caching resolver with DNSSEC validation (used by other containers)
    unbound unbound-anchor \
    # DNSSEC signing tools (ldns-keygen, ldns-signzone, ldns-key2ds)
    ldnsutils \
    # ssh-keyscan for SSHFP record generation
    openssh-client \
    # locales required for en_US.UTF-8
    locales \
    # Status checks
    dnsutils \
    # Misc utilities
    ca-certificates curl \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/dns/supervisord.conf /etc/supervisor/conf.d/dns.conf

COPY deploy/docker/dns/handlers/ /etc/miab/handlers/
COPY deploy/docker/control-socket-server.py /usr/local/sbin/control-socket-server
COPY deploy/docker/dns/entrypoint.sh /entrypoint.sh
RUN chmod +x /usr/local/sbin/control-socket-server /etc/miab/handlers/* /entrypoint.sh

# 53/tcp and 53/udp are exposed to the host network for public DNS.
EXPOSE 53/tcp 53/udp

ENTRYPOINT ["/entrypoint.sh"]
