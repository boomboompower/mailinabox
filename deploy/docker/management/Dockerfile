FROM ubuntu:24.04 AS frontend-builder

ENV DEBIAN_FRONTEND=noninteractive

# Install Node.js only in the builder stage - not needed at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy only the frontend source so this layer is only invalidated when
# frontend files change, not when setup scripts or other repo files change.
# Vite outDir is self-contained (dist/app, relative to frontend/) - no need to
# copy management/ into this stage at all.
COPY frontend/ /frontend/

RUN cd /frontend && npm ci --prefer-offline && npm run build

# ---------------------------------------------------------------------------

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python runtime and pip for management daemon dependencies
    python3 python3-pip virtualenv \
    # certbot for TLS certificate provisioning
    certbot \
    # rsync used by backup tasks
    rsync \
    # gnupg required by duplicity for backup encryption
    gnupg \
    # ncat used by start.sh to wait for the daemon
    ncat \
    # cron runs daily_tasks.sh for backup, cert renewal, status checks
    cron \
    # envsubst used by setup scripts to stamp service unit files
    gettext-base \
    # gcc + python3-dev needed to compile C extensions in the venv (psutil, fido2, netifaces)
    gcc python3-dev \
    # ldnsutils: ldns-signzone is called by dns_update.py when users/domains change
    ldnsutils \
    # restic: backup backend used when BACKUP_TOOL=restic (see management/services/backup/)
    restic \
    locales \
    curl git ca-certificates \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Pre-install Python packages BEFORE copying source so this layer is cached
# across source-file changes and only reruns when the package list changes.
# Keep this list in sync with the pip install block in setup/management.sh.
RUN mkdir -p /usr/local/lib/mailinabox/stamps && \
    virtualenv /usr/local/lib/mailinabox/env && \
    /usr/local/lib/mailinabox/env/bin/pip install --upgrade --quiet --no-compile --prefer-binary \
        rtyaml "email_validator>=1.0.0" "exclusiveprocess" \
        flask dnspython python-dateutil expiringdict gunicorn \
        "qrcode[pil]" pyotp "fido2>=1.0" \
        "idna>=2.0.0" "cryptography>=41.0.0" psutil postfix-mta-sts-resolver \
        "duplicity>=1.0" b2sdk boto3 \
        "passlib[bcrypt]"

# Pre-write the gunicorn start script so the entrypoint can exec it immediately
# without waiting for setup/management.sh to run. Bound to 0.0.0.0 so nginx
# (in a separate container) can reach port 10222 over the Docker bridge.
COPY deploy/docker/management/start.sh /usr/local/lib/mailinabox/start
COPY deploy/docker/management/run-daily-tasks.sh /usr/local/lib/mailinabox/run-daily-tasks.sh
RUN chmod +x /usr/local/lib/mailinabox/start /usr/local/lib/mailinabox/run-daily-tasks.sh

COPY deploy/docker/management/miab-daily /etc/cron.d/miab-daily
RUN chmod 0644 /etc/cron.d/miab-daily

COPY . /opt/mailinabox

# Overwrite with the pre-built output from the builder stage.
# Vite writes to frontend/dist/app (outDir: 'dist/app' in vite.config.ts). The
# daemon's Flask static_folder points at frontend/dist and serves this 'app'
# subfolder, so frontend/ and management/ never need to know about each other's layout.
COPY --from=frontend-builder /frontend/dist/app /opt/mailinabox/frontend/dist/app

WORKDIR /opt/mailinabox

# Write stamps after source is copied so management.sh skips pip install and
# Vue build on container startup.  Use hash_files() from functions.sh with
# absolute paths so the computed value matches exactly what management.sh
# produces at runtime (sha256sum includes the filename in its output, so
# relative vs absolute paths produce different hashes).
RUN /bin/bash -c '\
    source /opt/mailinabox/setup/functions.sh && \
    hash_files /opt/mailinabox/setup/management.sh \
        > /usr/local/lib/mailinabox/stamps/management-pip && \
    hash_files /opt/mailinabox/frontend \
        > /usr/local/lib/mailinabox/stamps/management-frontend'

COPY deploy/docker/management/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Management API port - must be reachable from nginx (on the Docker bridge).
EXPOSE 10222

ENTRYPOINT ["/entrypoint.sh"]
