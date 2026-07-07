FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    clamav \
    clamav-daemon \
    clamav-milter \
    clamav-freshclam \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/docker/optional/clamav/supervisord.conf /etc/supervisor/conf.d/clamav.conf
COPY deploy/docker/optional/clamav/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# clamav-milter TCP port (mail container connects here)
EXPOSE 7357

ENTRYPOINT ["/entrypoint.sh"]
