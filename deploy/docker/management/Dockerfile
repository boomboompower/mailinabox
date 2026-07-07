FROM oven/bun:latest AS frontend-builder

# Copy only the frontend source so this layer is only invalidated when
# frontend files change, not when setup scripts or other repo files change.
COPY frontend/ /frontend/

RUN --mount=type=cache,target=/root/.bun/install/cache \
    cd /frontend && bun install --frozen-lockfile && bunx vite build

# ---------------------------------------------------------------------------
# venv-builder: creates the Python virtualenv and pip-installs management deps.
# Runs in parallel with the main stage's apt bootstrap (the slowest step).
# Needs gcc/python3-dev to compile C extensions (psutil, fido2).
# The compiled venv is copied into the final image; gcc/python3-dev are not.

FROM ubuntu:26.04 AS venv-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # Python runtime for the venv and pip
    python3 python3-pip \
    # gcc + python3-dev: compile C extensions (psutil, fido2, cryptography)
    gcc python3-dev \
    # virtualenv: creates the isolated venv that ships into the final image
    virtualenv \
    # libxml2-dev + libxslt1-dev: lxml compile-time headers (not needed at runtime)
    libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages --quiet doit exclusiveprocess

COPY setup/components /opt/mailinabox/setup/components
WORKDIR /opt/mailinabox

# Run venv creation + pip install only (no apt - packages are above).
# Writes .doit.db with uptodate records so the main stage runner skips these tasks.
RUN --mount=type=cache,target=/root/.cache/pip \
    PYTHONPATH=/opt/mailinabox/setup python3 -m components.runner \
    --build-mode --skip-packages management

# ---------------------------------------------------------------------------

FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

ARG BACKUP_TOOL=restic

# Bootstrap: minimal set of packages needed before the component runner.
# gcc/python3-dev are in venv-builder instead (C extension compilation happens there).
# cron/ldnsutils/python3-idna are now in COMPONENT.packages (installed by the runner below).
# git is not needed - Docker images have no .git dir and the version file is written at runtime.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # Python runtime - venv is imported from venv-builder, but python3 is still needed to run it
    python3 python3-pip \
    # locales: management daemon requires en_US.UTF-8 for email header handling
    locales \
    # curl: used by backup and cert renewal scripts; ca-certificates: TLS trust store
    curl ca-certificates \
    # gnupg: duplicity uses GPG for backup encryption; not needed for restic
    $([ "$BACKUP_TOOL" = "duplicity" ] && echo gnupg) \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages --quiet doit exclusiveprocess

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Copy component defs before the full source COPY so this apt+pip layer is only
# invalidated when component definitions change, not on every code change.
COPY setup/components /opt/mailinabox/setup/components
WORKDIR /opt/mailinabox

# Import the pre-built venv from the parallel builder stage.
# .doit.db carries the uptodate records for virtualenv + pip-install, so the
# component runner below only runs the apt install step for those tasks.
COPY --from=venv-builder /usr/local/lib/mailinabox/env /usr/local/lib/mailinabox/env
COPY --from=venv-builder /usr/local/lib/mailinabox/setup-state.db /usr/local/lib/mailinabox/setup-state.db

# Install component packages (apt) - venv/pip tasks are already done (skipped by doit).
# RUNTIME is unset here so ensure_installed() runs apt normally.
# $BACKUP_TOOL is passed as a component name (restic or duplicity).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    PYTHONPATH=/opt/mailinabox/setup python3 -m components.runner --build-mode management $BACKUP_TOOL

# Pre-write the gunicorn start script so the entrypoint can exec it immediately
# without waiting for the management component to run. Bound to 0.0.0.0 so nginx
# (in a separate container) can reach port 10222 over the Docker bridge.
COPY deploy/docker/management/start.sh /usr/local/lib/mailinabox/start
COPY deploy/docker/management/run-daily-tasks.sh /usr/local/lib/mailinabox/run-daily-tasks.sh
COPY deploy/docker/management/miab-daily /etc/cron.d/miab-daily
RUN chmod +x /usr/local/lib/mailinabox/start /usr/local/lib/mailinabox/run-daily-tasks.sh \
    && chmod 0644 /etc/cron.d/miab-daily

COPY . /opt/mailinabox

# Overwrite with the pre-built output from the builder stage.
# Vite writes to frontend/dist/app (outDir: 'dist/app' in vite.config.ts). The
# daemon's Flask static_folder points at frontend/dist and serves this 'app'
# subfolder, so frontend/ and management/ never need to know about each other's layout.
COPY --from=frontend-builder /frontend/dist/app /opt/mailinabox/frontend/dist/app

COPY deploy/docker/management/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ARG GIT_SHA=unknown
RUN mkdir -p /usr/local/share/mailinabox && echo "$GIT_SHA" > /usr/local/share/mailinabox/version

# Management API port - must be reachable from nginx (on the Docker bridge).
EXPOSE 10222

ENTRYPOINT ["/entrypoint.sh"]
