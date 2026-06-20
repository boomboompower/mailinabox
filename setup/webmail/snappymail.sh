#!/bin/bash
# Webmail with SnappyMail
# -----------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing SnappyMail (webmail)..."

# Ensure required PHP extensions are installed.
# (php-intl is intentionally not listed: SnappyMail ships its own polyfill
# for when it's absent - app/libraries/polyfill/intl.php - so it's optional,
# not a hard dependency.)
apt_install_cached "webmail" php-cli php-fpm php-sqlite3 php-json php-common \
    php-xml php-mbstring php-curl php-zip php-gd ca-certificates unzip

# Pin to a known-good SnappyMail version (update both together when
# upgrading; the hash must be computed/copied here, not fetched alongside
# the archive at install time - SnappyMail doesn't publish a GitHub-computed
# digest for this asset, so it was computed directly from the release zip
# when this pin was added).
SNAPPYMAIL_VERSION="2.38.2"
SNAPPYMAIL_SHA256="ad37235002520958094f69bfe97952aab773c5634d68d967db4fc2d439f26399"
SNAPPYMAIL_DIR="/usr/local/src/snappymail"
SNAPPYMAIL_TARGET="/usr/local/share/snappymail"
_SM_STAMP=/usr/local/share/snappymail.version

# Skip download if the installed version already matches. A directory-exists
# check alone (the previous logic) would mean bumping SNAPPYMAIL_VERSION in
# this script silently never re-downloads anything on an already-installed
# box - the same stamp-file convention setup/optional/filebrowser.sh uses.
needs_download=0
if [ ! -d "$SNAPPYMAIL_DIR" ]; then
    needs_download=1
elif [ ! -f "$_SM_STAMP" ] || [ "$(cat "$_SM_STAMP")" != "$SNAPPYMAIL_VERSION" ]; then
    needs_download=1
fi

if [ "$needs_download" = "1" ]; then
    echo "Downloading SnappyMail version ${SNAPPYMAIL_VERSION}..."
    rm -rf "$SNAPPYMAIL_DIR"
    mkdir -p "$SNAPPYMAIL_DIR"
    wget_verify_sha256 \
        "https://github.com/the-djmaze/snappymail/releases/download/v${SNAPPYMAIL_VERSION}/snappymail-${SNAPPYMAIL_VERSION}.zip" \
        "$SNAPPYMAIL_SHA256" \
        /tmp/snappymail.zip
    # The release zip is not flat - it nests the real app under
    # snappymail/v/<version>/app/, which is SnappyMail's own multi-version
    # layout for its built-in updater. Extracting and rsyncing the whole
    # tree as-is is correct; index.php at the top level resolves the active
    # version through that nested path itself.
    unzip -q -o /tmp/snappymail.zip -d "$SNAPPYMAIL_DIR"
    rm -f /tmp/snappymail.zip
    echo "$SNAPPYMAIL_VERSION" > "$_SM_STAMP"
fi

# Upstream bug (present in 2.38.2, may be fixed in later versions - the
# grep guards below make this a no-op + warning if so): DefaultDomain's
# wildcard/default-domain fallback (used by default.json to match any email
# domain with no dedicated <domain>.json) is broken. Load('*') immediately
# runs $sName through strtolower(idn_to_ascii($sName)) - '*' isn't a valid
# IDNA domain character, so idn_to_ascii() fails and corrupts $sName to an
# empty string *before* encodeFileName()'s '*' === $sName special case
# (which maps it to the literal filename "default") ever gets a chance to
# run. The net effect: default.json is never actually reachable via the
# wildcard path, regardless of its content - any domain without its own
# exact <domain>.json file gets "DomainNotAllowed" on login. Same exact
# line appears in both Load() and Disable() - patch both, preserving the
# literal '*' sentinel through to encodeFileName() so its existing special
# case works.
#
# Deliberately NOT gated by $needs_download: this must reapply against
# whatever's currently in $SNAPPYMAIL_DIR on every invocation (idempotent
# either way) so a box that already had this version downloaded before this
# patch existed - or before some future change to it - still gets patched
# on a plain rerun, without requiring a forced redownload.
SNAPPYMAIL_DOMAIN_PHP="$SNAPPYMAIL_DIR/snappymail/v/$SNAPPYMAIL_VERSION/app/libraries/RainLoop/Providers/Domain/DefaultDomain.php"
SNAPPYMAIL_BUGGY_LINE='$sName = \strtolower(\idn_to_ascii($sName));'
SNAPPYMAIL_FIXED_LINE='$sName = "*" === $sName ? $sName : \strtolower(\idn_to_ascii($sName));'
if [ ! -f "$SNAPPYMAIL_DOMAIN_PHP" ]; then
    echo "WARNING: DefaultDomain.php not found at expected path - cannot apply wildcard-domain bug patch." >&2
elif grep -qF "$SNAPPYMAIL_FIXED_LINE" "$SNAPPYMAIL_DOMAIN_PHP"; then
    : # already patched, nothing to do
elif grep -qF "$SNAPPYMAIL_BUGGY_LINE" "$SNAPPYMAIL_DOMAIN_PHP"; then
    python3 - "$SNAPPYMAIL_DOMAIN_PHP" "$SNAPPYMAIL_BUGGY_LINE" "$SNAPPYMAIL_FIXED_LINE" << 'PYEOF'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as f:
    content = f.read()
with open(path, "w", encoding="utf-8") as f:
    f.write(content.replace(old, new))
PYEOF
    echo "Patched SnappyMail's wildcard-domain fallback bug (DefaultDomain.php)."
else
    echo "WARNING: SnappyMail wildcard-domain bug patch target not found in DefaultDomain.php - upstream may have changed or already fixed this. default.json's fallback for unconfigured domains may not work; check manually." >&2
fi

# Keyed on this script's own content hash, not just SNAPPYMAIL_VERSION -
# the deploy step (rsync from $SNAPPYMAIL_DIR, the patched staging copy,
# into $SNAPPYMAIL_TARGET, what PHP-FPM actually serves) must re-run
# whenever this script's logic changes (e.g. the DefaultDomain.php patch
# above), even when the pinned version string hasn't changed - otherwise a
# box that already had this version deployed before a script change never
# picks it up on a normal rerun, exactly as just happened with the
# wildcard-domain patch landing in $SNAPPYMAIL_DIR but never reaching
# $SNAPPYMAIL_TARGET.
_sm_deploy_key="${SNAPPYMAIL_VERSION}:$(hash_files "$PWD/setup/webmail/snappymail.sh")"
if needs_build "snappymail-webmail" "$_sm_deploy_key" || [ ! -d "$SNAPPYMAIL_TARGET" ]; then
    echo "Deploying SnappyMail..."
    mkdir -p "$SNAPPYMAIL_TARGET"
    hide_output rsync -a --delete "$SNAPPYMAIL_DIR/" "$SNAPPYMAIL_TARGET/"
    mark_built "snappymail-webmail" "$_sm_deploy_key"
fi

# Data storage setup - www-data needs ownership.
# SnappyMail uses a '_data_' directory for configurations, domains, and caches.
SNAPPYMAIL_DATA_DIR="$STORAGE_ROOT/snappymail"

# Point SnappyMail to the custom external data directory. SnappyMail's
# versioned bootstrap (snappymail/v/$SNAPPYMAIL_VERSION/include.php) does
# `if (is_file(APP_INDEX_ROOT_PATH.'include.php')) include_once ...` - a
# plain file literally named include.php directly in the docroot root is
# the real, only hook for this. (The shipped _include.php with a leading
# underscore is just an unused example template - nothing ever includes it;
# an earlier version of this script wrote to include/snappymail-data-dir.php,
# a path nothing reads, which is why APP_DATA_FOLDER_PATH silently fell back
# to the bundled root:root data/ folder www-data can't write to.)
cat > "$SNAPPYMAIL_TARGET/include.php" << EOF
<?php
define('APP_DATA_FOLDER_PATH', '$SNAPPYMAIL_DATA_DIR/');
EOF

# Only chown -R / mkdir the data tree fresh on first creation - re-running on
# a live server with cached data already present would recursively traverse
# potentially gigabytes of files for no reason.
if [ ! -d "$SNAPPYMAIL_DATA_DIR" ]; then
    mkdir -p "$SNAPPYMAIL_DATA_DIR/_data_/_default_/configs" "$SNAPPYMAIL_DATA_DIR/_data_/_default_/domains"
    chown -R www-data:www-data "$SNAPPYMAIL_DATA_DIR"
    chmod -R 750 "$SNAPPYMAIL_DATA_DIR"
else
    mkdir -p "$SNAPPYMAIL_DATA_DIR/_data_/_default_/configs" "$SNAPPYMAIL_DATA_DIR/_data_/_default_/domains"
fi

# Base application settings.
# The web admin panel is left disabled: Mail-in-a-Box already has its own
# control panel, and an enabled-by-default admin UI with an auto-generated
# password that's never surfaced to the admin is a needless attack surface
# for a feature nobody asked for. curl_verify_ssl is left at its secure
# default (On) - the previous "Off" setting globally disabled TLS
# verification for all of SnappyMail's outbound HTTP requests (e.g. contact
# avatar fetching), which has nothing to do with the local plaintext IMAP/TLS
# SMTP connections below, and was a blanket weakening with no real benefit.
# Automatically provision the local Mail-in-a-Box domain configuration.
# SnappyMail reads fallback settings from 'default.json' for unknown user
# domains (once the wildcard-fallback bug above is patched).
#
# Schema must match RainLoop\Model\Domain::fromArray()'s legacy flat format
# exactly - camelCase keys, integer security-type codes, not the snake_case
# string-valued keys this previously had. fromArray() checks for a nested
# "IMAP"/"SMTP"/"Sieve" object first; failing that, falls back to flat
# imapHost/imapPort/etc keys - neither matched the old content, so
# fromArray() silently returned null (logged as "Undefined array key
# imapHost"), making the domain object construction fail even after the
# wildcard bug itself was fixed.
#
# Security type codes (MailSo\Net\Enumerations\ConnectionSecurityType):
# NONE=0, SSL/TLS=1, STARTTLS=2. IMAP on 143 is plaintext loopback (0).
# SMTP on 587 is mandatory STARTTLS per Postfix's submission service
# config (master.cf's smtpd_tls_security_level=encrypt), not implicit
# TLS, so this is 2, not 1.
#
# config.ini is written via a tmp file so ownership can be set before the
# final rename - prevents root-owned files on reinstall (www-data can't read
# root:root 640 files, causing silent login failures).
cat > "$SNAPPYMAIL_DATA_DIR/_data_/_default_/configs/config.ini.tmp" << EOF
[security]
allow_admin = Off
force_https = On

[logs]
; Writes a syslog entry (LOG_AUTHPRIV, tag "snappymail") on every failed
; login - required for fail2ban's miab-snappymail filter to have anything
; to match. auth_logging_format is deliberately left unset so only the
; syslog path fires, not also a separate app-managed log file to track.
auth_logging = On
EOF
# Write atomically and set ownership - done every run so reinstalls don't
# leave root-owned config files unreadable by PHP-FPM (www-data).
mv "$SNAPPYMAIL_DATA_DIR/_data_/_default_/configs/config.ini.tmp" \
   "$SNAPPYMAIL_DATA_DIR/_data_/_default_/configs/config.ini"
chown www-data:www-data "$SNAPPYMAIL_DATA_DIR/_data_/_default_/configs/config.ini"

cat > "$SNAPPYMAIL_DATA_DIR/_data_/_default_/domains/default.json" << EOF
{
    "imapHost": "127.0.0.1",
    "imapPort": 143,
    "imapSecure": 0,
    "imapShortLogin": false,
    "useSieve": false,
    "sieveHost": "127.0.0.1",
    "sievePort": 4190,
    "sieveSecure": 0,
    "smtpHost": "127.0.0.1",
    "smtpPort": 587,
    "smtpSecure": 2,
    "smtpShortLogin": false,
    "smtpAuth": true,
    "whiteList": ""
}
EOF

chown www-data:www-data "$SNAPPYMAIL_DATA_DIR/_data_/_default_/domains/default.json"
chown -R root:root "$SNAPPYMAIL_TARGET"
chmod -R 755 "$SNAPPYMAIL_TARGET"

# SnappyMail runs through Nginx via PHP-FPM rather than as its own service.
# The actual nginx wiring (the catch-all location / proxying to PHP-FPM) is
# generated centrally by management/services/web_update.py based on
# WEBMAIL_CLIENT, not written by this script - setup/tools/web_update runs
# later in the pipeline and picks this up.
restart_service "$(php_fpm_service)"
