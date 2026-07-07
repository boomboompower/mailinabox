FROM debian:bookworm-slim

ARG BESZEL_VERSION=0.18.7
ARG BESZEL_AGENT_SHA256=4ae327aac5ad5a231845b0ef613066d555bbe52f7ecb2f28a53d07c04e689aff

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/henrygd/beszel/releases/download/v${BESZEL_VERSION}/beszel-agent_linux_amd64.tar.gz" \
        -o /tmp/beszel-agent.tar.gz \
    && echo "${BESZEL_AGENT_SHA256}  /tmp/beszel-agent.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/beszel-agent.tar.gz -C /usr/local/bin beszel-agent \
    && chmod +x /usr/local/bin/beszel-agent \
    && rm /tmp/beszel-agent.tar.gz

COPY deploy/docker/beszel-agent/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 45876

ENTRYPOINT ["/entrypoint.sh"]
