#!/bin/bash
#
# User Authentication and Destination Validation
# ----------------------------------------------
#
# This script configures user authentication for Dovecot
# and Postfix (which relies on Dovecot) and destination
# validation by querying an Sqlite3 database of mail users.

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

DOVECOT_VERSION=$(dovecot --version 2>/dev/null | awk '{print $1}')

# ### User and Alias Database

# The database of mail users (i.e. authenticated users, who have mailboxes)
# and aliases (forwarders).

db_path=$STORAGE_ROOT/mail/db/users.sqlite

# Create a shared group so postfix proxymap and dovecot auth-workers can write
# to the WAL -shm file. The database file is set to 660 (root:mail-db) so that
# SQLite copies that mode when creating -shm, making it group-writable.
# The setgid bit on the directory ensures new files inherit the mail-db group.
groupadd --system mail-db 2>/dev/null || true
usermod -aG mail-db postfix
usermod -aG mail-db dovecot

mkdir -p "$(dirname "$db_path")"
chown root:mail-db "$(dirname "$db_path")"
chmod 2770 "$(dirname "$db_path")"

# ### Postfix - Sender and Destination Validation

# Generate the sqlite map config files that Postfix uses to look up
# domains, mailboxes, aliases, and permitted senders.

cat > /etc/postfix/sender-login-maps.cf << EOF;
dbpath=$db_path
query=SELECT permitted_senders FROM (
  SELECT permitted_senders, 0 AS priority FROM aliases WHERE source='%s' AND permitted_senders IS NOT NULL
  UNION SELECT destination AS permitted_senders, 1 AS priority FROM aliases WHERE source='%s' AND permitted_senders IS NULL
  UNION SELECT email AS permitted_senders, 2 AS priority FROM users WHERE email='%s'
  ) ORDER BY priority LIMIT 1
EOF

cat > /etc/postfix/virtual-mailbox-domains.cf << EOF;
dbpath=$db_path
query=SELECT 1 FROM users WHERE email LIKE '%%@%s'
  UNION SELECT 1 FROM aliases WHERE source LIKE '%%@%s'
  UNION SELECT 1 FROM auto_aliases WHERE source LIKE '%%@%s'
  LIMIT 1
EOF

cat > /etc/postfix/virtual-mailbox-maps.cf << EOF;
dbpath=$db_path
query=SELECT 1 FROM users WHERE email='%s'
EOF

# Postfix queries this map multiple times per message: first the full address,
# then just @domain (catch-all). virtual-alias-maps has precedence over
# virtual-mailbox-maps, so catch-alls would swallow mail for real users unless
# users also appear here - hence the UNION on the users table (each user becomes
# an alias to themselves). The priority ordering ensures a direct alias wins over
# a user entry which wins over a catch-all. Records with empty destination are
# skipped so permitted_senders-only aliases don't accidentally absorb mail.
cat > /etc/postfix/virtual-alias-maps.cf << EOF;
dbpath=$db_path
query=SELECT destination FROM (
  SELECT destination, 0 AS priority FROM aliases WHERE source='%s' AND destination<>''
  UNION SELECT email AS destination, 1 AS priority FROM users WHERE email='%s'
  UNION SELECT destination, 2 AS priority FROM auto_aliases WHERE source='%s' AND destination<>''
  ) ORDER BY priority LIMIT 1
EOF

# Prevent intra-domain spoofing: the MAIL FROM address on outbound authenticated
# mail must be "owned" by the logged-in user (reject_authenticated_sender_login_mismatch).
# The query returns everyone permitted to send from a given address, checking aliases
# first (with explicit permitted_senders), then alias destinations, then direct users.
setup/tools/editconf.py /etc/postfix/main.cf \
	smtpd_sender_login_maps=proxy:sqlite:/etc/postfix/sender-login-maps.cf

# Disable SMTPUTF8: Dovecot's LMTP server doesn't support it, so any message
# received with the SMTPUTF8 flag would bounce on delivery.
# Use proxy:sqlite: so map lookups route through proxymap, which runs unchrooted
# and can access the database path. The chrooted smtpd cannot reach it directly.
setup/tools/editconf.py /etc/postfix/main.cf \
	smtputf8_enable=no \
	virtual_mailbox_domains=proxy:sqlite:/etc/postfix/virtual-mailbox-domains.cf \
	virtual_mailbox_maps=proxy:sqlite:/etc/postfix/virtual-mailbox-maps.cf \
	virtual_alias_maps=proxy:sqlite:/etc/postfix/virtual-alias-maps.cf \
	local_recipient_maps=\$virtual_mailbox_maps

# ### User Authentication

# Have Dovecot query our database, and not system users, for authentication.
sed -i "s/#*\(\!include auth-system.conf.ext\)/#\1/"  /etc/dovecot/conf.d/10-auth.conf
sed -i "s/#\(\!include auth-sql.conf.ext\)/\1/"  /etc/dovecot/conf.d/10-auth.conf

# Generate the Dovecot SQL config. Dovecot's auth master (root) opens the
# database directly; Postfix's sqlite driver also runs as root via master.cf.
cat > /etc/dovecot/dovecot-sql.conf.ext << EOF;
driver = sqlite
connect = $db_path
default_pass_scheme = BLF-CRYPT
password_query = SELECT password FROM users WHERE email='%Lu'
user_query = SELECT email, \
  '$STORAGE_ROOT/mail/mailboxes/%Ld/%Ln' AS home, \
  'mail' AS uid, 'mail' AS gid, \
  CASE WHEN quota='0' OR quota='' THEN '' ELSE concat('*:bytes=', quota) END AS quota_rule \
  FROM users WHERE email='%Lu'
iterate_query = SELECT email FROM users
EOF
chmod 0600 /etc/dovecot/dovecot-sql.conf.ext

# Have Dovecot provide an authorization service that Postfix can access & use.
cat > /etc/dovecot/conf.d/99-local-auth.conf << EOF;
service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0666
    user = postfix
    group = postfix
  }
}
EOF

# And have Postfix use that service. We *disable* it here
# so that authentication is not permitted on port 25 (which
# does not run DKIM on relayed mail, so outbound mail isn't
# correct, see #830), but we enable it specifically for the
# submission port.
setup/tools/editconf.py /etc/postfix/main.cf \
	smtpd_sasl_type=dovecot \
	smtpd_sasl_path=private/auth \
	smtpd_sasl_auth_enable=no

# Initialize the database schema and set the database file to 660 so that
# SQLite copies that mode to -shm on creation (SQLite's robust_open uses
# fchmod to match the db file permissions, bypassing the process umask).
STORAGE_ROOT="$STORAGE_ROOT" python3 -c "
import sys, os
sys.path.insert(0, 'management')
from mail import mailconfig
mailconfig.initialize_database({'STORAGE_ROOT': os.environ['STORAGE_ROOT']})
"

# Restart Services
##################

restart_service postfix
restart_service dovecot

# force a recalculation of all user quotas
if systemctl is-active --quiet dovecot 2>/dev/null; then
	doveadm quota recalc -A
else
	echo "Skipping quota recalculation - Dovecot not running yet."
fi
