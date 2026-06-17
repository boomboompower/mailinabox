"""
boxctl doctor - live status check and service management for a running box.

Scans all services, shows health status, lets you manage each one.
Navigate with ↑↓, Enter to open a service, Esc to quit.
Exits non-zero if any service is degraded.
"""

import os, sys, subprocess, datetime, tarfile, socket, re
from .ui import (
    bold, gray_desc, lavender, white_b, red, green,
    Raw, read_key, clear, _term_width,
)

BARE_METAL_CONF = "/etc/mailinabox.conf"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK   = "ok"
WARN = "warn"
ERR  = "error"
OFF  = "off"

# ── Low-level probes ───────────────────────────────────────────────────────────

def _systemd_active(service):
    r = subprocess.run(["systemctl", "is-active", "--quiet", service], capture_output=True)
    return r.returncode == 0

def _systemd_installed(service):
    r = subprocess.run(["systemctl", "cat", service], capture_output=True)
    return r.returncode == 0

def _port_open(host, port, timeout=2):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def _cert_days(storage_root):
    cert = os.path.join(storage_root, "ssl", "ssl_certificate.pem")
    if not os.path.exists(cert):
        return None
    r = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", cert],
        capture_output=True, text=True,
    )
    m = re.search(r"notAfter=(.+)", r.stdout)
    if not m:
        return None
    try:
        expiry = datetime.datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
        return (expiry - datetime.datetime.utcnow()).days
    except ValueError:
        return None

# ── Service checks ─────────────────────────────────────────────────────────────

def check_mail(conf):
    ok_p = _systemd_active("postfix")
    ok_d = _systemd_active("dovecot")
    smtp = _port_open("127.0.0.1", 25)
    imap = _port_open("127.0.0.1", 143)
    if ok_p and ok_d and smtp and imap:
        return OK, "Postfix + Dovecot running"
    parts = []
    if not ok_p: parts.append("Postfix not active")
    if not ok_d: parts.append("Dovecot not active")
    if not smtp: parts.append("SMTP port 25 not responding")
    if not imap: parts.append("IMAP port 143 not responding")
    return ERR, "; ".join(parts)

def check_spam(conf):
    spam = conf.get("SPAM_FILTER", "rspamd")
    if spam == "rspamd":
        if not _systemd_active("rspamd"):
            return ERR, "Rspamd not running"
        if not _port_open("127.0.0.1", 11332):
            return WARN, "Rspamd running but milter port 11332 not responding"
        redis = _systemd_active("redis-server")
        if not redis:
            return WARN, "Rspamd running but Redis not active (greylisting/Bayes affected)"
        return OK, "Rspamd running (milter active)"
    else:
        if not _systemd_active("spampd"):
            return ERR, "spampd not running"
        if not _systemd_active("opendkim"):
            return WARN, "spampd running but OpenDKIM not active"
        return OK, "SpamAssassin + spampd running"

def check_webmail(conf):
    client = conf.get("WEBMAIL_CLIENT", "oxi")
    if client == "none":
        return OFF, "No webmail configured"
    if client == "oxi":
        if not _systemd_active("oxi-email"):
            return ERR, "oxi-email service not running"
        if not _port_open("127.0.0.1", 3001):
            return WARN, "oxi-email running but not responding on port 3001"
        return OK, "oxi.email running"
    # php-fpm service name varies by version; use shell glob
    r = subprocess.run("systemctl is-active php*-fpm 2>/dev/null",
                       capture_output=True, text=True, shell=True)
    fpm_ok = r.stdout.strip() == "active"
    label = {"roundcube": "Roundcube", "snappymail": "SnappyMail", "cypht": "Cypht"}.get(client, client)
    if not fpm_ok:
        return ERR, f"{label} installed but PHP-FPM not running"
    return OK, f"{label} running via PHP-FPM"

def check_dns(conf):
    if not _systemd_active("nsd"):
        return ERR, "NSD not running"
    # NSD binds to external interfaces only, not loopback - use nsd-control
    r = subprocess.run(["nsd-control", "status"], capture_output=True)
    if r.returncode != 0:
        return WARN, "NSD running but nsd-control status failed"
    return OK, "NSD running"

def check_certs(conf):
    storage_root = conf.get("STORAGE_ROOT", "/home/user-data")
    days = _cert_days(storage_root)
    if days is None:
        return WARN, "Could not read certificate expiry"
    if days < 0:
        return ERR, "Certificate has expired"
    if days < 14:
        return WARN, f"Certificate expires in {days} days - renewal needed"
    if days < 30:
        return WARN, f"Certificate expires in {days} days"
    return OK, f"Valid (expires in {days} days)"

def check_radicale(conf):
    if conf.get("ENABLE_RADICALE", "true") != "true":
        return OFF, "Disabled"
    if not _systemd_active("radicale"):
        r = subprocess.run(
            ["systemctl", "show", "radicale", "--property=ExecMainStatus"],
            capture_output=True, text=True,
        )
        if "ExecMainStatus=226" in r.stdout:
            return ERR, "Crash loop: kernel lacks mount namespace support (226/NAMESPACE)"
        return ERR, "Radicale not running"
    if not _port_open("127.0.0.1", 5232):
        return WARN, "Radicale running but port 5232 not responding"
    return OK, "Running"

def check_filebrowser(conf):
    if conf.get("ENABLE_FILEBROWSER", "true") != "true":
        return OFF, "Disabled"
    if not _systemd_active("filebrowser"):
        return ERR, "FileBrowser not running"
    if not _port_open("127.0.0.1", 8080):
        return WARN, "FileBrowser running but not responding on port 8080"
    return OK, "Running"

def check_nginx(conf):
    if not _systemd_active("nginx"):
        return ERR, "nginx not running"
    if not _port_open("127.0.0.1", 443):
        return WARN, "nginx running but HTTPS port 443 not responding"
    return OK, "Running"

def check_unbound(conf):
    if not _systemd_active("unbound"):
        return ERR, "Unbound not running (DANE and DNS blocklists affected)"
    if not _port_open("127.0.0.1", 53):
        return WARN, "Unbound running but port 53 not responding"
    return OK, "Running"

def check_clamav(conf):
    if conf.get("ENABLE_CLAMAV", "false") != "true":
        if _systemd_installed("clamav-daemon"):
            return OFF, "Installed but disabled"
        return OFF, "Not installed"
    if not _systemd_active("clamav-daemon"):
        return ERR, "ClamAV daemon not running"
    clamd_sock = "/run/clamav/clamd.ctl"
    if not os.path.exists(clamd_sock):
        return WARN, "clamav-daemon running but socket not ready yet"
    return OK, "Running"

# ── Service registry ───────────────────────────────────────────────────────────
# Each entry: (key, label, check_fn)
SERVICES = [
    ("nginx",       "nginx",        check_nginx),
    ("mail",        "Mail",         check_mail),
    ("spam",        "Spam",         check_spam),
    ("dns",         "DNS",          check_dns),
    ("unbound",     "Unbound",      check_unbound),
    ("certs",       "Certificates", check_certs),
    ("webmail",     "Webmail",      check_webmail),
    ("radicale",    "Radicale",     check_radicale),
    ("filebrowser", "FileBrowser",  check_filebrowser),
    ("clamav",      "ClamAV",       check_clamav),
]

# ── Backup + apply helpers ─────────────────────────────────────────────────────

_BACKUP_PATHS = {
    "WEBMAIL_CLIENT:roundcube":  ["roundcube"],
    "WEBMAIL_CLIENT:snappymail": ["snappymail"],
    "WEBMAIL_CLIENT:cypht":      ["cypht"],
    "SPAM_FILTER:spamassassin":  ["mail/spamassassin"],
    "ENABLE_RADICALE:true":      ["mail/radicale"],
    "ENABLE_FILEBROWSER:true":   ["filebrowser"],
}

_STOP_SERVICES = {
    "WEBMAIL_CLIENT:oxi":        ["oxi-email"],
    "WEBMAIL_CLIENT:roundcube":  [],
    "WEBMAIL_CLIENT:snappymail": [],
    "WEBMAIL_CLIENT:cypht":      [],
    "WEBMAIL_CLIENT:none":       [],
    "SPAM_FILTER:spamassassin":  ["spampd", "opendkim", "opendmarc", "postgrey"],
    "SPAM_FILTER:rspamd":        ["rspamd", "redis-server"],
    "ENABLE_RADICALE:true":      ["radicale"],
    "ENABLE_FILEBROWSER:true":   ["filebrowser"],
    "ENABLE_CLAMAV:true":        ["clamav-daemon", "clamav-freshclam"],
}

_SETUP_SEQUENCES = {
    "WEBMAIL_CLIENT:oxi":          ["setup/webmail/oxi.sh"],
    "WEBMAIL_CLIENT:roundcube":    ["setup/webmail/roundcube.sh"],
    "WEBMAIL_CLIENT:snappymail":   ["setup/webmail/snappymail.sh"],
    "WEBMAIL_CLIENT:cypht":        ["setup/webmail/cypht.sh"],
    "WEBMAIL_CLIENT:none":         [],
    "SPAM_FILTER:rspamd":          ["setup/mail/rspamd.sh"],
    "SPAM_FILTER:spamassassin":    ["setup/mail/dkim.sh", "setup/mail/spamassassin.sh"],
    "ENABLE_RADICALE:true":        ["setup/optional/radicale.sh"],
    "ENABLE_RADICALE:false":       [],
    "ENABLE_FILEBROWSER:true":     ["setup/optional/filebrowser.sh"],
    "ENABLE_FILEBROWSER:false":    [],
    "ENABLE_CLAMAV:true":          ["setup/optional/clamav.sh"],
    "ENABLE_CLAMAV:false":         [],
}

# Keys that affect postfix wiring and need postfix.sh re-run
_NEEDS_POSTFIX = {"SPAM_FILTER"}

def _backup(storage_root, conf_key):
    paths = _BACKUP_PATHS.get(conf_key, [])
    existing = [os.path.join(storage_root, p) for p in paths
                if os.path.exists(os.path.join(storage_root, p))]
    if not existing:
        return None
    backup_dir = os.path.join(storage_root, "backups", "doctor")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = conf_key.replace(":", "-").replace("_", "").lower()
    archive = os.path.join(backup_dir, f"{ts}-{label}.tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in existing:
            tar.add(path, arcname=os.path.relpath(path, storage_root))
    return archive

def _stop(conf_key):
    for svc in _STOP_SERVICES.get(conf_key, []):
        subprocess.run(["systemctl", "stop",    svc], capture_output=True)
        subprocess.run(["systemctl", "disable", svc], capture_output=True)

def _run_scripts(conf_key, conf):
    scripts = _SETUP_SEQUENCES.get(conf_key, [])
    for script in scripts:
        result = subprocess.run(
            ["bash", "-c", f"set -e; source setup/functions.sh; source {BARE_METAL_CONF}; source {script}"],
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            return False
    if _NEEDS_POSTFIX.intersection(conf_key.split(":")):
        result = subprocess.run(
            ["bash", "-c", f"set -e; source setup/functions.sh; source {BARE_METAL_CONF}; source setup/mail/postfix.sh"],
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            return False
    return True

def _write_conf_key(key, value):
    lines = []
    found = False
    with open(BARE_METAL_CONF) as f:
        for line in f:
            if line.strip().startswith(key + "=") and not line.strip().startswith("#"):
                lines.append(f"{key}={value}\n")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(BARE_METAL_CONF, "w") as f:
        f.writelines(lines)

def _regenerate(conf):
    try:
        api_key_file = os.path.join(conf.get("STORAGE_ROOT", "/home/user-data"), "api.key")
        if not os.path.exists(api_key_file):
            return False
        import urllib.request, urllib.error
        with open(api_key_file) as f:
            api_key = f.read().strip()
        for endpoint in ["/dns/update", "/web/update"]:
            req = urllib.request.Request(
                f"http://127.0.0.1:10222{endpoint}",
                data=b"", method="POST",
                headers={"X-Api-Key": api_key},
            )
            urllib.request.urlopen(req, timeout=30)
        return True
    except Exception:
        return False

# ── UI rendering ───────────────────────────────────────────────────────────────

_STATUS_ICON = {
    OK:   lambda s: f"\033[38;2;95;255;135m✓\033[0m",
    WARN: lambda s: f"\033[38;2;255;215;0m!\033[0m",
    ERR:  lambda s: f"\033[38;2;255;85;85m✗\033[0m",
    OFF:  lambda s: f"\033[38;2;103;105;114m-\033[0m",
}

def _icon(status):
    return _STATUS_ICON.get(status, lambda s: "-")(status)

def _press_enter_to_return():
    """Wait for Enter/Esc in raw mode (safe to call while already in Raw())."""
    print(f"\n  {gray_desc('Press Enter to return...')}", end="", flush=True)
    while True:
        k = read_key()
        if k in ('enter', 'esc', 'ctrl_c'):
            break
    print()


def _render_list(services, results, sel, first=False):
    if first:
        print("\033[s", end="", flush=True)
    else:
        print("\033[u\033[J", end="", flush=True)

    out = []
    label_w = max(len(label) for _, label, _ in services) + 2
    for i, (key, label, _) in enumerate(services):
        status, msg = results.get(key, (OFF, "checking..."))
        icon  = _icon(status)
        pad   = " " * (label_w - len(label))
        arrow = lavender("❯") if i == sel else " "
        lbl   = lavender(label, bold=True) if i == sel else white_b(label)
        out.append(f"  {arrow} {icon}  {lbl}{pad}{gray_desc(msg)}")

    out.append("")
    out.append(f"  {gray_desc('↑↓ navigate  ·  Enter to manage  ·  Esc to quit')}")

    text = "\n".join(out)
    print(text, end="\n", flush=True)


def _render_detail(label, status, msg, actions, sel, first=False):
    if first:
        print("\033[s", end="", flush=True)
    else:
        print("\033[u\033[J", end="", flush=True)

    out = []
    out.append(f"  {_icon(status)}  {gray_desc(msg)}")
    out.append("")

    for i, (action_label, _) in enumerate(actions):
        arrow = lavender("❯") if i == sel else " "
        lbl   = lavender(action_label, bold=True) if i == sel else white_b(action_label)
        out.append(f"  {arrow} {lbl}")

    out.append("")
    out.append(f"  {gray_desc('↑↓ navigate  ·  Enter to select  ·  Esc to go back')}")

    text = "\n".join(out)
    print(text, end="\n", flush=True)


def _warn_screen(lines, confirm_label="Yes, proceed", cancel_label="Cancel"):
    """Show a warning and return True if user confirms, False if cancelled."""
    width = _term_width() - 2
    sel = 1  # default to Cancel
    choices = [(confirm_label, True), (cancel_label, False)]
    def render(first=False):
        if first:
            print("\033[s", end="", flush=True)
        else:
            print("\033[u\033[J", end="", flush=True)
        out = []
        out.append(f"  {red('⚠')}  {bold('Warning')}")
        out.append(f"  {gray_desc('─' * (width - 2))}")
        out.append("")
        for line in lines:
            out.append(f"  {line}")
        out.append("")
        for i, (label, _) in enumerate(choices):
            if i == sel:
                out.append(f"  {lavender('❯', bold=True)} {lavender(label, bold=True)}")
            else:
                out.append(f"    {white_b(label)}")
        out.append("")
        out.append(f"  {gray_desc('↑↓ navigate  ·  Enter to confirm  ·  Esc to cancel')}")
        text = "\n".join(out)
        print(text, end="\n", flush=True)

    print("\033[?25l", end="", flush=True)
    try:
        render(first=True)
        with Raw():
            while True:
                k = read_key()
                if k in ("up", "shift_tab"):
                    sel = (sel - 1) % len(choices)
                elif k in ("down", "tab"):
                    sel = (sel + 1) % len(choices)
                elif k == "enter":
                    return choices[sel][1]
                elif k in ("esc", "ctrl_c"):
                    return False
                render()
    finally:
        print("\033[?25h", end="", flush=True)


def _run_with_output(conf_key, conf, storage_root, action_verb="Installing"):
    """Back up, stop old services, run scripts, regenerate. Prints progress."""


    print(f"\n  → Backing up existing data...")
    archive = _backup(storage_root, conf_key.replace("new:", "old:"))
    if archive:
        print(f"    {green('✓')} Saved to {archive}")
    else:
        print(f"    {gray_desc('(no data to back up)')}")

    print(f"  → Stopping old services...")
    _stop(conf_key.replace("new:", "old:"))

    print(f"  → {action_verb}...")
    ok = _run_scripts(conf_key, conf)
    if not ok:
        print(f"\n  {red('✗')} Script failed - check output above.")
        print(f"  {gray_desc('Run sudo setup/start.sh to restore a known-good state.')}\n")
        return False

    print(f"  → Regenerating nginx + DNS...")
    regen_ok = _regenerate(conf)
    if not regen_ok:
        print(f"    {gray_desc('Management daemon unreachable - run sudo setup/start.sh')}")

    print(f"\n  {green('✓')} {bold('Done.')}\n")
    return True

# ── Action builders ────────────────────────────────────────────────────────────

def _actions_for(key, label, status, msg, conf):
    """Return list of (action_label, handler) for a service."""


    storage_root = conf.get("STORAGE_ROOT", "/home/user-data")
    actions = []

    # Recheck is always available
    def recheck():
        pass  # sentinel - handled in run_detail loop
    actions.append(("Recheck status", "recheck"))

    if key == "mail":
        def reinstall_mail():
            clear()
            print("\n  Reinstalling mail services...\n")
            for script in ["setup/mail/postfix.sh", "setup/mail/dovecot.sh"]:
                subprocess.run(
                    ["bash", "-c", f"set -e; source setup/functions.sh; source {BARE_METAL_CONF}; source {script}"],
                    cwd=PROJECT_ROOT,
                )
            _press_enter_to_return()
        actions.append(("Reinstall / repair", reinstall_mail))

    elif key == "spam":
        current = conf.get("SPAM_FILTER", "rspamd")
        other   = "spamassassin" if current == "rspamd" else "rspamd"
        other_label = "SpamAssassin" if other == "spamassassin" else "Rspamd"

        def switch_spam():
            clear()
            confirmed = _warn_screen([
                f"Switching from {current} to {other_label}.",
                "",
                "Spam learning history (Bayes database) will be backed up",
                "but the new filter starts fresh with no trained data.",
                "",
                f"Backup location: {storage_root}/backups/doctor/",
            ], confirm_label=f"Switch to {other_label}", cancel_label="Cancel")
            if not confirmed:
                return
            clear()
            _write_conf_key("SPAM_FILTER", other)
            conf["SPAM_FILTER"] = other
            _run_with_output(f"SPAM_FILTER:{other}", conf, storage_root, f"Installing {other_label}")
            _press_enter_to_return()
        actions.append((f"Switch to {other_label}", switch_spam))

        def reinstall_spam():
            clear()
            print(f"\n  Reinstalling {current}...\n")
            _run_scripts(f"SPAM_FILTER:{current}", conf)
            _press_enter_to_return()
        actions.append(("Reinstall / repair", reinstall_spam))

    elif key == "webmail":
        current = conf.get("WEBMAIL_CLIENT", "oxi")
        _CLIENTS = [
            ("oxi.email",   "oxi"),
            ("Roundcube",   "roundcube"),
            ("SnappyMail",  "snappymail"),
            ("Cypht",       "cypht"),
            ("None",        "none"),
        ]
        current_label = next((l for l, v in _CLIENTS if v == current), current)

        def switch_webmail():
            from .questions import step_webmail
            clear()

            class _FakeArgs: pass
            new_client = step_webmail(_FakeArgs(), dict(conf))
            if not new_client or new_client == current:
                return
            new_label = next((l for l, v in _CLIENTS if v == new_client), new_client)

            clear()
            warn_lines = [
                f"Switching webmail from {current_label} to {new_label}.",
                "",
            ]
            backup_paths = _BACKUP_PATHS.get(f"WEBMAIL_CLIENT:{current}", [])
            if backup_paths:
                warn_lines += [
                    "The following will be backed up but NOT migrated:",
                ]
                for p in backup_paths:
                    warn_lines.append(f"  · {storage_root}/{p}")
                warn_lines += [
                    "",
                    "Contacts synced via Radicale (CardDAV) are unaffected.",
                ]
            confirmed = _warn_screen(warn_lines,
                                     confirm_label=f"Switch to {new_label}",
                                     cancel_label="Cancel")
            if not confirmed:
                return
            clear()
            _backup(storage_root, f"WEBMAIL_CLIENT:{current}")
            _stop(f"WEBMAIL_CLIENT:{current}")
            _write_conf_key("WEBMAIL_CLIENT", new_client)
            conf["WEBMAIL_CLIENT"] = new_client
            _run_with_output(f"WEBMAIL_CLIENT:{new_client}", conf, storage_root, f"Installing {new_label}")
            _press_enter_to_return()
        actions.append(("Switch to a different client", switch_webmail))

        if status != OFF:
            def reinstall_webmail():
                clear()
                print(f"\n  Reinstalling {current_label}...\n")
                _run_scripts(f"WEBMAIL_CLIENT:{current}", conf)
                _regenerate(conf)
                _press_enter_to_return()
            actions.append(("Reinstall / repair", reinstall_webmail))

    elif key in ("radicale", "filebrowser", "clamav"):
        conf_key_map = {
            "radicale":    "ENABLE_RADICALE",
            "filebrowser": "ENABLE_FILEBROWSER",
            "clamav":      "ENABLE_CLAMAV",
        }
        ck = conf_key_map[key]
        enabled = conf.get(ck, "false") == "true"

        if key == "radicale" and "226/NAMESPACE" in msg:
            def fix_namespace():
                clear()
                dropin_dir = "/etc/systemd/system/radicale.service.d"
                dropin = os.path.join(dropin_dir, "no-namespace.conf")
                os.makedirs(dropin_dir, exist_ok=True)
                with open(dropin, "w") as f:
                    f.write("[Service]\nPrivateTmp=false\nProtectSystem=false\nBindPaths=\nReadWritePaths=\n")
                subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                subprocess.run(["systemctl", "restart", "radicale"], capture_output=True)
                print(f"\n  {green('✓')} Drop-in written, Radicale restarted.\n")
                _press_enter_to_return()
            actions.append(("Fix sandbox (no namespace support)", fix_namespace))

        if enabled:
            def reinstall_svc(k=key, ck=ck):
                clear()
                print(f"\n  Reinstalling {label}...\n")
                _run_scripts(f"{ck}:true", conf)
                _regenerate(conf)
                _press_enter_to_return()
            actions.append(("Reinstall / repair", reinstall_svc))

            def disable_svc(k=key, ck=ck):
                clear()
                backup_paths = _BACKUP_PATHS.get(f"{ck}:true", [])
                warn_lines = [f"Disable {label}?", ""]
                if backup_paths:
                    warn_lines += ["Data will be backed up and kept on disk:"]
                    for p in backup_paths:
                        warn_lines.append(f"  · {storage_root}/{p}")
                else:
                    warn_lines.append("No data will be lost.")
                confirmed = _warn_screen(warn_lines,
                                         confirm_label=f"Disable {label}",
                                         cancel_label="Cancel")
                if not confirmed:
                    return
                _backup(storage_root, f"{ck}:true")
                _stop(f"{ck}:true")
                _write_conf_key(ck, "false")
                conf[ck] = "false"
                _regenerate(conf)

                print(f"\n  {green('✓')} {label} disabled.\n")
                _press_enter_to_return()
            actions.append((f"Disable {label}", disable_svc))
        else:
            def enable_svc(k=key, ck=ck):
                clear()
                print(f"\n  Installing {label}...\n")
                _write_conf_key(ck, "true")
                conf[ck] = "true"
                _run_scripts(f"{ck}:true", conf)
                _regenerate(conf)
                _press_enter_to_return()
            actions.append((f"Enable {label}", enable_svc))

    elif key in ("dns", "certs"):
        script_map = {
            "dns":   "setup/infra/dns.sh",
            "certs": "setup/infra/ssl.sh",
        }
        def reinstall_infra(s=script_map[key]):
            clear()
            print(f"\n  Reinstalling {label}...\n")
            subprocess.run(
                ["bash", "-c", f"set -e; source setup/functions.sh; source {BARE_METAL_CONF}; source {s}"],
                cwd=PROJECT_ROOT,
            )
            _press_enter_to_return()
        actions.append(("Reinstall / repair", reinstall_infra))

    return actions

# ── Detail loop ────────────────────────────────────────────────────────────────

def run_detail(key, label, conf, results):


    status, msg = results.get(key, (OFF, "unknown"))
    actions = _actions_for(key, label, status, msg, conf)
    sel = 0

    print("\033[?25l", end="", flush=True)
    try:
        print(f"\n  {bold(label)}")
        print(f"  {gray_desc('─' * (_term_width() - 4))}")
        print()
        _render_detail(label, status, msg, actions, sel, first=True)
        with Raw():
            while True:
                k = read_key()
                if k in ("up", "shift_tab"):
                    sel = (sel - 1) % len(actions)
                elif k in ("down", "tab"):
                    sel = (sel + 1) % len(actions)
                elif k == "enter":
                    action_label, handler = actions[sel]
                    if handler == "recheck":

                        service_check = next(fn for sk, sl, fn in SERVICES if sk == key)
                        new_status, new_msg = service_check(conf)
                        results[key] = (new_status, new_msg)
                        status, msg = new_status, new_msg
                        actions = _actions_for(key, label, status, msg, conf)
                        sel = min(sel, len(actions) - 1)
                    else:
                        print("\033[?25h", end="", flush=True)
                        clear()
                        handler()
                        # Recheck after any action
                        service_check = next(fn for sk, sl, fn in SERVICES if sk == key)
                        results[key] = service_check(conf)
                        status, msg = results[key]
                        actions = _actions_for(key, label, status, msg, conf)
                        sel = 0
                        clear()
                        print("\033[?25l", end="", flush=True)
                        # Screen was cleared - reprint static header and reset save position
                        print(f"\n  {bold(label)}")
                        print(f"  {gray_desc('─' * (_term_width() - 4))}")
                        print()
                        _render_detail(label, status, msg, actions, sel, first=True)
                        continue
                elif k in ("esc", "ctrl_c"):
                    return
                _render_detail(label, status, msg, actions, sel)
    finally:
        print("\033[?25h", end="", flush=True)

# ── Main list loop ─────────────────────────────────────────────────────────────

def _is_docker():
    return (
        os.path.exists("/.dockerenv")
        or os.path.exists("/run/supervisor.sock")
        or os.environ.get("RUNTIME") == "docker"
    )

def _load_conf():
    conf = {}
    try:
        with open(BARE_METAL_CONF) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return conf


def _run_check(conf):
    """Non-interactive check mode: print status table and exit."""
    label_w = max(len(label) for _, label, _ in SERVICES) + 2
    results = {}
    for key, label, check_fn in SERVICES:
        results[key] = check_fn(conf)

    for key, label, _ in SERVICES:
        status, msg = results[key]
        pad = " " * (label_w - len(label))
        print(f"  {_icon(status)}  {label}{pad}{msg}")

    degraded = any(s in (WARN, ERR) for s, _ in results.values())
    sys.exit(1 if degraded else 0)


def run(check=False):


    conf = _load_conf()

    if check:
        if not conf:
            print("  error: no /etc/mailinabox.conf found")
            sys.exit(2)
        _run_check(conf)
        return

    clear()

    if _is_docker():
        print(f"\n  {red('boxctl doctor does not run inside Docker.')}")
        print(f"  {gray_desc('Edit deploy/docker/.env and re-run docker compose to reconfigure.')}\n")
        sys.exit(1)

    if os.geteuid() != 0:
        print(f"\n  {red('doctor must be run as root.')}")
        print(f"  {gray_desc('Try: sudo python3 setup/boxctl doctor')}\n")
        sys.exit(1)

    if not conf:
        print(f"\n  {red('No /etc/mailinabox.conf found.')}")
        print(f"  {gray_desc('Run sudo setup/start.sh first.')}\n")
        sys.exit(1)

    # Run all checks
    print(f"\n  {bold('boxctl doctor')}  {gray_desc('scanning...')}", flush=True)
    results = {}
    for key, label, check_fn in SERVICES:
        results[key] = check_fn(conf)

    sel = 0

    print("\033[?25l", end="", flush=True)
    try:
        clear()
        print(f"\n  {bold('boxctl doctor')}")
        print(f"  {gray_desc('─' * (_term_width() - 4))}")
        print()
        _render_list(SERVICES, results, sel, first=True)

        with Raw():
            while True:
                k = read_key()
                if k in ("up", "shift_tab"):
                    sel = (sel - 1) % len(SERVICES)
                elif k in ("down", "tab"):
                    sel = (sel + 1) % len(SERVICES)
                elif k == "enter":
                    key, label, check_fn = SERVICES[sel]
                    print("\033[?25h", end="", flush=True)
                    clear()
                    run_detail(key, label, conf, results)
                    clear()
                    print("\033[?25l", end="", flush=True)
                    # Screen was cleared - reprint static header and reset save position
                    print(f"\n  {bold('boxctl doctor')}")
                    print(f"  {gray_desc('─' * (_term_width() - 4))}")
                    print()
                    _render_list(SERVICES, results, sel, first=True)
                    continue
                elif k in ("esc", "ctrl_c"):
                    break
                _render_list(SERVICES, results, sel)
    finally:
        print("\033[?25h", end="", flush=True)
        clear()

    # Exit non-zero if anything is degraded
    degraded = any(s in (WARN, ERR) for s, _ in results.values())
    sys.exit(1 if degraded else 0)
