FROM debian:bookworm-slim

ARG BESZEL_VERSION=0.18.7
ARG BESZEL_SHA256=b75c52a82af5c9721f08a7a9cb0c16df27e81967a3855cef7c77dbad9fb43524

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/henrygd/beszel/releases/download/v${BESZEL_VERSION}/beszel_linux_amd64.tar.gz" \
        -o /tmp/beszel.tar.gz \
    && echo "${BESZEL_SHA256}  /tmp/beszel.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/beszel.tar.gz -C /usr/local/bin beszel \
    && chmod +x /usr/local/bin/beszel \
    && rm /tmp/beszel.tar.gz

COPY deploy/docker/beszel-hub/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8090

ENTRYPOINT ["/entrypoint.sh"]
