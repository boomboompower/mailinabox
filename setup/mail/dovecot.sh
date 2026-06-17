#!/bin/bash
#
# Dovecot (IMAP/POP and LDA)
# ----------------------
#
# Dovecot is *both* the IMAP/POP server (the protocol that email applications
# use to query a mailbox) as well as the local delivery agent (LDA),
# meaning it is responsible for writing emails to mailbox storage on disk.
# You could imagine why these things would be bundled together.
#
# As part of local mail delivery, Dovecot executes actions on incoming
# mail as defined in a "sieve" script.
#
# Dovecot's LDA role comes after spam filtering. Postfix hands mail off
# to Spamassassin which in turn hands it off to Dovecot. This all happens
# using the LMTP protocol.

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

echo "Installing Dovecot (IMAP server)..."
apt_install_cached "dovecot" \
	dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd dovecot-sqlite sqlite3 \
	dovecot-sieve dovecot-managesieved

DOVECOT_VERSION=$(dovecot --version 2>/dev/null | awk '{print $1}')

# The `default_process_limit` is 100, which constrains the total number
# of active IMAP connections (at, say, 5 open connections per user that
# would be 20 users). Set it to 250 times the number of cores this
# machine has, so on a two-core machine that's 500 processes/100 users).
# The `default_vsz_limit` is the maximum amount of virtual memory that
# can be allocated. It should be set *reasonably high* to avoid allocation
# issues with larger mailboxes. We're setting it to 1/3 of the total
# available memory (physical mem + swap) to be sure.
setup/tools/editconf.py /etc/dovecot/conf.d/10-master.conf \
	default_process_limit="$(($(nproc) * 250))" \
	default_vsz_limit="$(($(free -tm | tail -1 | awk '{print $2}') / 3))M" \
	log_path=/var/log/mail.log

# The inotify `max_user_instances` default is 128, which constrains
# the total number of watched (IMAP IDLE push) folders by open connections.
mkdir -p /etc/sysctl.d
echo "fs.inotify.max_user_instances=1024" > /etc/sysctl.d/99-inotify.conf

# Create, subscribe, and mark as special folders: INBOX, Drafts, Sent, Trash, Spam and Archive.
cp setup/conf/mail/dovecot-mailboxes.conf /etc/dovecot/conf.d/15-mailboxes.conf

# Disable in-the-clear IMAP/POP. Only the over-TLS versions are exposed
# (IMAPS on port 993; POP3S on port 995).
sed -i "s/#port = 143/port = 0/" /etc/dovecot/conf.d/10-master.conf
sed -i "s/#port = 110/port = 0/" /etc/dovecot/conf.d/10-master.conf

# Make IMAP IDLE slightly more efficient. See [#129].
setup/tools/editconf.py /etc/dovecot/conf.d/20-imap.conf \
	imap_idle_notify_interval="4 mins"

# Setting a `postmaster_address` is required or LMTP won't start. An alias
# will be created automatically by our management daemon.
setup/tools/editconf.py /etc/dovecot/conf.d/15-lda.conf \
	"postmaster_address=postmaster@$PRIMARY_HOSTNAME"

# Have Dovecot query our database, and not system users, for authentication.
sed -i "s/#*\(\!include auth-system.conf.ext\)/#\1/" /etc/dovecot/conf.d/10-auth.conf
sed -i "s/#\(\!include auth-sql.conf.ext\)/\1/"      /etc/dovecot/conf.d/10-auth.conf

# DOVECOT_IMAP_BIND controls what address the plain IMAP listener (port 143)
# binds to. Default is 127.0.0.1 (loopback only). Set to 0.0.0.0 when the
# IMAP client runs on a separate host or container.
# LMTP stays on 127.0.0.1 - Postfix and spampd are always co-located.
IMAP_BIND="${DOVECOT_IMAP_BIND:-127.0.0.1}"

# ---------------------------------------------------------------------------
# Version-specific configuration
# Ubuntu 22.04/24.04 ship Dovecot 2.3; Ubuntu 26.04+ ships 2.4.
# Dovecot 2.4 is a significant breaking change: plugin{} blocks removed,
# settings renamed, passdb/userdb args gone, sieve config completely rewritten.
# ---------------------------------------------------------------------------

if printf '%s\n' "$DOVECOT_VERSION" | grep -q '^2\.4\.'; then

	# Opt in to the new config format. Without these, old-style plugin{} blocks
	# and renamed settings cause fatal startup failures.
	setup/tools/editconf.py /etc/dovecot/dovecot.conf \
		"dovecot_config_version=2.4.0" \
		"dovecot_storage_version=2.4.0"

	# mail_location split into mail_driver + mail_path. Variable syntax changed:
	# %d -> %{user|domain}, %n -> %{user|username}.
	setup/tools/editconf.py /etc/dovecot/conf.d/10-mail.conf \
		mail_driver=maildir \
		"mail_path=$STORAGE_ROOT/mail/mailboxes/%{user|domain}/%{user|username}" \
		mail_privileged_group=mail \
		first_valid_uid=0

	# disable_plaintext_auth (inverted) renamed to auth_allow_cleartext.
	setup/tools/editconf.py /etc/dovecot/conf.d/10-auth.conf \
		"auth_mechanisms=plain login" \
		"auth_allow_cleartext=no"

	# ssl_cert/ssl_key renamed to ssl_server_cert_file/ssl_server_key_file
	# (no < prefix needed). ssl_min_protocol gone (TLSv1.2 is the 2.4 floor).
	# ssl_prefer_server_ciphers renamed to ssl_server_prefer_ciphers with
	# value changed from yes/no to server/client.
	setup/tools/editconf.py /etc/dovecot/conf.d/10-ssl.conf \
		ssl=required \
		"ssl_server_cert_file=$STORAGE_ROOT/ssl/ssl_certificate.pem" \
		"ssl_server_key_file=$STORAGE_ROOT/ssl/ssl_private_key.pem" \
		"ssl_cipher_list=ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305" \
		"ssl_server_prefer_ciphers=client"

	# mail_plugins is a BOOLLIST in 2.4. The parser does not expand $variable
	# references, so the 2.3 "$mail_plugins quota" idiom fatally fails to load
	# a plugin literally named "$mail_plugins". Use plain names instead.
	sed -i "s/#mail_plugins =.*/mail_plugins = quota/" /etc/dovecot/conf.d/10-mail.conf
	if ! grep -q "mail_plugins.*imap_quota" /etc/dovecot/conf.d/20-imap.conf; then
		sed -i "s/\(mail_plugins =.*\)/\1\n  mail_plugins = imap_quota/" /etc/dovecot/conf.d/20-imap.conf
	fi
	sed -i "s/#mail_plugins = .*/mail_plugins = sieve/" /etc/dovecot/conf.d/20-lmtp.conf

	# quota: plugin{} removed. Quota roots use SET_FILTER_ARRAY syntax.
	# The old "maildir:Name" combined form is gone. quota_storage_grace is
	# now a SIZE (bytes); default 10M matches the 2.3 10% spirit.
	cat > /etc/dovecot/conf.d/90-quota.conf << 'EOF'
quota quota {
    quota_driver = maildir
    quota_storage_grace = 10M
}

quota_status_success = DUNNO
quota_status_nouser = DUNNO
quota_status_overquota = "522 5.2.2 Mailbox is full"

service quota-status {
    executable = quota-status -p postfix
    inet_listener quota-status {
        port = 12340
    }
}
EOF

	# 2.4 default pop3_uidl_format (%{uid | hex(8)}%{uidvalidity | hex(8)}) is
	# equivalent to the old %08Xu%08Xv, and the old printf-style format is not
	# understood by the new var_expand engine. Leave it at the default.

	# 'address' removed from inet_listener blocks. Bind address is now set via
	# 'listen' (the global listen setting, scopeable per-listener).
	cat > /etc/dovecot/conf.d/99-local.conf << EOF
service lmtp {
  inet_listener lmtp {
    listen = 127.0.0.1
    port = 10026
  }
}

service imap-login {
  inet_listener imap {
    listen = $IMAP_BIND
    port = 143
    ssl = no
  }
}
protocol imap {
  mail_max_userip_connections = 40
}
EOF

	# sieve: plugin{} completely removed when dovecot_config_version=2.4.0.
	# Pigeonhole 2.4 replaced sieve_before/after/dir with sieve_script filter
	# blocks. sieve_script_active_path replaces the old 'sieve =' symlink setting.
	cat > /etc/dovecot/conf.d/99-local-sieve.conf << EOF
sieve_redirect_envelope_from = recipient

sieve_script spam {
  sieve_script_type = before
  sieve_script_driver = file
  sieve_script_path = /etc/dovecot/sieve-spam.sieve
  sieve_script_precedence = 10
}

sieve_script global_before {
  sieve_script_type = before
  sieve_script_driver = file
  sieve_script_path = $STORAGE_ROOT/mail/sieve/global_before
  sieve_script_precedence = 20
}

sieve_script global_after {
  sieve_script_type = after
  sieve_script_driver = file
  sieve_script_path = $STORAGE_ROOT/mail/sieve/global_after
}

sieve_script personal {
  sieve_script_type = personal
  sieve_script_driver = file
  sieve_script_path = $STORAGE_ROOT/mail/sieve/%{user|domain}/%{user|username}
  sieve_script_active_path = $STORAGE_ROOT/mail/sieve/%{user|domain}/%{user|username}.sieve
}
EOF

else # Dovecot 2.3

	setup/tools/editconf.py /etc/dovecot/conf.d/10-mail.conf \
		"mail_location=maildir:$STORAGE_ROOT/mail/mailboxes/%d/%n" \
		mail_privileged_group=mail \
		first_valid_uid=0

	setup/tools/editconf.py /etc/dovecot/conf.d/10-auth.conf \
		disable_plaintext_auth=yes \
		"auth_mechanisms=plain login"

	# Dovecot 2.3 does not support TLSv1.3, so we cap at TLSv1.2.
	setup/tools/editconf.py /etc/dovecot/conf.d/10-ssl.conf \
		ssl=required \
		"ssl_cert=<$STORAGE_ROOT/ssl/ssl_certificate.pem" \
		"ssl_key=<$STORAGE_ROOT/ssl/ssl_private_key.pem" \
		"ssl_min_protocol=TLSv1.2" \
		"ssl_cipher_list=ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305" \
		"ssl_prefer_server_ciphers=no"

	sed -i "s/#mail_plugins =\(.*\)/mail_plugins =\1 \$mail_plugins quota/" /etc/dovecot/conf.d/10-mail.conf
	if ! grep -q "mail_plugins.* imap_quota" /etc/dovecot/conf.d/20-imap.conf; then
		sed -i "s/\(mail_plugins =.*\)/\1\n  mail_plugins = \$mail_plugins imap_quota/" /etc/dovecot/conf.d/20-imap.conf
	fi
	sed -i "s/#mail_plugins = .*/mail_plugins = \$mail_plugins sieve/" /etc/dovecot/conf.d/20-lmtp.conf

	if ! grep -q "quota_status_success = DUNNO" /etc/dovecot/conf.d/90-quota.conf 2>/dev/null \
	   || grep -q "quota maildir:" /etc/dovecot/conf.d/90-quota.conf 2>/dev/null; then
		cat > /etc/dovecot/conf.d/90-quota.conf << 'EOF'
plugin {
  quota = maildir

  quota_grace = 10%

  quota_status_success = DUNNO
  quota_status_nouser = DUNNO
  quota_status_overquota = "522 5.2.2 Mailbox is full"
}

service quota-status {
    executable = quota-status -p postfix
    inet_listener {
        port = 12340
    }
}
EOF
	fi

	setup/tools/editconf.py /etc/dovecot/conf.d/20-pop3.conf \
		pop3_uidl_format="%08Xu%08Xv"

	cat > /etc/dovecot/conf.d/99-local.conf << EOF
service lmtp {
  inet_listener lmtp {
    address = 127.0.0.1
    port = 10026
  }
}

service imap-login {
  inet_listener imap {
    address = $IMAP_BIND
    port = 143
    ssl = no
  }
}
protocol imap {
  mail_max_userip_connections = 40
}
EOF

	cat > /etc/dovecot/conf.d/99-local-sieve.conf << EOF
plugin {
  sieve_before = /etc/dovecot/sieve-spam.sieve
  sieve_before2 = $STORAGE_ROOT/mail/sieve/global_before
  sieve_after = $STORAGE_ROOT/mail/sieve/global_after
  sieve = $STORAGE_ROOT/mail/sieve/%d/%n.sieve
  sieve_dir = $STORAGE_ROOT/mail/sieve/%d/%n
  sieve_redirect_envelope_from = recipient
}
EOF

fi # end version-specific configuration

# Copy the global sieve script and compile it. Global scripts must be
# compiled now because Dovecot won't have permission later.
cp setup/conf/mail/sieve-spam.txt /etc/dovecot/sieve-spam.sieve
sievec /etc/dovecot/sieve-spam.sieve

# Ensure configuration files are owned by dovecot and not world readable.
if [ "$(stat -c %U /etc/dovecot)" != "mail" ]; then
	chown -R mail:dovecot /etc/dovecot
fi
chmod -R o-rwx /etc/dovecot

# Ensure mailbox files have a directory that exists and are owned by the mail user.
# Only chown -R on creation - on a live server this would traverse the entire mail store.
if [ ! -d "$STORAGE_ROOT/mail/mailboxes" ]; then
	mkdir -p "$STORAGE_ROOT/mail/mailboxes"
	chown -R mail:mail "$STORAGE_ROOT/mail/mailboxes"
else
	mkdir -p "$STORAGE_ROOT/mail/mailboxes"
fi

# Same for the sieve scripts.
if [ ! -d "$STORAGE_ROOT/mail/sieve" ]; then
	mkdir -p "$STORAGE_ROOT/mail/sieve"
	mkdir -p "$STORAGE_ROOT/mail/sieve/global_before"
	mkdir -p "$STORAGE_ROOT/mail/sieve/global_after"
	chown -R mail:mail "$STORAGE_ROOT/mail/sieve"
else
	mkdir -p "$STORAGE_ROOT/mail/sieve/global_before"
	mkdir -p "$STORAGE_ROOT/mail/sieve/global_after"
fi

# Allow the IMAP/POP ports in the firewall.
ufw_allow imaps
ufw_allow pop3s

# Allow the Sieve port in the firewall.
ufw_allow sieve

restart_service dovecot
