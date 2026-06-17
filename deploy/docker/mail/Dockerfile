FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install supervisor and the runtime packages that the mail setup scripts
# install via apt.  We pre-install them here so the setup scripts run
# quickly at container start time (they will find the packages already
# present and skip apt).
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Supervisor manages multiple processes inside the container
    supervisor \
    # Core mail stack
    postfix postfix-sqlite postfix-pcre postgrey \
    dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd dovecot-sqlite sqlite3 \
    dovecot-sieve dovecot-managesieved \
    # DNS/network utilities used by setup scripts and mail tools
    ncat \
    # Python used by management tools called from mail setup.
    # python3-idna: mailconfig.py imports idna at module level - on bare metal this
    # rides in as a transitive dep of certbot, but this container never installs certbot.
    python3 python3-idna \
    # openssl CLI used by ssl.sh to generate self-signed cert
    openssl \
    # locales required for en_US.UTF-8 (Postfix, Dovecot, and Python all need it)
    locales \
    # Misc utilities
    ca-certificates curl wget git \
    # file(1) used by the postgrey whitelist cron script to verify MIME type
    file \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire MIAB repo so setup scripts can be sourced.
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
