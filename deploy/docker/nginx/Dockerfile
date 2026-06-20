FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    # idn2 for internationalised domain name handling in web.sh
    idn2 \
    # python3 is required by tools/editconf.py and control-socket-server
    python3 \
    # supervisor manages nginx + control socket server
    supervisor \
    ca-certificates curl \
    # locales required for en_US.UTF-8
    locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/nginx/supervisord.conf /etc/supervisor/conf.d/nginx.conf
COPY deploy/docker/nginx/handlers/ /etc/miab/handlers/
COPY deploy/docker/control-socket-server.py /usr/local/sbin/control-socket-server
COPY deploy/docker/nginx/entrypoint.sh /entrypoint.sh
RUN chmod +x /usr/local/sbin/control-socket-server /etc/miab/handlers/* /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
