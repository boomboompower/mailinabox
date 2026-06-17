#!/bin/bash
# Stub replacement for systemctl inside Docker containers.
#
# Install this file to /usr/local/bin/systemctl before sourcing any MIAB
# setup script.  Routes service-lifecycle verbs through the per-service
# handler scripts in /etc/miab/handlers/ (same dispatch path as the
# control-socket-server).  Falls back to supervisorctl for services that
# have no handler.
#
# Service names passed to systemctl may have a ".service" suffix; the stub
# strips it before dispatching.

svc="${2%.service}"

case "$1" in
    daemon-reload|enable|disable|is-enabled|unmask|link)
        exit 0
        ;;
    is-active)
        pgrep -x "${svc}" >/dev/null 2>&1
        exit $?
        ;;
    start|restart|reload|stop)
        # Dispatch through the per-service handler when supervisord is running,
        # so setup-script restarts use the same path as socket-server requests.
        # When supervisord is not yet running (first-time container setup),
        # silently skip: the service will start fresh under supervisord at the
        # end of the entrypoint anyway.
        if [ -x "/etc/miab/handlers/${svc}" ] && [ -S /run/supervisor.sock ]; then
            exec /etc/miab/handlers/"${svc}" "$1"
        else
            supervisorctl "${1}" "${svc}" 2>/dev/null || true
        fi
        ;;
    *)
        exit 0
        ;;
esac
