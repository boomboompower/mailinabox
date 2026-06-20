#!/bin/bash
# Rspamd - spam filtering, DKIM signing/verification, DMARC, greylisting
# -----------------------------------------------------------------------
# Rspamd is a milter. It replaces SpamAssassin/spampd, OpenDKIM, OpenDMARC,
# and Postgrey in one service. Mail flows: Postfix -> Rspamd (milter) ->
# Dovecot LMTP directly (no spampd relay).
#
# Redis is required for greylisting state, rate limiting, and Bayes learning.

source setup/functions.sh
source /etc/mailinabox.conf

echo "Installing Rspamd (spam filter, DKIM, DMARC, greylisting)..."

apt_install_cached "rspamd" rspamd redis-server

systemctl enable redis-server
restart_service redis-server

# ── DKIM key ───────────────────────────────────────────────────────────────────

mkdir -p "$STORAGE_ROOT/mail/dkim"

# Generate key if it doesn't exist. Uses the same path and selector as the
# OpenDKIM path so the DNS record (managed by the management daemon) is
# identical regardless of which spam filter is active.
if [ ! -f "$STORAGE_ROOT/mail/dkim/mail.private" ]; then
    rspamadm dkim_keygen -s mail -b 2048 -k "$STORAGE_ROOT/mail/dkim/mail.private" \
        > "$STORAGE_ROOT/mail/dkim/mail.txt"
    chmod 644 "$STORAGE_ROOT/mail/dkim/mail.txt"
fi

# The rspamd worker runs as _rspamd. Fix ownership so it can read the key.
chown root:_rspamd "$STORAGE_ROOT/mail/dkim"
chmod 750 "$STORAGE_ROOT/mail/dkim"
chown root:_rspamd "$STORAGE_ROOT/mail/dkim/mail.private"
chmod 640 "$STORAGE_ROOT/mail/dkim/mail.private"

# ── Rspamd config ──────────────────────────────────────────────────────────────

mkdir -p /etc/rspamd/local.d

# Redis - used by greylisting, rate limiting, Bayes, fuzzy hashes.
cat > /etc/rspamd/local.d/redis.conf << 'EOF'
servers = "127.0.0.1";
EOF

# Milter proxy worker - Postfix connects here on port 11332.
cat > /etc/rspamd/local.d/worker-proxy.inc << 'EOF'
bind_socket = "127.0.0.1:11332";
timeout = 120s;
upstream "local" {
  default = yes;
  self_scan = yes;
}
EOF

# DKIM signing for outbound mail. Uses the same key location as OpenDKIM.
cat > /etc/rspamd/local.d/dkim_signing.conf << EOF
allow_username_mismatch = true;
use_domain = "envelope";
path = "$STORAGE_ROOT/mail/dkim/\${selector}.private";
selector = "mail";
sign_authenticated = true;
sign_local = true;
EOF

# Greylisting via Redis. Short timeout (60s) is enough to deter non-retrying bots;
# DKIM_ALLOW skips greylisting entirely for mail with a valid DKIM signature.
cat > /etc/rspamd/local.d/greylisting.conf << 'EOF'
enabled = true;
timeout = 60;
expire = 86400;
whitelist_symbols = ["DKIM_ALLOW"];
EOF

# DMARC verification. No outbound reports - not a reporting MTA.
cat > /etc/rspamd/local.d/dmarc.conf << 'EOF'
reporting {
  enabled = false;
}
EOF

# Authentication-Results and spam score headers on processed messages.
cat > /etc/rspamd/local.d/milter_headers.conf << 'EOF'
use = ["x-spam-status", "x-spam-score", "authentication-results"];
extended_spam_headers = true;
EOF

# Spam action thresholds.
cat > /etc/rspamd/local.d/actions.conf << 'EOF'
reject = 15;
add_header = 6;
greylist = 4;
EOF

# ── Postfix milter + transport wiring ─────────────────────────────────────────

# Rspamd is a milter - Postfix delivers directly to Dovecot LMTP, no spampd needed.
setup/tools/editconf.py /etc/postfix/main.cf \
    "virtual_transport=lmtp:unix:private/dovecot-lmtp"
setup/tools/editconf.py /etc/postfix/main.cf -e \
    lmtp_destination_recipient_limit=

append_milter "inet:127.0.0.1:11332"

# Rspamd handles greylisting internally via Redis - drop the Postgrey policy check.
# Dovecot quota policy (12340) stays.
setup/tools/editconf.py /etc/postfix/main.cf \
    smtpd_recipient_restrictions="permit_sasl_authenticated,permit_mynetworks,reject_rbl_client zen.spamhaus.org=127.0.0.[2..11],reject_unlisted_recipient,check_policy_service inet:127.0.0.1:12340"

# ── Stop dead services from the SpamAssassin path ─────────────────────────────

for svc in spampd opendkim opendmarc postgrey; do
    systemctl stop    "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
done

restart_service rspamd
restart_service postfix
