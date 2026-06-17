#!/bin/bash
# Spam filtering with spamassassin via spampd
# -------------------------------------------
#
# spampd sits between postfix and dovecot. It takes mail from postfix
# over the LMTP protocol, runs spamassassin on it, and then passes the
# message over LMTP to dovecot for local delivery.
#
# In order to move spam automatically into the Spam folder we use the dovecot sieve
# plugin.

source /etc/mailinabox.conf # get global vars
source setup/functions.sh # load our functions

# Install packages and basic configuration
# ----------------------------------------

# Install packages.
# libmail-dkim-perl is needed to make the spamassassin DKIM module work.
# For more information see Debian Bug #689414:
# https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=689414
echo "Installing SpamAssassin..."
DOVECOT_VERSION=$(dovecot --version 2>/dev/null | awk '{print $1}')
# dovecot-antispam is a 2.3-only third-party plugin; it does not exist in 2.4.
if printf '%s\n' "$DOVECOT_VERSION" | grep -q '^2\.3\.'; then
	apt_install_cached "spamassassin" spampd dovecot-antispam libmail-dkim-perl
else
	apt_install_cached "spamassassin" spampd libmail-dkim-perl
fi

# Allow spamassassin to download new rules.
# Ubuntu 24.04 no longer ships /etc/default/spamassassin (replaced by a systemd
# timer), so create it if absent so editconf.py doesn't abort on a missing file.
touch /etc/default/spamassassin
setup/tools/editconf.py /etc/default/spamassassin \
	CRON=1

# Configure spampd:
# * Pass messages on to docevot on port 10026. This is actually the default setting but we don't
#   want to lose track of it. (We've configured Dovecot to listen on this port elsewhere.)
# * Increase the maximum message size of scanned messages from the default of 64KB to 500KB, which
#   is Spamassassin (spamc)'s own default. Specified in KBytes.
# * Disable localmode so DKIM and DNS checks can be used.
# Ubuntu 24.04 may not ship /etc/default/spampd; create it if absent.
touch /etc/default/spampd
setup/tools/editconf.py /etc/default/spampd \
	DESTPORT=10026 \
	ADDOPTS="\"--maxsize=2000\"" \
	LOCALONLY=0

# Spamassassin normally wraps spam as an attachment inside a fresh
# email with a report about the message. This also protects the user
# from accidentally opening a message with embedded malware.
#
# It's nice to see what rules caused the message to be marked as spam,
# but it's also annoying to get to the original message when it is an
# attachment, modern mail clients are safer now and don't load remote
# content or execute scripts, and it is probably confusing to most users.
#
# Tell Spamassassin not to modify the original message except for adding
# the X-Spam-Status & X-Spam-Score mail headers and related headers.
setup/tools/editconf.py /etc/spamassassin/local.cf -s \
	report_safe=0 \
	"add_header all Report"=_REPORT_ \
	"add_header all Score"=_SCORE_


# Authentication-Results SPF/Dmarc checks
# ---------------------------------------
# OpenDKIM and OpenDMARC are configured to validate and add "Authentication-Results: ..."
# headers by checking the sender's SPF & DMARC policies. Instead of blocking mail that fails
# these checks, we can use these headers to evaluate the mail as spam.
#
# Our custom rules are added to their own file so that an update to the deb package config
# does not remove our changes.
#
# We need to escape period's in $PRIMARY_HOSTNAME since spamassassin config uses regex.

escapedprimaryhostname="${PRIMARY_HOSTNAME//./\\.}"

cat > /etc/spamassassin/miab_spf_dmarc.cf << EOF
# Evaluate DMARC Authentication-Results
header DMARC_PASS Authentication-Results =~ /$escapedprimaryhostname; dmarc=pass/
describe DMARC_PASS DMARC check passed
score DMARC_PASS -0.1

header DMARC_NONE Authentication-Results =~ /$escapedprimaryhostname; dmarc=none/
describe DMARC_NONE DMARC record not found
score DMARC_NONE 0.1

header DMARC_FAIL_NONE Authentication-Results =~ /$escapedprimaryhostname; dmarc=fail \(p=none/
describe DMARC_FAIL_NONE DMARC check failed (p=none)
score DMARC_FAIL_NONE 2.0

header DMARC_FAIL_QUARANTINE Authentication-Results =~ /$escapedprimaryhostname; dmarc=fail \(p=quarantine/
describe DMARC_FAIL_QUARANTINE DMARC check failed (p=quarantine)
score DMARC_FAIL_QUARANTINE 5.0

header DMARC_FAIL_REJECT Authentication-Results =~ /$escapedprimaryhostname; dmarc=fail \(p=reject/
describe DMARC_FAIL_REJECT DMARC check failed (p=reject)
score DMARC_FAIL_REJECT 10.0

# Evaluate SPF Authentication-Results
header SPF_PASS Authentication-Results =~ /$escapedprimaryhostname; spf=pass/
describe SPF_PASS SPF check passed
score SPF_PASS -0.1

header SPF_NONE Authentication-Results =~ /$escapedprimaryhostname; spf=none/
describe SPF_NONE SPF record not found
score SPF_NONE 2.0

header SPF_FAIL Authentication-Results =~ /$escapedprimaryhostname; spf=fail/
describe SPF_FAIL SPF check failed
score SPF_FAIL 5.0
EOF

# Bayesean learning
# -----------------
#
# Spamassassin can learn from mail marked as spam or ham, but it needs to be
# configured. We'll store the learning data in our storage area.
#
# These files must be:
#
# * Writable by sa-learn-pipe script below, which run as the 'mail' user, for manual tagging of mail as spam/ham.
# * Readable by the spampd process ('spampd' user) during mail filtering.
# * Writable by the debian-spamd user, which runs /etc/cron.daily/spamassassin.
#
# We'll have these files owned by spampd and grant access to the other two processes.
#
# Spamassassin will change the access rights back to the defaults, so we must also configure
# the filemode in the config file.

setup/tools/editconf.py /etc/spamassassin/local.cf -s \
	bayes_path="$STORAGE_ROOT/mail/spamassassin/bayes" \
	bayes_file_mode=0666

if [ ! -d "$STORAGE_ROOT/mail/spamassassin" ]; then
	mkdir -p "$STORAGE_ROOT/mail/spamassassin"
	chown -R spampd:spampd "$STORAGE_ROOT/mail/spamassassin"
else
	mkdir -p "$STORAGE_ROOT/mail/spamassassin"
fi

# To mark mail as spam or ham, just drag it in or out of the Spam folder.
# Dovecot detects the move and invokes sa-learn on the message.

if printf '%s\n' "$DOVECOT_VERSION" | grep -q '^2\.3\.'; then
	# Dovecot 2.3: use the third-party dovecot-antispam plugin.
	sed -i "s/#mail_plugins = .*/mail_plugins = \$mail_plugins antispam/" /etc/dovecot/conf.d/20-imap.conf
	sed -i "s/#mail_plugins = .*/mail_plugins = \$mail_plugins antispam/" /etc/dovecot/conf.d/20-pop3.conf

	cat > /etc/dovecot/conf.d/99-local-spampd.conf << 'EOF'
plugin {
    antispam_backend = pipe
    antispam_spam_pattern_ignorecase = SPAM
    antispam_trash_pattern_ignorecase = trash;Deleted *
    antispam_allow_append_to_spam = yes
    antispam_pipe_program_spam_args = /usr/local/bin/sa-learn-pipe.sh;--spam
    antispam_pipe_program_notspam_args = /usr/local/bin/sa-learn-pipe.sh;--ham
    antispam_pipe_program = /bin/bash
}
EOF

	rm -f /usr/bin/sa-learn-pipe.sh # legacy location #NODOC
	cat > /usr/local/bin/sa-learn-pipe.sh << 'EOF'
#!/bin/bash
cat <&0 >> /tmp/sendmail-msg-$$.txt
/usr/bin/sa-learn "$@" /tmp/sendmail-msg-$$.txt > /dev/null
rm -f /tmp/sendmail-msg-$$.txt
exit 0
EOF
	chmod a+x /usr/local/bin/sa-learn-pipe.sh

else
	# Dovecot 2.4: dovecot-antispam is gone. Use Pigeonhole's imapsieve plugin
	# instead. imap_sieve fires sieve scripts on IMAP COPY/APPEND/FLAG events.
	# sieve_extprograms provides the vnd.dovecot.pipe sieve extension to call
	# sa-learn. The /key=yes BOOLLIST syntax appends without replacing existing
	# mail_plugins values set by dovecot.sh.
	cat > /etc/dovecot/conf.d/99-local-spampd.conf << 'EOF'
protocol imap {
  mail_plugins/imap_sieve = yes
}

# sieve_imapsieve: sieve-side plugin that registers the imapsieve extension
# and imap.mailbox/imap.cause environment variables used in the scripts.
# sieve_extprograms: provides the vnd.dovecot.pipe sieve command.
sieve_plugins/sieve_imapsieve = yes
sieve_plugins/sieve_extprograms = yes
sieve_global_extensions/imapsieve = yes
sieve_global_extensions/vnd.dovecot.pipe = yes
sieve_pipe_bin_dir = /usr/local/bin

# When mail is moved FROM Spam: learn as ham.
imapsieve_from spam_to_ham {
  imapsieve_from_name = Spam

  sieve_script learn_ham {
    sieve_script_type = before
    sieve_script_cause = COPY
    sieve_script_driver = file
    sieve_script_path = /etc/dovecot/sieve/learn-ham.sieve
  }
}

# Runs on all COPY events; the script itself checks whether the
# destination mailbox is Spam before running sa-learn.
sieve_script learn_spam {
  sieve_script_type = before
  sieve_script_cause = COPY
  sieve_script_driver = file
  sieve_script_path = /etc/dovecot/sieve/learn-spam.sieve
}
EOF

	mkdir -p /etc/dovecot/sieve

	cat > /etc/dovecot/sieve/learn-spam.sieve << 'EOF'
require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];
if environment :matches "imap.mailbox" "Spam" {
    pipe :copy "sa-learn-spam.sh";
}
EOF

	cat > /etc/dovecot/sieve/learn-ham.sieve << 'EOF'
require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];
pipe :copy "sa-learn-ham.sh";
EOF

	# Do not pre-compile these with sievec - they use non-standard extensions
	# (imapsieve, vnd.dovecot.pipe) that sievec can't validate at setup time
	# before Dovecot has loaded the plugin .so files. Dovecot compiles them
	# lazily on first use, by which point all plugins are active.

	cat > /usr/local/bin/sa-learn-spam.sh << 'EOF'
#!/bin/bash
exec /usr/bin/sa-learn --spam
EOF
	cat > /usr/local/bin/sa-learn-ham.sh << 'EOF'
#!/bin/bash
exec /usr/bin/sa-learn --ham
EOF
	chmod a+x /usr/local/bin/sa-learn-spam.sh /usr/local/bin/sa-learn-ham.sh
fi

# Have Dovecot run its mail process with the spampd supplementary group
# so it can write to the shared bayes learning files.
setup/tools/editconf.py /etc/dovecot/conf.d/10-mail.conf \
	mail_access_groups=spampd

# Create empty bayes training data (if it doesn't exist). Once the files exist,
# ensure they are group-writable so that the Dovecot process has access.
if systemctl is-active --quiet spampd 2>/dev/null; then
	sudo -u spampd /usr/bin/sa-learn --sync 2>/dev/null
else
	echo "Skipping sa-learn sync - spampd not running yet."
fi
chmod -R 660 "$STORAGE_ROOT/mail/spamassassin"
chmod 770 "$STORAGE_ROOT/mail/spamassassin"

# Initial training?
# sa-learn --ham storage/mail/mailboxes/*/*/cur/
# sa-learn --spam storage/mail/mailboxes/*/*/.Spam/cur/

# Kick services.
restart_service spampd
restart_service dovecot

