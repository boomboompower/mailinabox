#!/bin/bash
# ClamAV - antivirus scanning for email attachments
# --------------------------------------------------
# ClamAV scans mail passing through the spam filter.
# With Rspamd: the antivirus module connects to clamd via socket.
# With SpamAssassin: the ClamAV plugin scores infected mail.

source setup/functions.sh
source /etc/mailinabox.conf

echo "Installing ClamAV (antivirus)..."
apt_install_cached "clamav" clamav clamav-daemon

# freshclam downloads the signature database on first run. This can take
# a minute. Run it once now so the daemon starts with an up-to-date DB.
# Stop freshclam first if it's running (it locks the DB file).
systemctl stop clamav-freshclam 2>/dev/null || true
hide_output freshclam || echo "WARNING: freshclam could not update signatures - check network connectivity."

# Point clamd at the default socket path that Rspamd's antivirus module expects.
setup/tools/editconf.py /etc/clamav/clamd.conf -s \
    "LocalSocket=/run/clamav/clamd.ctl" \
    "LocalSocketMode=666" \
    "LogSyslog=true" \
    "LogFacility=LOG_MAIL"

# Wire into Rspamd if that's the active spam filter.
if [ "${SPAM_FILTER:-rspamd}" = "rspamd" ]; then
    mkdir -p /etc/rspamd/local.d
    cat > /etc/rspamd/local.d/antivirus.conf << 'EOF'
clamav {
    action = "reject";
    symbol = "CLAM_VIRUS";
    type = "clamav";
    log_clean = false;
    servers = "/run/clamav/clamd.ctl";
    scan_mime_parts = true;
    scan_text_mime = false;
    scan_image_mime = false;
    max_size = 20971520; # 20MB
}
EOF
    restart_service rspamd
fi

restart_service clamav-daemon
restart_service clamav-freshclam
