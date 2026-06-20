#!/bin/bash
# ClamAV container entrypoint.
# Runs clamd (virus scanner) and clamav-milter (Postfix milter interface).
# The mail container connects to clamav-milter on TCP port 7357.

set -euo pipefail

# Ensure run directory exists with correct ownership.
mkdir -p /run/clamav
chown clamav:clamav /run/clamav

# Configure clamd to listen on a local TCP port so clamav-milter can reach it.
# The default config listens on a unix socket which is fine inside this container.
cat > /etc/clamav/clamd.conf << 'EOF'
LocalSocket /run/clamav/clamd.ctl
LocalSocketMode 666
LogSyslog true
LogFacility LOG_MAIL
# Allow clamav-milter (same container) to connect
TCPSocket 3310
TCPAddr 127.0.0.1
EOF

# Configure clamav-milter to listen on all interfaces over TCP so the mail
# container can connect, and talk to clamd via the local TCP port.
cat > /etc/clamav/clamav-milter.conf << 'EOF'
MilterSocket inet:7357
ClamdSocket tcp:127.0.0.1:3310
OnInfected Reject
RejectMsg "Message rejected: virus detected"
AddHeader Replace
LogSyslog true
LogFacility LOG_MAIL
EOF

# Update virus signatures before starting.
echo "Updating ClamAV signatures..."
freshclam || echo "WARNING: freshclam could not update signatures - check network connectivity."

echo "ClamAV setup complete. Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
