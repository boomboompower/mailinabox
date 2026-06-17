#!/bin/bash
# Webmail with oxi.email
# ----------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing oxi.email (webmail)..."

apt_install_cached "webmail" ca-certificates

# Remove a Rust toolchain installed by a previous version of this script.
# oxi is now fetched as a prebuilt release - nothing is compiled on the box.
if [ -f /etc/profile.d/cargo.sh ]; then
	rm -f /etc/profile.d/cargo.sh
fi

# Pinned prebuilt release - backend binary + built frontend, bundled together
# in one tar.gz by oxi-miab's release CI (github.com/boomboompower/oxi-miab).
# Update OXI_VERSION/OXI_ASSET/OXI_SHA256 together when upgrading. The hash
# must be copied here from that release's checksums.txt, not fetched at
# install time - fetching the hash from the same place as the binary would
# mean a compromised release could ship a tampered binary and a matching
# tampered hash with nothing independent left to catch it.
OXI_VERSION="v0.1.0+2122fe6"
OXI_ASSET="oxi-email-server-linux-x86_64.tar.gz"
OXI_SHA256="0d0dc2c0677383dbe65a50cd5052b66cfc0e281cb837a6e1c3cd2aade4c2a537"
OXI_URL="https://github.com/boomboompower/oxi-miab/releases/download/${OXI_VERSION//+/%2B}/$OXI_ASSET"

OXI_STATIC_DIR=/usr/local/share/oxi-email/static
_OXI_STAMP=/usr/local/share/oxi-email.version

# Skip download if the installed version already matches. We use a stamp
# file rather than asking the binary its own version, to avoid depending on
# how/whether it reports that.
needs_update=0
if [ ! -x /usr/local/bin/oxi-email-server ]; then
	needs_update=1
elif [ ! -f "$_OXI_STAMP" ] || [ "$(cat "$_OXI_STAMP")" != "$OXI_VERSION" ]; then
	needs_update=1
fi

if [ "$needs_update" = "1" ]; then
	echo "Fetching oxi.email $OXI_VERSION (prebuilt)..."
	wget_verify_sha256 "$OXI_URL" "$OXI_SHA256" /tmp/oxi-email-server.tar.gz

	_OXI_EXTRACT=$(mktemp -d)
	tar -xzf /tmp/oxi-email-server.tar.gz -C "$_OXI_EXTRACT"
	rm -f /tmp/oxi-email-server.tar.gz

	cp --remove-destination "$_OXI_EXTRACT/oxi-email-server" /usr/local/bin/oxi-email-server
	chmod 755 /usr/local/bin/oxi-email-server
	chown root:root /usr/local/bin/oxi-email-server

	mkdir -p "$OXI_STATIC_DIR"
	hide_output rsync -a --delete "$_OXI_EXTRACT/static/" "$OXI_STATIC_DIR/"
	chown -R root:root "$OXI_STATIC_DIR"
	chmod -R 755 "$OXI_STATIC_DIR"

	rm -rf "$_OXI_EXTRACT"
	echo "$OXI_VERSION" > "$_OXI_STAMP"
fi

# Data directory for per-user SQLite + search indexes - www-data needs write.
mkdir -p "$STORAGE_ROOT/oxi"
chown www-data:www-data "$STORAGE_ROOT/oxi"
chmod 750 "$STORAGE_ROOT/oxi"

# Runtime config.
# Use IMAP port 143 (plain, loopback-only) - oxi has no TLS cert skip option
# so port 993 with a self-signed cert would fail. Dovecot already listens on
# 127.0.0.1:143 for local plain IMAP.
mkdir -p /etc/oxi
cat > /etc/oxi/config.env << EOF
HOST=127.0.0.1
PORT=3001
IMAP_HOST=127.0.0.1
IMAP_PORT=143
TLS_ENABLED=false
SMTP_HOST=127.0.0.1
SMTP_PORT=587
ALLOW_CUSTOM_MAIL_SERVERS=false
DATA_DIR=$STORAGE_ROOT/oxi
STATIC_DIR=/usr/local/share/oxi-email/static
RUST_LOG=info,tantivy=warn,async_imap=warn
SESSION_TIMEOUT_HOURS=24
EOF
chmod 640 /etc/oxi/config.env
chown root:www-data /etc/oxi/config.env

STORAGE_ROOT="$STORAGE_ROOT" envsubst '${STORAGE_ROOT}' < setup/conf/systemd/oxi-email.service > /lib/systemd/system/oxi-email.service

systemctl daemon-reload
systemctl enable oxi-email
restart_service oxi-email
