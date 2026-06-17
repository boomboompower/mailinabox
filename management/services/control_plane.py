"""
Control-plane shim for service lifecycle actions.

Single interface; two backends:
  bare metal  - subprocess.run() directly (raises on failure)
  Docker      - Unix socket RPC to the container that owns the service
                (raises on failure, same semantics as bare metal)

Wire protocol (per connection, newline-delimited):
  Request:  "<service>\\n<action>\\n"
  Response: "OK\\n"  or  "ERROR: <message>\\n"

Socket paths: STORAGE_ROOT/sockets/<role>.sock
  dns.sock         -> nsd, unbound
  mail.sock        -> postfix, dovecot, opendkim, opendmarc, spampd
  nginx.sock       -> nginx
  filebrowser.sock -> filebrowser

Callers contain zero RUNTIME checks; all environment branching lives here.
"""
import os
import socket
import subprocess
from pathlib import Path

RUNTIME = os.environ.get("RUNTIME", "baremetal")

# Maps service name to the socket role that owns it.
_SERVICE_SOCKET: dict[str, str] = {
    "nsd":      "dns",
    "unbound":  "dns",
    "postfix":  "mail",
    "dovecot":  "mail",
    "opendkim": "mail",
    "opendmarc":"mail",
    "spampd":   "mail",
    "nginx":        "nginx",
    "filebrowser":  "filebrowser",
}

# Services whose bare-metal reload requires a non-standard command sequence.
# nsd uses nsd-control (not `service nsd reload`) for zone reconfig + reload.
_BARE_METAL_RELOAD: dict[str, list[list[str]]] = {
    "nsd": [
        ["/usr/sbin/nsd-control", "reconfig"],
        ["/usr/sbin/nsd-control", "reload"],
    ],
    # unbound cache flush is expressed as a "reload" at the caller level.
    "unbound": [
        ["/usr/sbin/unbound-control", "-c", "/etc/unbound/unbound.conf", "flush_zone", "."],
    ],
}

# Fallback restart command if a custom reload sequence fails.
_BARE_METAL_RELOAD_FALLBACK: dict[str, list[str]] = {
    "nsd": ["/usr/sbin/service", "nsd", "restart"],
}

def _socket_dir() -> Path:
    storage = os.environ.get("STORAGE_ROOT", "/home/user-data")
    return Path(storage) / "sockets"

def _send(service: str, action: str) -> None:
    role = _SERVICE_SOCKET.get(service)
    if not role:
        raise RuntimeError(f"control_plane: no socket role configured for service '{service}'")

    sock_path = _socket_dir() / f"{role}.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(35)
    try:
        sock.connect(str(sock_path))
        sock.sendall(f"{service}\n{action}\n".encode())
        response = sock.recv(256).decode().strip()
    finally:
        sock.close()

    if not response.startswith("OK"):
        raise RuntimeError(f"control_plane: {service} {action}: {response}")

def _run_bare_metal(service: str, action: str) -> None:
    if action == "reload" and service in _BARE_METAL_RELOAD:
        try:
            for cmd in _BARE_METAL_RELOAD[service]:
                subprocess.run(cmd, check=True)
        except Exception:
            fallback = _BARE_METAL_RELOAD_FALLBACK.get(service)
            if fallback:
                subprocess.run(fallback, check=True)
            else:
                raise
    elif action == "restart":
        subprocess.run(["/usr/sbin/service", service, "restart"], check=True)
    else:
        subprocess.run(["/usr/sbin/service", service, action], check=True)

def restart(service: str) -> None:
    """Restart a service. Raises on failure in both environments."""
    if RUNTIME == "docker":
        _send(service, "restart")
    else:
        _run_bare_metal(service, "restart")

def reload(service: str) -> None:
    """Reload a service config without dropping connections. Raises on failure."""
    if RUNTIME == "docker":
        _send(service, "reload")
    else:
        _run_bare_metal(service, "reload")

def stop(service: str) -> None:
    """Stop a service. Raises on failure in both environments."""
    if RUNTIME == "docker":
        _send(service, "stop")
    else:
        subprocess.run(["/usr/sbin/service", service, "stop"], check=True)

def disable(service: str) -> None:
    """Disable service autostart on boot.

    On bare metal this calls 'systemctl disable'. In Docker the container's
    presence in the compose profile controls autostart, so this is a no-op -
    the caller is expected to write the config flag before calling this.
    """
    if RUNTIME == "docker":
        return
    subprocess.run(["systemctl", "disable", service], check=True)
