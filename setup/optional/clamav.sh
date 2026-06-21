#!/bin/bash
# ClamAV - antivirus scanning for email attachments
# --------------------------------------------------
# On bare metal: installs clamav-milter so Postfix scans mail directly as a milter.
# Rspamd also connects to clamd via socket for in-process scanning.
# In Docker: the miab-clamav container provides clamav-milter over TCP.

source setup/functions.sh
source /etc/mailinabox.conf

echo "Installing ClamAV (antivirus)..."
if [ "${RUNTIME:-baremetal}" = "docker" ]; then
    # In Docker, only the base ClamAV packages are needed - the miab-clamav
    # container provides clamav-milter, and entrypoint.sh wires the milter.
    apt_install_cached "clamav" clamav clamav-daemon
else
    # Mask clamav-milter before install so dpkg's postinst doesn't try to start
    # it immediately (clamd isn't running yet and the milter would time out).
    # We unmask and start it ourselves after clamd is up.
    systemctl mask clamav-milter 2>/dev/null || true
    apt_install_cached "clamav" clamav clamav-daemon clamav-milter
fi

# freshclam downloads the signature database. Only run it if the DB files are
# missing - on reruns the running clamav-freshclam service keeps them current.
if [ ! -f /var/lib/clamav/main.cvd ] && [ ! -f /var/lib/clamav/main.cld ]; then
    echo "Downloading ClamAV signature database (first run, this may take a minute)..."
    systemctl stop clamav-freshclam 2>/dev/null || true
    hide_output freshclam || echo "WARNING: freshclam could not update signatures - check network connectivity."
fi

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

# On bare metal, configure clamav-milter so Postfix can scan mail as a milter.
# In Docker this is handled by the miab-clamav container and entrypoint.sh.
if [ "${RUNTIME:-baremetal}" != "docker" ]; then
    cat > /etc/clamav/clamav-milter.conf << 'EOF'
MilterSocket unix:/run/clamav/clamav-milter.sock
MilterSocketMode 660
PidFile /run/clamav/clamav-milter.pid
ClamdSocket unix:/run/clamav/clamd.ctl
OnInfected Reject
RejectMsg "Message rejected: virus detected"
AddHeader Replace
LogSyslog true
LogFacility LOG_MAIL
EOF

    append_milter "unix:/run/clamav/clamav-milter.sock"
fi

# Start daemon first - milter connects to clamd.ctl so it must be up before milter starts.
restart_service clamav-daemon
echo -n "Waiting for clamd socket..."
for i in $(seq 1 60); do
    [ -S /run/clamav/clamd.ctl ] && break
    sleep 2
done
[ -S /run/clamav/clamd.ctl ] && echo " ready." || echo " timed out (milter may fail to connect)."

if [ "${RUNTIME:-baremetal}" != "docker" ]; then
    systemctl unmask clamav-milter 2>/dev/null || true
    restart_service clamav-milter
fi
restart_service clamav-freshclam
