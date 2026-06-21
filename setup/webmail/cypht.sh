#!/bin/bash
# Webmail with Cypht
# ------------------

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing Cypht (webmail)..."

# ext-curl, ext-fileinfo, ext-iconv, ext-json, ext-mbstring, ext-openssl,
# ext-session are required by composer.json. php-zip covers attachment
# handling. composer installs vendor/ dependencies from the lockfile.
apt_install_cached "webmail" php-cli php-fpm php-curl php-mbstring php-zip \
    php-json php-intl php-xml php-soap php-gd ca-certificates composer unzip

# Pinned to a commit rather than a release tag so merged upstream fixes land
# without waiting for a release. Update CYPHT_COMMIT + CYPHT_SHA256 together.
CYPHT_COMMIT="d4a9c43b109d019577b364fa89852264377ca03a"
CYPHT_SHA256="d0d07588f1755eee258ba181e28bb103b9bc4374f8e54d3e5e4794e80f29d7a7"
CYPHT_DIR="/usr/local/src/cypht"
CYPHT_TARGET="/usr/local/share/cypht"
_CYPHT_STAMP=/usr/local/share/cypht.version

needs_download=0
if [ ! -d "$CYPHT_DIR" ]; then
    needs_download=1
elif [ ! -f "$_CYPHT_STAMP" ] || [ "$(cat "$_CYPHT_STAMP")" != "$CYPHT_COMMIT" ]; then
    needs_download=1
fi

if [ "$needs_download" = "1" ]; then
    echo "Downloading Cypht at ${CYPHT_COMMIT:0:8}..."
    rm -rf "$CYPHT_DIR"
    mkdir -p "$CYPHT_DIR"
    wget_verify_sha256 \
        "https://github.com/cypht-org/cypht/archive/${CYPHT_COMMIT}.tar.gz" \
        "$CYPHT_SHA256" \
        /tmp/cypht.tar.gz
    tar -xzf /tmp/cypht.tar.gz --strip-components=1 -C "$CYPHT_DIR"
    rm -f /tmp/cypht.tar.gz
    echo "$CYPHT_COMMIT" > "$_CYPHT_STAMP"
fi

# Keyed on script content hash so a script change (e.g. module list update)
# forces a redeploy even when the commit hasn't changed.
_cypht_deploy_key="${CYPHT_COMMIT}:$(hash_files "$PWD/setup/webmail/cypht.sh")"
if needs_build "cypht-webmail" "$_cypht_deploy_key" || [ ! -d "$CYPHT_TARGET" ]; then
    echo "Installing Cypht vendor dependencies..."
    COMPOSER_ALLOW_SUPERUSER=1 hide_output composer install --no-dev --working-dir="$CYPHT_DIR"

    echo "Deploying Cypht..."
    mkdir -p "$CYPHT_TARGET"
    hide_output rsync -a --delete "$CYPHT_DIR/" "$CYPHT_TARGET/"
    # index.php ships with APP_PATH='' which breaks .env loading under PHP-FPM
    # (CWD is not the app dir). Use the absolute path like config_gen.php does.
    python3 -c "
import sys
f = sys.argv[1]
with open(f) as fh: c = fh.read()
c = c.replace(\"define('APP_PATH', '');\", \"define('APP_PATH', dirname(__FILE__).'/');\")
with open(f, 'w') as fh: fh.write(c)
" "$CYPHT_TARGET/index.php"

    # Auto-populate CardDAV credentials on login using the same username/password
    # the user authenticated with. Without this, users must manually enter their
    # CardDAV credentials in Settings even though they are identical to IMAP.
    python3 -c "
import sys

# Append handler class to modules.php
modules = sys.argv[1]
with open(modules) as fh: c = fh.read()
handler = '''
class Hm_Handler_auto_populate_carddav_credentials extends Hm_Handler_Module {
    public function process() {
        list(\$success, \$form) = \$this->process_form(array(\"username\", \"password\"));
        if (!\$success || !\$this->session->is_active()) {
            return;
        }
        \$existing = \$this->user_config->get(\"carddav_contacts_auth_setting\", array());
        \$servers  = config(\"carddav\");
        \$changed  = false;
        foreach (\$servers as \$name => \$details) {
            if (!isset(\$existing[\$name][\"user\"]) || empty(\$existing[\$name][\"user\"])) {
                \$existing[\$name] = array(\"user\" => rtrim(\$form[\"username\"]), \"pass\" => \$form[\"password\"]);
                \$changed = true;
            }
        }
        if (\$changed) {
            \$this->user_config->set(\"carddav_contacts_auth_setting\", \$existing);
            \$this->user_config->save(rtrim(\$form[\"username\"]), \$form[\"password\"]);
        }
    }
}
'''
if 'auto_populate_carddav_credentials' not in c:
    c = c.rstrip() + '\n' + handler + '\n'
    with open(modules, 'w') as fh: fh.write(c)

# Register the handler in setup.php
setup = sys.argv[2]
with open(setup) as fh: c = fh.read()
hook = \"add_handler('home', 'auto_populate_carddav_credentials', true, 'carddav_contacts', 'load_user_data', 'after');\"
if 'auto_populate_carddav_credentials' not in c:
    c = c.replace('handler_source(', hook + '\n' + 'handler_source(', 1)
    with open(setup, 'w') as fh: fh.write(c)

" \
    "$CYPHT_TARGET/modules/carddav_contacts/modules.php" \
    "$CYPHT_TARGET/modules/carddav_contacts/setup.php"

    # Hide the CardDAV credentials form in single-server mode - server is pre-configured
    # to Radicale and credentials are auto-populated on login, so the form is pointless
    # and exposes an attack surface for users to misconfigure their contacts server.
    python3 -c "
f = '$CYPHT_TARGET/modules/carddav_contacts/modules.php'
with open(f) as fh: c = fh.read()
needle = 'protected function output() {\n        \$settings = \$this->get(\'carddav_settings\''
guard  = 'protected function output() {\n        if (filter_var(env(\'SINGLE_SERVER_MODE\', \'false\'), FILTER_VALIDATE_BOOLEAN)) { return \'\'; }\n        \$settings = \$this->get(\'carddav_settings\''
if needle in c and guard not in c:
    c = c.replace(needle, guard, 1)
    with open(f, 'w') as fh: fh.write(c)
"

    # The server-adding wizard (stepper) in Cypht is split across many output modules:
    # the container, form steps, end-parts, and the NUX "Add a new server" button.
    # Each module must independently check single_server_mode because the module system
    # concatenates HTML strings - returning '' from the container but not the children
    # leaves the child HTML orphaned on the page.
    python3 -c "
import re
GUARD = \"if (\\\$this->get('single_server_mode')) { return ''; }\"
def patch(c, cls):
    pat = (r'(class ' + re.escape(cls) +
           r'\s+extends\s+Hm_Output_Module\s*\{.*?'
           r'protected\s+function\s+output\s*\(\s*\)\s*\{)')
    def add(m): return m.group(0) + '\n        ' + GUARD
    return re.sub(pat, add, c, flags=re.DOTALL, count=1)

patches = [
    ('$CYPHT_TARGET/modules/core/output_modules.php', [
        'Hm_Output_server_config_stepper',
        'Hm_Output_server_config_stepper_end_part',
        'Hm_Output_server_config_stepper_accordion_end_part',
    ]),
    ('$CYPHT_TARGET/modules/imap/output_modules.php', [
        'Hm_Output_stepper_setup_server_jmap',
        'Hm_Output_stepper_setup_server_imap',
        'Hm_Output_stepper_setup_server_jmap_imap_common',
    ]),
    ('$CYPHT_TARGET/modules/smtp/modules.php', [
        'Hm_Output_stepper_setup_server_smtp',
    ]),
    ('$CYPHT_TARGET/modules/nux/modules.php', [
        'Hm_Output_quick_add_multiple_section',
    ]),
]
for fpath, classes in patches:
    with open(fpath) as fh: c = fh.read()
    for cls in classes:
        if GUARD not in c:
            c = patch(c, cls)
    with open(fpath, 'w') as fh: fh.write(c)
"

    # Upstream omits single_server_mode check from the Exchange/EWS output module.
    python3 -c "
f = '$CYPHT_TARGET/modules/imap/output_modules.php'
with open(f) as fh: c = fh.read()
needle = 'class Hm_Output_server_config_ews extends Hm_Output_Module {\n    protected function output() {\n        \$hasEWSActivated'
guard  = 'class Hm_Output_server_config_ews extends Hm_Output_Module {\n    protected function output() {\n        if (\$this->get(\'single_server_mode\')) { return \'\'; }\n        \$hasEWSActivated'
if needle in c and guard not in c:
    c = c.replace(needle, guard, 1)
    with open(f, 'w') as fh: fh.write(c)
"

    # "Add Carddav" title on the contact form is confusing - it's adding a contact
    # not a server. Rename to "Add Contact".
    python3 -c "
f = '$CYPHT_TARGET/modules/carddav_contacts/modules.php'
with open(f) as fh: c = fh.read()
if \"trans('Add Carddav')\" in c:
    c = c.replace(\"trans('Add Carddav')\", \"trans('Add Contact')\", 1)
    with open(f, 'w') as fh: fh.write(c)
"

    # Symfony Dotenv 6.x deprecated putenv() support - values land in \$_ENV only.
    # Cypht's env() still uses getenv() which reads the process env and sees nothing.
    # Replace the function body using a regex so whitespace differences don't matter.
    python3 -c "
import re, sys
f = '$CYPHT_TARGET/lib/environment.php'
with open(f) as fh: c = fh.read()
fixed = ('    function env(\$key, \$default = null) {\n'
         '        \$v = getenv(\$key);\n'
         '        if (\$v !== false) return \$v;\n'
         '        return isset(\$_ENV[\$key]) ? \$_ENV[\$key] : \$default;\n'
         '    }')
if '\$_ENV' not in c:
    c = re.sub(
        r'function env\(\\\$key,\s*\\\$default\s*=\s*null\)\s*\{[^}]+\}',
        fixed.lstrip(),
        c,
    )
    with open(f, 'w') as fh: fh.write(c)
"
    # Log failed login attempts with the real client IP so fail2ban can ban
    # brute-force attackers. Without this, Cypht's IMAP auth makes Dovecot see
    # 127.0.0.1 as the source, which is whitelisted and never banned.
    python3 -c "
import sys

# Add handler class to handler_modules.php
handler_modules = sys.argv[1]
with open(handler_modules) as fh: c = fh.read()
handler = '''
class Hm_Handler_log_failed_login extends Hm_Handler_Module {
    public function process() {
        list(\$success, \$form) = \$this->process_form(array('username', 'password'));
        if (!\$success) { return; }
        if (\$this->session->is_active()) { return; }
        \$ip = isset(\$this->request->server['REMOTE_ADDR']) ? \$this->request->server['REMOTE_ADDR'] : 'unknown';
        \$raw = isset(\$form['username']) ? rtrim(\$form['username']) : 'unknown';
        \$user = substr(preg_replace('/[^\x20-\x7E]/', '', \$raw), 0, 254);
        \$line = '[' . date('Y-m-d H:i:s') . '] Failed login for ' . \$user . ' from ' . \$ip . PHP_EOL;
        @file_put_contents('/var/log/cypht-auth.log', \$line, FILE_APPEND | LOCK_EX);
    }
}
'''
if 'log_failed_login' not in c:
    c = c.rstrip() + '\n' + handler + '\n'
    with open(handler_modules, 'w') as fh: fh.write(c)

# Register after the login handler in setup.php
setup = sys.argv[2]
with open(setup) as fh: c = fh.read()
hook = \"add_handler('home', 'log_failed_login', false, 'core', 'login', 'after');\"
if 'log_failed_login' not in c:
    c = c.replace(\"add_handler('home', 'check_missing_passwords'\", hook + '\n' + \"add_handler('home', 'check_missing_passwords'\", 1)
    with open(setup, 'w') as fh: fh.write(c)
" \
    "$CYPHT_TARGET/modules/core/handler_modules.php" \
    "$CYPHT_TARGET/modules/core/setup.php"

    mark_built "cypht-webmail" "$_cypht_deploy_key"
fi

# Data directories - only chown -R on first creation for the same reason
# as roundcube.sh and snappymail.sh (avoid traversing user data on reruns).
CYPHT_DATA_DIR="$STORAGE_ROOT/cypht"
if [ ! -d "$CYPHT_DATA_DIR" ]; then
    mkdir -p "$CYPHT_DATA_DIR/users" "$CYPHT_DATA_DIR/attachments"
    chown -R www-data:www-data "$CYPHT_DATA_DIR"
    chmod 750 "$CYPHT_DATA_DIR"
else
    mkdir -p "$CYPHT_DATA_DIR/users" "$CYPHT_DATA_DIR/attachments"
fi

# Auth log for fail2ban - must be writable by www-data (PHP-FPM user).
touch /var/log/cypht-auth.log
chown www-data:adm /var/log/cypht-auth.log
chmod 640 /var/log/cypht-auth.log

cat > /etc/logrotate.d/cypht-auth << 'EOF'
/var/log/cypht-auth.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 640 www-data adm
}
EOF

# Include carddav_contacts module when Radicale is enabled so Cypht contacts
# sync with the same CardDAV server users use on their devices.
_CYPHT_MODULES="core,contacts,local_contacts,feeds,imap,smtp,account,idle_timer,desktop_notifications,themes,nux,profiles,imap_folders,sievefilters,tags,history,scheduled_sends"
if [ "${ENABLE_RADICALE:-true}" = "true" ]; then
    # carddav_contacts syncs with Radicale - drop local_contacts to avoid two stores
    _CYPHT_MODULES="${_CYPHT_MODULES//local_contacts,/}"
    _CYPHT_MODULES="${_CYPHT_MODULES},carddav_contacts"
fi

# Runtime configuration. AUTH_TYPE=IMAP authenticates directly against
# Dovecot's IMAP on 127.0.0.1:143 - no separate user database needed.
# SINGLE_SERVER_MODE prevents users from adding external accounts.
# DEFAULT_SMTP_TLS=STARTTLS matches Postfix's submission service on port 587.
cat > "$CYPHT_TARGET/.env" << EOF
APP_NAME=Cypht

SESSION_TYPE=PHP
AUTH_TYPE=IMAP

IMAP_AUTH_NAME=MIAB
IMAP_AUTH_SERVER=127.0.0.1
IMAP_AUTH_PORT=143
IMAP_AUTH_TLS=false

DEFAULT_SMTP_SERVER=127.0.0.1
DEFAULT_SMTP_PORT=587
DEFAULT_SMTP_TLS=STARTTLS

USER_CONFIG_TYPE=file
USER_SETTINGS_DIR=$CYPHT_DATA_DIR/users
ATTACHMENT_DIR=$CYPHT_DATA_DIR/attachments

SINGLE_SERVER_MODE=true
DYNAMIC_HOST=false
DYNAMIC_USER=false

DEFAULT_EMAIL_DOMAIN=
ALLOW_EXTERNAL_IMAGE_SOURCES=false
ALLOW_LONG_SESSION=false

ENABLE_DEBUG=false
LOG_LEVEL=WARNING
LOG_FILE=

CARD_DAV_SERVER=http://127.0.0.1:5232

CYPHT_MODULES=$_CYPHT_MODULES
EOF

chmod 640 "$CYPHT_TARGET/.env"
chown root:www-data "$CYPHT_TARGET/.env"

# Generate the runtime module config (writes config/dynamic.php inside the
# target). Must run after every deploy and after .env changes since it reads
# .env and encodes the active module list into the generated file.
echo "Generating Cypht runtime configuration..."
if ! hide_output php "$CYPHT_TARGET/scripts/config_gen.php"; then
    echo "FAILED: Cypht config_gen.php failed - check output above."
    exit 1
fi

chown -R root:root "$CYPHT_TARGET"
chown -R root:www-data "$CYPHT_TARGET/.env" "$CYPHT_TARGET/config"
chown -R www-data:www-data "$CYPHT_TARGET/assets"
chmod -R 755 "$CYPHT_TARGET"
chmod 640 "$CYPHT_TARGET/.env"
chmod 644 "$CYPHT_TARGET/config/dynamic.php" 2>/dev/null || true

# Cypht runs through Nginx via PHP-FPM rather than as its own service.
restart_service "$(php_fpm_service)"
