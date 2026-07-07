# oxi.email webmail
#
# Backend binary + built frontend are fetched as a single prebuilt release
# tarball from boomboompower/oxi-miab's release CI - nothing is compiled here.

FROM ubuntu:26.04

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive

# Runtime shared libraries only - no build tools, no Rust, no Bun.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget \
    libssl3 libsqlite3-0 \
    # sudo to drop to www-data when starting the server
    sudo \
    # locales required for en_US.UTF-8
    locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# Pinned prebuilt release - keep these three in sync with
# setup/components/defs/oxi.py's OXI_VERSION/OXI_ASSET/OXI_SHA256. The hash is
# copied here from that release's checksums.txt, not fetched at build time -
# fetching it from the same place as the binary would give a compromised
# release nothing independent to be caught by.
ARG OXI_VERSION="v0.1.0+2122fe6"
ARG OXI_ASSET="oxi-email-server-linux-x86_64.tar.gz"
ARG OXI_SHA256="0d0dc2c0677383dbe65a50cd5052b66cfc0e281cb837a6e1c3cd2aade4c2a537"

RUN set -euo pipefail && \
    OXI_URL="https://github.com/boomboompower/oxi-miab/releases/download/${OXI_VERSION//+/%2B}/${OXI_ASSET}" && \
    wget -O /tmp/oxi.tar.gz "$OXI_URL" && \
    echo "${OXI_SHA256}  /tmp/oxi.tar.gz" | sha256sum --check --strict && \
    mkdir -p /tmp/oxi-extract && \
    tar -xzf /tmp/oxi.tar.gz -C /tmp/oxi-extract && \
    mv /tmp/oxi-extract/oxi-email-server /usr/local/bin/oxi-email-server && \
    chmod 755 /usr/local/bin/oxi-email-server && \
    mkdir -p /usr/local/share/oxi-email/static && \
    cp -a /tmp/oxi-extract/static/. /usr/local/share/oxi-email/static/ && \
    rm -rf /tmp/oxi.tar.gz /tmp/oxi-extract

# Copy the MIAB repo so the entrypoint has access to shared helpers
# (common-entrypoint.sh) and the storage volume config path.
COPY . /opt/mailinabox
WORKDIR /opt/mailinabox

COPY deploy/docker/webmail/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# oxi listens on port 3001 by default.
EXPOSE 3001

ENTRYPOINT ["/entrypoint.sh"]
