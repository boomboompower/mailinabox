#!/bin/bash
# FileBrowser - web file manager
# ------------------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing FileBrowser..."

# Pinned version (update when upgrading).
FB_VERSION=v2.63.11
wget -q -O /tmp/filebrowser.tar.gz \
	"https://github.com/filebrowser/filebrowser/releases/download/${FB_VERSION}/linux-amd64-filebrowser.tar.gz"
tar -xzf /tmp/filebrowser.tar.gz -C /usr/local/bin filebrowser
chmod +x /usr/local/bin/filebrowser
rm /tmp/filebrowser.tar.gz

# Files root and database directories.
mkdir -p "$STORAGE_ROOT/files"
chown www-data:www-data "$STORAGE_ROOT/files"

mkdir -p "$STORAGE_ROOT/filebrowser"
chown www-data:www-data "$STORAGE_ROOT/filebrowser"

FB_DB="$STORAGE_ROOT/filebrowser/filebrowser.db"

# Install IMAP hook auth script. Connects on port 993 with cert verification
# disabled (Python ssl allows this; oxi does not). Lets users log in with
# their mail credentials.
cat > /usr/local/lib/filebrowser-auth.py << 'EOF'
#!/usr/bin/env python3
import sys, json, imaplib, ssl

data = json.load(sys.stdin)
username = data.get('username', '')
password = data.get('password', '')

try:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = imaplib.IMAP4_SSL('127.0.0.1', 993, ssl_context=ctx)
    conn.login(username, password)
    conn.logout()
    print(json.dumps({"username": username, "isAdmin": False}))
    sys.exit(0)
except Exception:
    sys.exit(1)
EOF
chmod 755 /usr/local/lib/filebrowser-auth.py
chown root:root /usr/local/lib/filebrowser-auth.py

# Initialize on first install only.
if [ ! -f "$FB_DB" ]; then
	sudo -u www-data filebrowser config init \
		--database "$FB_DB"
	sudo -u www-data filebrowser config set \
		--database "$FB_DB" \
		--address 127.0.0.1 \
		--port 8080 \
		--root "$STORAGE_ROOT/files" \
		--baseURL /files \
		--auth.method hook \
		--auth.command "python3 /usr/local/lib/filebrowser-auth.py"
fi

cat > /lib/systemd/system/filebrowser.service << EOF
[Unit]
Description=FileBrowser web file manager
After=network.target

[Service]
ExecStart=/usr/local/bin/filebrowser \
    --database $STORAGE_ROOT/filebrowser/filebrowser.db \
    --log /var/log/filebrowser.log
User=www-data
Group=www-data
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable filebrowser
restart_service filebrowser
