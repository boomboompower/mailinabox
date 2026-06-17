#!/bin/bash
# FileBrowser - web file manager
# ------------------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing FileBrowser..."

# Pinned version (update FB_HASH when changing FB_VERSION).
# To get the hash: run this script once with a wrong hash; the correct sha1
# is printed in the error. Or: sha1sum linux-amd64-filebrowser.tar.gz
FB_VERSION=v2.63.11
FB_HASH=4bc72dad029d531d153b58bd63a3dabf74c0b395

# Skip download if the installed version already matches.
# We use a stamp file rather than parsing 'filebrowser version' output, which
# varies across releases and would cause spurious re-downloads.
_FB_STAMP=/usr/local/share/filebrowser.version
needs_update=0
if [ ! -x /usr/local/bin/filebrowser ]; then
	needs_update=1
elif [ ! -f "$_FB_STAMP" ] || [ "$(cat "$_FB_STAMP")" != "$FB_VERSION" ]; then
	needs_update=1
fi

if [ "$needs_update" = "1" ]; then
	wget_verify \
		"https://github.com/filebrowser/filebrowser/releases/download/${FB_VERSION}/linux-amd64-filebrowser.tar.gz" \
		"$FB_HASH" \
		/tmp/filebrowser.tar.gz
	tar -xzf /tmp/filebrowser.tar.gz -C /usr/local/bin filebrowser
	chmod +x /usr/local/bin/filebrowser
	rm /tmp/filebrowser.tar.gz
	echo "$FB_VERSION" > "$_FB_STAMP"
fi

# Files root and database directories.
# Only chown -R on first creation - re-running on a live server with user data
# would recursively traverse potentially gigabytes of files for no reason.
if [ ! -d "$STORAGE_ROOT/files" ]; then
	mkdir -p "$STORAGE_ROOT/files"
	chown -R www-data:www-data "$STORAGE_ROOT/files"
else
	mkdir -p "$STORAGE_ROOT/files"
fi

mkdir -p "$STORAGE_ROOT/filebrowser"
chown www-data:www-data "$STORAGE_ROOT/filebrowser"

FB_DB="$STORAGE_ROOT/filebrowser/filebrowser.db"

# Install auth hook. Verifies credentials via the management daemon's /auth/verify endpoint
# Exit codes: 0=auth or block (FileBrowser reads hook.action), 1=server error.
# Bad credentials must exit 0 with hook.action=block - a non-zero exit makes
# FileBrowser return 500 instead of 403, which breaks fail2ban targeting.
cat > /usr/local/lib/filebrowser-auth.py << EOF
#!/usr/bin/env python3
import hashlib, os, sys, urllib.error, urllib.parse, urllib.request

FILES_ROOT = "$STORAGE_ROOT/files"
MANAGEMENT_HOST = "${MANAGEMENT_HOST:-127.0.0.1}"

username = os.environ.get('USERNAME', '')
password = os.environ.get('PASSWORD', '')

if not username or not password:
    print("hook.action=block")
    sys.exit(0)

try:
    data = urllib.parse.urlencode({"email": username, "password": password}).encode()
    req = urllib.request.Request(
        f"http://{MANAGEMENT_HOST}:10222/auth/verify",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()

    # Hash the email to avoid exposing addresses in the filesystem, standardized
    # to match other systems (SHA-256 of raw email bytes, lowercase hex).
    user_hash = hashlib.sha256(username.encode()).hexdigest()
    os.makedirs(os.path.join(FILES_ROOT, user_hash), mode=0o750, exist_ok=True)

    print("hook.action=auth")
    print(f"user.scope={user_hash}")
    sys.exit(0)
except urllib.error.HTTPError as e:
    if e.code == 401:
        print("hook.action=block")
        sys.exit(0)
    # Other HTTP error - let FileBrowser return 500.
    sys.exit(1)
except Exception:
    # Management unreachable - let FileBrowser return 500.
    sys.exit(1)
EOF
chmod 755 /usr/local/lib/filebrowser-auth.py
chown root:root /usr/local/lib/filebrowser-auth.py

# Stop the service before touching the database - it holds a BoltDB lock
# while running and config init/set will timeout if it's up.
systemctl stop filebrowser 2>/dev/null || true

# Initialize on first install only.
if [ ! -f "$FB_DB" ]; then
	hide_output sudo -u www-data filebrowser config init \
		--database "$FB_DB"
fi

# Apply config on every run so settings are updated when setup re-runs.
# FILEBROWSER_BIND defaults to 127.0.0.1 (bare metal, nginx co-located).
# Set to 0.0.0.0 in Docker so nginx can reach it from a separate container.
FB_BIND="${FILEBROWSER_BIND:-127.0.0.1}"
hide_output sudo -u www-data filebrowser config set \
	--database "$FB_DB" \
	--address "$FB_BIND" \
	--port 8080 \
	--root "$STORAGE_ROOT/files" \
	--baseURL /files \
	--auth.method hook \
	--auth.command "python3 /usr/local/lib/filebrowser-auth.py" \
	--minimumPasswordLength 1 \
	--createUserDir \
	--branding.name "$PRIMARY_HOSTNAME"
# minimumPasswordLength 1: 0 is treated as unset (Go zero value) and reverts to default 12
# createUserDir: each user gets their own subdirectory under the files root

# Ensure the log file exists before fail2ban starts watching it.
touch /var/log/filebrowser.log
chown www-data:www-data /var/log/filebrowser.log

# Logrotate config: rotate weekly, keep 4 weeks, copytruncate so we don't
# need to signal FileBrowser to reopen the file (it doesn't support SIGUSR1).
cat > /etc/logrotate.d/filebrowser << 'LOGROTATEOF'
/var/log/filebrowser.log {
    weekly
    rotate 4
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data www-data
    copytruncate
}
LOGROTATEOF

STORAGE_ROOT="$STORAGE_ROOT" envsubst '${STORAGE_ROOT}' < setup/conf/systemd/filebrowser.service > /lib/systemd/system/filebrowser.service

systemctl daemon-reload
systemctl enable filebrowser
restart_service filebrowser
