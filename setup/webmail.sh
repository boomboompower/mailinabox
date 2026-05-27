#!/bin/bash
# Webmail with oxi.email
# ----------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing oxi.email (webmail)..."

# Install Rust to stable system paths so PATH is consistent across MIAB re-runs.
export RUSTUP_HOME=/opt/rustup
export CARGO_HOME=/opt/cargo
if [ ! -x /opt/cargo/bin/cargo ]; then
	curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
		| sh -s -- -y --profile minimal --no-modify-path
fi
export PATH="/opt/cargo/bin:$PATH"
cat > /etc/profile.d/cargo.sh << 'PROFILE'
export RUSTUP_HOME=/opt/rustup
export CARGO_HOME=/opt/cargo
export PATH="$CARGO_HOME/bin:$PATH"
PROFILE

# Install Bun with BUN_INSTALL=/usr/local so the binary lands at /usr/local/bin/bun.
if [ ! -x /usr/local/bin/bun ]; then
	BUN_INSTALL=/usr/local curl -fsSL https://bun.sh/install | bash
fi

apt_install libssl-dev libsqlite3-dev ca-certificates

# Pin to a known-good commit (update this hash when upgrading).
OXI_COMMIT=f210ec5863dad8d8f9ab432272a749fe79a65f74
OXI_DIR=/usr/local/src/oxi

if [ ! -d "$OXI_DIR/.git" ]; then
	git clone https://github.com/c0h1b4/oxi.git "$OXI_DIR"
fi
git -C "$OXI_DIR" fetch origin
git -C "$OXI_DIR" checkout "$OXI_COMMIT"

# Build frontend. /mail is oxi's own Next.js route - no basePath needed.
cd "$OXI_DIR/frontend"
bun install --frozen-lockfile
bun run build

# Build Rust backend.
cd "$OXI_DIR/backend"
cargo build --release

# Install binary and static files.
cp "$OXI_DIR/backend/target/release/oxi-email-server" /usr/local/bin/oxi-email-server
chmod 755 /usr/local/bin/oxi-email-server
chown root:root /usr/local/bin/oxi-email-server

mkdir -p /usr/local/share/oxi-email
rsync -a --delete "$OXI_DIR/frontend/out/" /usr/local/share/oxi-email/static/
chown -R root:root /usr/local/share/oxi-email
chmod -R 755 /usr/local/share/oxi-email

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
DATA_DIR=$STORAGE_ROOT/oxi
STATIC_DIR=/usr/local/share/oxi-email/static
RUST_LOG=info,tantivy=warn,async_imap=warn
SESSION_TIMEOUT_HOURS=24
EOF
chmod 640 /etc/oxi/config.env
chown root:www-data /etc/oxi/config.env

cat > /lib/systemd/system/oxi-email.service << EOF
[Unit]
Description=oxi.email webmail
After=network.target dovecot.service postfix.service

[Service]
EnvironmentFile=/etc/oxi/config.env
ExecStart=/usr/local/bin/oxi-email-server
User=www-data
Group=www-data
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
WorkingDirectory=/usr/local/share/oxi-email

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable oxi-email
restart_service oxi-email
