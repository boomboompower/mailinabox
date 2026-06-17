#!/bin/bash
# Webmail with Roundcube
# ----------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing Roundcube (webmail)..."

# composer is not needed: the "-complete" release archive already bundles
# vendor/ with all PHP dependencies pre-installed. Running composer install
# against it is redundant at best (and risks the live vendor/ tree diverging
# from what this exact release was tested with).
apt_install_cached "webmail" php-cli php-fpm php-sqlite3 php-intl php-json php-common \
    php-xml php-mbstring php-curl php-zip php-gd php-imagick php-pear \
    unzip sqlite3 ca-certificates

# Pin to a known-good Roundcube release (update both together when upgrading;
# the hash is GitHub's own computed digest for this asset, cross-checked
# against the maintainer's .asc signature when bumping - never trust a hash
# fetched from the same place as the archive at install time).
ROUNDCUBE_VERSION="1.7.1"
ROUNDCUBE_SHA256="1e0382bcefd627ab0b6285d3181ddfba5b444fdcf6d49f33f5ea15fbf97864ef"
ROUNDCUBE_DIR="/usr/local/src/roundcube"
ROUNDCUBE_TARGET="/usr/local/share/roundcube"
_RC_STAMP=/usr/local/share/roundcube.version

# Skip download if the installed version already matches. A directory-exists
# check alone (the previous logic) would mean bumping ROUNDCUBE_VERSION in
# this script silently never re-downloads anything on an already-installed
# box - the same stamp-file convention setup/optional/filebrowser.sh uses.
needs_download=0
if [ ! -d "$ROUNDCUBE_DIR" ]; then
    needs_download=1
elif [ ! -f "$_RC_STAMP" ] || [ "$(cat "$_RC_STAMP")" != "$ROUNDCUBE_VERSION" ]; then
    needs_download=1
fi

if [ "$needs_download" = "1" ]; then
    echo "Downloading Roundcube version ${ROUNDCUBE_VERSION}..."
    rm -rf "$ROUNDCUBE_DIR"
    mkdir -p "$ROUNDCUBE_DIR"
    wget_verify_sha256 \
        "https://github.com/roundcube/roundcubemail/releases/download/${ROUNDCUBE_VERSION}/roundcubemail-${ROUNDCUBE_VERSION}-complete.tar.gz" \
        "$ROUNDCUBE_SHA256" \
        /tmp/roundcubemail.tar.gz
    tar -xzf /tmp/roundcubemail.tar.gz --strip-components=1 -C "$ROUNDCUBE_DIR"
    rm -f /tmp/roundcubemail.tar.gz
    echo "$ROUNDCUBE_VERSION" > "$_RC_STAMP"
fi

if needs_build "roundcube-webmail" "$ROUNDCUBE_VERSION"; then
    echo "Deploying Roundcube..."
    mkdir -p "$ROUNDCUBE_TARGET"
    hide_output rsync -a --delete "$ROUNDCUBE_DIR/" "$ROUNDCUBE_TARGET/"
    mark_built "roundcube-webmail" "$ROUNDCUBE_VERSION"
fi

# Data, logs, and DB storage setup - www-data needs ownership.
# Only chown -R on first creation - re-running on a live server with
# attachments/cache already present would recursively traverse potentially
# gigabytes of files for no reason, the same convention used elsewhere
# (see setup/optional/filebrowser.sh).
if [ ! -d "$STORAGE_ROOT/roundcube" ]; then
    mkdir -p "$STORAGE_ROOT/roundcube" "$STORAGE_ROOT/roundcube/temp" "$STORAGE_ROOT/roundcube/logs"
    # Ensure the log file exists before fail2ban starts watching it -
    # log_logins only creates it on the first actual login attempt otherwise.
    touch "$STORAGE_ROOT/roundcube/logs/userlogins.log"
    chown -R www-data:www-data "$STORAGE_ROOT/roundcube"
else
    mkdir -p "$STORAGE_ROOT/roundcube/temp" "$STORAGE_ROOT/roundcube/logs"
    touch "$STORAGE_ROOT/roundcube/logs/userlogins.log"
    chown www-data:www-data "$STORAGE_ROOT/roundcube/logs/userlogins.log"
fi
chmod 750 "$STORAGE_ROOT/roundcube"

# des_key encrypts IMAP/SMTP credentials Roundcube keeps in the session/DB.
# It must be generated once and reused - regenerating it on every setup
# rerun (the previous behavior) would silently invalidate every existing
# session and any stored credentials on every single rerun.
RC_DES_KEY_FILE="$STORAGE_ROOT/roundcube/des_key.txt"
if [ ! -f "$RC_DES_KEY_FILE" ]; then
    (umask 077; openssl rand -base64 24 | head -c 24 > "$RC_DES_KEY_FILE")
fi
RC_DES_KEY=$(cat "$RC_DES_KEY_FILE")

# ── rcmcarddav plugin (Radicale contact sync) ─────────────────────────────────
# Only installed and enabled when ENABLE_RADICALE=true.

RCMCARDDAV_VERSION="5.1.3"
RCMCARDDAV_SHA256="f6c84fcbb7726292f13cdec7cd74bd93cb4241f6f4650e8dde3bca004b39908a"
RCMCARDDAV_DIR="$ROUNDCUBE_TARGET/plugins/carddav"
_CARDDAV_STAMP=/usr/local/share/roundcube-carddav.version

if [ "${ENABLE_RADICALE:-true}" = "true" ]; then
    needs_carddav_download=0
    if [ ! -d "$RCMCARDDAV_DIR" ]; then
        needs_carddav_download=1
    elif [ ! -f "$_CARDDAV_STAMP" ] || [ "$(cat "$_CARDDAV_STAMP")" != "$RCMCARDDAV_VERSION" ]; then
        needs_carddav_download=1
    fi

    if [ "$needs_carddav_download" = "1" ]; then
        echo "Downloading rcmcarddav ${RCMCARDDAV_VERSION}..."
        wget_verify_sha256 \
            "https://github.com/mstilkerich/rcmcarddav/releases/download/v${RCMCARDDAV_VERSION}/carddav-v${RCMCARDDAV_VERSION}.tar.gz" \
            "$RCMCARDDAV_SHA256" \
            /tmp/carddav.tar.gz
        rm -rf "$RCMCARDDAV_DIR"
        mkdir -p "$RCMCARDDAV_DIR"
        tar -xzf /tmp/carddav.tar.gz --strip-components=1 -C "$RCMCARDDAV_DIR"
        rm -f /tmp/carddav.tar.gz
        echo "$RCMCARDDAV_VERSION" > "$_CARDDAV_STAMP"
    fi

    # Plugin config: point to this box's Radicale server.
    # %u expands to the IMAP username (full email address in MIAB).
    cat > "$RCMCARDDAV_DIR/config.inc.php" << EOF
<?php
\$prefs['_GLOBAL']['pwstore_scheme'] = 'encrypted';
\$prefs['_GLOBAL']['loglevel'] = \Psr\Log\LogLevel::WARNING;

\$prefs['radicale'] = [
    'name'           => 'Contacts',
    'url'            => 'https://$PRIMARY_HOSTNAME/radicale/%u/',
    'active'         => true,
    'use_categories' => true,
    'fixed'          => ['url'],
];
EOF
    chmod 640 "$RCMCARDDAV_DIR/config.inc.php"

    RC_PLUGINS="'archive', 'zipdownload', 'carddav'"
else
    RC_PLUGINS="'archive', 'zipdownload'"
fi

# ── Roundcube runtime configuration ───────────────────────────────────────────
mkdir -p "$ROUNDCUBE_TARGET/config"
cat > "$ROUNDCUBE_TARGET/config/config.inc.php" << EOF
<?php
\$config = [];

// Database connection string (SQLite)
\$config['db_dsnw'] = 'sqlite:///$STORAGE_ROOT/roundcube/sqlite.db?mode=0646';

// IMAP and SMTP configuration matching standard loopback
\$config['imap_host'] = '127.0.0.1:143';
\$config['smtp_host'] = '127.0.0.1:587';
\$config['smtp_user'] = '%u';
\$config['smtp_pass'] = '%p';

// Paths for logging and temporary storage
\$config['temp_dir'] = '$STORAGE_ROOT/roundcube/temp';
\$config['log_dir'] = '$STORAGE_ROOT/roundcube/logs';

// Writes logs/userlogins.log on every login attempt (success and failure) -
// required for fail2ban's miab-roundcube filter to have anything to match.
\$config['log_logins'] = true;

// Security settings
\$config['des_key'] = '$RC_DES_KEY';
\$config['session_lifetime'] = 1440; // 24 Hours

// Installed Plugins
\$config['plugins'] = [$RC_PLUGINS];
EOF

chown -R root:root "$ROUNDCUBE_TARGET"
chmod -R 755 "$ROUNDCUBE_TARGET"
# Config dir and plugin configs need www-data read access - set after the
# root:root sweep above so it isn't immediately clobbered.
chown -R root:www-data "$ROUNDCUBE_TARGET/config"
chmod 640 "$ROUNDCUBE_TARGET/config/config.inc.php"
if [ "${ENABLE_RADICALE:-true}" = "true" ] && [ -f "$RCMCARDDAV_DIR/config.inc.php" ]; then
    chown root:www-data "$RCMCARDDAV_DIR/config.inc.php"
    chmod 644 "$RCMCARDDAV_DIR/config.inc.php"
fi

# Initialize or upgrade the Roundcube database schema.
# --update makes initdb.sh check for the system table first: if found it runs
# db_update (idempotent migrations) rather than db_init. This handles all
# drivers correctly - SQLite auto-initializes on first connect so system
# always exists; MySQL/PostgreSQL on a fresh DB fall through to db_init.
echo "Initializing/upgrading Roundcube database schema..."
if ! hide_output php "$ROUNDCUBE_TARGET/bin/initdb.sh" --update --dir "$ROUNDCUBE_TARGET/SQL"; then
    echo "WARNING: Roundcube initdb.sh reported an error - check $ROUNDCUBE_TARGET/logs for details."
fi

# rcmcarddav DB migrations - run after initdb.sh so the SQLite file exists.
# Migrations are idempotent; safe to re-run on every setup.
if [ "${ENABLE_RADICALE:-true}" = "true" ] && [ -d "$RCMCARDDAV_DIR/dbmigrations/sqlite3" ]; then
    RC_DB="$STORAGE_ROOT/roundcube/sqlite.db"
    for _sql in $(ls "$RCMCARDDAV_DIR/dbmigrations/sqlite3/"*.sql 2>/dev/null | sort); do
        sqlite3 "$RC_DB" < "$_sql"
    done
fi

# Roundcube runs through Nginx via PHP-FPM rather than as its own service.
# The actual nginx wiring (the catch-all location / proxying to PHP-FPM) is
# generated centrally by management/services/web_update.py based on
# WEBMAIL_CLIENT, not written by this script - setup/tools/web_update runs
# later in the pipeline and picks this up.
restart_service "$(php_fpm_service)"
