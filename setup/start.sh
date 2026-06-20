#!/bin/bash
# This is the entry point for configuring the system.
#####################################################

# Change to the repo root regardless of how this script was invoked.
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.."

source setup/functions.sh # load our functions

# Parse flags.
# --force          bypasses all stamp checks and re-runs every build step.
# --no-upgrade     skips apt update/upgrade/autoremove (safe on re-runs, not first installs).
for _arg in "$@"; do
	case "$_arg" in
		--force) export MIAB_FORCE=1 ;;
		--no-upgrade) export MIAB_SKIP_UPDATES=1 ;;
	esac
done
unset _arg

# Tee all output (stdout + stderr) to a log file so crashes leave a trace.
exec > >(tee -a /tmp/mailinabox-setup.log) 2>&1
echo "=== Setup started at $(date) ==="

# Check system setup: Are we running as root on a supported Ubuntu release on a
# machine with enough memory? Is /tmp mounted with exec.
# If not, this shows an error and exits.
source setup/preflight.sh

# Ensure Python reads/writes files in UTF-8. If the machine
# triggers some other locale in Python, like ASCII encoding,
# Python may not be able to read/write files. This is also
# in the management daemon startup script and the cron script.

if ! locale -a | grep en_US.utf8 > /dev/null; then
    # Generate locale if not exists
    hide_output locale-gen en_US.UTF-8
fi

export LANGUAGE=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_TYPE=en_US.UTF-8

# Fix so line drawing characters are shown correctly in Putty on Windows. See #744.
export NCURSES_NO_UTF8_ACS=1

# Recall the last settings used if we're running this a second time.
if [ -f /etc/mailinabox.conf ]; then
	# Run any system migrations before proceeding. Since this is a second run,
	# we assume we have Python already installed.
	setup/migrate.py --migrate || exit 1

	# Load the old .conf file to get existing configuration options loaded
	# into variables with a DEFAULT_ prefix.
	cat /etc/mailinabox.conf | sed s/^/DEFAULT_/ > /tmp/mailinabox.prev.conf
	source /tmp/mailinabox.prev.conf
	rm -f /tmp/mailinabox.prev.conf
else
	FIRST_TIME_SETUP=1
fi

# Put a start script in a global location. We tell the user to run 'mailinabox'
# in the first dialog prompt, so we should do this before that starts.
cat > /usr/local/bin/mailinabox << 'EOF'
#!/bin/bash
exec boxctl "$@"
EOF
chmod +x /usr/local/bin/mailinabox

# Ask the user for the PRIMARY_HOSTNAME, PUBLIC_IP, and PUBLIC_IPV6,
# if values have not already been set in environment variables. When running
# non-interactively, be sure to set values for all! Also sets STORAGE_USER and
# STORAGE_ROOT.
source setup/questions.sh

# Run some network checks to make sure setup on this machine makes sense.
# Skip on existing installs since we don't want this to block the ability to
# upgrade, and these checks are also in the control panel status checks.
if [ -z "${DEFAULT_PRIMARY_HOSTNAME:-}" ]; then
if [ -z "${SKIP_NETWORK_CHECKS:-}" ]; then
	source setup/network-checks.sh
fi
fi

# Create the STORAGE_USER and STORAGE_ROOT directory if they don't already exist.
#
# Set the directory and all of its parent directories' permissions to world
# readable since it holds files owned by different processes.
#
# If the STORAGE_ROOT is missing the mailinabox.version file that lists a
# migration (schema) number for the files stored there, assume this is a fresh
# installation to that directory and write the file to contain the current
# migration number for this version of Mail-in-a-Box.
if ! id -u "$STORAGE_USER" >/dev/null 2>&1; then
	useradd -r -m -d "$STORAGE_ROOT" "$STORAGE_USER"
fi
if [ ! -d "$STORAGE_ROOT" ]; then
	mkdir -p "$STORAGE_ROOT"
fi
f=$STORAGE_ROOT
while [[ $f != / ]]; do chmod a+rx "$f"; f=$(dirname "$f"); done;
if [ ! -f "$STORAGE_ROOT/mailinabox.version" ]; then
	setup/migrate.py --current > "$STORAGE_ROOT/mailinabox.version"
	chown "$STORAGE_USER:$STORAGE_USER" "$STORAGE_ROOT/mailinabox.version"
fi

# Save the global options in /etc/mailinabox.conf so that standalone
# tools know where to look for data. The default MTA_STS_MODE setting
# is blank unless set by an environment variable, but see web.sh for
# how that is interpreted.
# Preserve optional service flags across re-runs; defaults apply on first install.
ENABLE_FILEBROWSER=${ENABLE_FILEBROWSER:-${DEFAULT_ENABLE_FILEBROWSER:-true}}
ENABLE_RADICALE=${ENABLE_RADICALE:-${DEFAULT_ENABLE_RADICALE:-true}}
ENABLE_CLAMAV=${ENABLE_CLAMAV:-${DEFAULT_ENABLE_CLAMAV:-false}}
WEBMAIL_CLIENT=${WEBMAIL_CLIENT:-${DEFAULT_WEBMAIL_CLIENT:-oxi}}
DNS_MODE=${DNS_MODE:-${DEFAULT_DNS_MODE:-self}}
SPAM_FILTER=${SPAM_FILTER:-${DEFAULT_SPAM_FILTER:-rspamd}}
TIMEZONE=${TIMEZONE:-${DEFAULT_TIMEZONE:-}}

# BACKUP_TOOL: brand new installs default to restic. Existing installs that
# are rerunning setup but never had this flag (DEFAULT_BACKUP_TOOL unset)
# keep duplicity - nothing auto-switches an existing box's backup tool.
if [ -n "${FIRST_TIME_SETUP:-}" ]; then
	BACKUP_TOOL=${BACKUP_TOOL:-restic}
else
	BACKUP_TOOL=${BACKUP_TOOL:-${DEFAULT_BACKUP_TOOL:-duplicity}}
fi

cat > /etc/mailinabox.conf << EOF;
STORAGE_USER=$STORAGE_USER
STORAGE_ROOT=$STORAGE_ROOT
PRIMARY_HOSTNAME=$PRIMARY_HOSTNAME
PUBLIC_IP=$PUBLIC_IP
PUBLIC_IPV6=$PUBLIC_IPV6
PRIVATE_IP=$PRIVATE_IP
PRIVATE_IPV6=$PRIVATE_IPV6
MTA_STS_MODE=${DEFAULT_MTA_STS_MODE:-enforce}
ENABLE_FILEBROWSER=$ENABLE_FILEBROWSER
ENABLE_RADICALE=$ENABLE_RADICALE
ENABLE_CLAMAV=$ENABLE_CLAMAV
WEBMAIL_CLIENT=$WEBMAIL_CLIENT
DNS_MODE=$DNS_MODE
BACKUP_TOOL=$BACKUP_TOOL
SPAM_FILTER=$SPAM_FILTER
TIMEZONE=$TIMEZONE
DOVECOT_IMAP_BIND=127.0.0.1
EOF

# Start service configuration.
source setup/infra/system.sh
source setup/infra/ssl.sh
source setup/infra/dns.sh
source setup/mail/postfix.sh

# Clear any previously configured milters so that spam filter scripts start
# from a clean slate. Prevents stale entries from a prior filter path (e.g.
# opendkim/opendmarc) persisting when the active filter changes.
clear_milters

source setup/mail/dovecot.sh
source setup/mail/users.sh
if [ "$SPAM_FILTER" = "spamassassin" ]; then
	source setup/mail/dkim.sh
	source setup/mail/spamassassin.sh
else
	source setup/mail/rspamd.sh
fi
source setup/infra/web.sh

# Stop all webmail services before installing to handle client switches cleanly.
systemctl stop oxi-email 2>/dev/null || true
systemctl disable oxi-email 2>/dev/null || true
case "$WEBMAIL_CLIENT" in
	oxi)        source setup/webmail/oxi.sh ;;
	roundcube)  source setup/webmail/roundcube.sh ;;
	snappymail) source setup/webmail/snappymail.sh ;;
	cypht)      source setup/webmail/cypht.sh ;;
	none)       ;; # no webmail
esac

if [ "$ENABLE_FILEBROWSER" = "true" ]; then
	source setup/optional/filebrowser.sh
else
	# Disable FileBrowser if it was previously installed.
	systemctl stop filebrowser 2>/dev/null || true
	systemctl disable filebrowser 2>/dev/null || true
fi
if [ "$ENABLE_RADICALE" = "true" ]; then
	source setup/optional/radicale.sh
else
	systemctl stop radicale 2>/dev/null || true
	systemctl disable radicale 2>/dev/null || true
fi
if [ "$ENABLE_CLAMAV" = "true" ]; then
	source setup/optional/clamav.sh
else
	systemctl stop clamav-daemon 2>/dev/null || true
	systemctl disable clamav-daemon 2>/dev/null || true
fi
source setup/management.sh
source setup/monitoring/munin.sh

# Wait for the management daemon to start...
until nc -z -w 4 127.0.0.1 10222 > /dev/null 2>&1
do
	echo "Waiting for the Mail-in-a-Box management daemon to start..."
	sleep 2
done

# ...and then have it write the DNS and nginx configuration files and start those
# services.
setup/tools/dns_update
setup/tools/web_update

# Give fail2ban another restart. The log files may not all have been present when
# fail2ban was first configured, but they should exist now.
restart_service fail2ban

# Register with Let's Encrypt, including agreeing to the Terms of Service.
# We'd let certbot ask the user interactively, but when this script is
# run in the recommended curl-pipe-to-bash method there is no TTY and
# certbot will fail if it tries to ask.
if [ ! -d "$STORAGE_ROOT/ssl/lets_encrypt/accounts/acme-v02.api.letsencrypt.org/" ]; then
	echo "Registering with Let's Encrypt (auto-accepting subscriber agreement)..."
	hide_output certbot register --register-unsafely-without-email --agree-tos --config-dir "$STORAGE_ROOT/ssl/lets_encrypt"
fi

if [ -n "${FIRST_TIME_SETUP:-}" ]; then
    # Done - generate bootstrap code and print the final summary.
    if [ -z "${NONINTERACTIVE:-}" ]; then
    	boxctl bootstrap --show-cert
    else
    	echo
    	echo "Mail-in-a-Box is running."
    	echo "Set MAILINABOX_BOOTSTRAP_EMAIL and MAILINABOX_BOOTSTRAP_PASSWORD to create the first admin account."
    	echo
    fi
fi
