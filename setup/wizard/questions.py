"""Bare metal wizard steps and validators."""

import ipaddress
from .ui import select_prompt, text_prompt

# ── Validators ────────────────────────────────────────────────────────────────

def validate_email(addr):
    if not addr.strip():
        return "Email address cannot be empty."
    try:
        from email_validator import validate_email as _chk, EmailNotValidError
        _chk(addr.strip(), check_deliverability=False)
        return True
    except ImportError:
        return True  # validator not available; bare metal boot venv will have it
    except Exception as exc:
        return str(exc)


def validate_ipv4(addr):
    if not addr.strip():
        return "IPv4 address cannot be empty."
    try:
        ipaddress.IPv4Address(addr.strip())
        return True
    except ValueError:
        return "Enter a valid IPv4 address (e.g. 1.2.3.4)."


def validate_ipv6(addr):
    if not addr.strip():
        return "IPv6 address cannot be empty."
    try:
        ipaddress.IPv6Address(addr.strip())
        return True
    except ValueError:
        return "Enter a valid IPv6 address (e.g. 2001:db8::1)."


def validate_hostname(name):
    name = name.strip()
    if not name:
        return "Hostname cannot be empty."
    if len(name) > 253:
        return "Hostname is too long (max 253 characters)."
    labels = name.rstrip(".").split(".")
    if len(labels) < 2:
        return "Hostname must contain at least one dot (e.g. box.example.com)."
    for label in labels:
        if not label or len(label) > 63:
            return "Each hostname part must be 1-63 characters."
        if label.startswith("-") or label.endswith("-"):
            return "Hostname parts cannot start or end with a hyphen."
        if not all(c.isalnum() or c == "-" for c in label):
            return "Hostname parts may only contain letters, digits, and hyphens."
    return True

# ── Steps ─────────────────────────────────────────────────────────────────────

def step_email(args, answers):
    domain  = args.default_hostname[4:] if args.default_hostname.startswith("box.") else ""
    default = answers.get("EMAIL_ADDR") or (f"me@{domain}" if domain else "")
    return text_prompt(
        "What email address should this server manage?",
        "The domain part (after @) will be used to suggest a hostname.",
        default, validate_email,
    )


def step_hostname(args, answers):
    email     = answers.get("EMAIL_ADDR", "")
    suggested = f"box.{email.split('@')[-1]}" if email else (args.default_hostname or "")
    current   = answers.get("PRIMARY_HOSTNAME")
    options   = []
    if suggested:
        options.append((suggested, "Recommended - subdomain of your email domain.", suggested))
    options.append(("✎  Enter a custom hostname", "Type any valid fully-qualified hostname.", "__custom__"))
    return select_prompt(
        "Choose a hostname for your Mail-in-a-Box box.",
        "The hostname is your server's address on the internet (e.g. box.example.com).",
        options, current or suggested or None, current is not None,
        validate_fn=validate_hostname,
    )


def step_ipv4(args, answers):
    current = answers.get("PUBLIC_IP")
    options = []
    if args.guessed_ipv4:
        options.append((args.guessed_ipv4, "Auto-detected from the internet.", args.guessed_ipv4))
    if args.default_ipv4 and args.default_ipv4 != args.guessed_ipv4:
        options.append((args.default_ipv4, "Previously configured address.", args.default_ipv4))
    options.append(("✎  Enter a custom address", "Type an IPv4 address manually.", "__custom__"))
    return select_prompt(
        "What is the public IPv4 address of this server?",
        "This is the IP your hosting provider assigned to the server.",
        options, current, current is not None,
        validate_fn=validate_ipv4,
    )


def step_ipv6(args, answers):
    current = answers.get("PUBLIC_IPV6")
    options = [("No IPv6", "Most setups work fine with IPv4 only.", "")]
    if args.guessed_ipv6:
        options.append((args.guessed_ipv6, "Auto-detected from the internet.", args.guessed_ipv6))
    if args.default_ipv6 and args.default_ipv6 not in ("", args.guessed_ipv6):
        options.append((args.default_ipv6, "Previously configured address.", args.default_ipv6))
    options.append(("✎  Enter a custom address", "Type an IPv6 address manually.", "__custom__"))
    return select_prompt(
        "Does this server have a public IPv6 address?",
        "IPv6 is optional but recommended if your provider supports it.",
        options, current, current is not None,
        validate_fn=validate_ipv6,
    )


def step_filebrowser(args, answers):
    current = answers.get("ENABLE_FILEBROWSER")
    options = [
        ("Yes", "Install a web-based file manager at /files.", "true"),
        ("No",  "Skip - can be enabled later in /etc/mailinabox.conf.", "false"),
    ]
    return select_prompt(
        "Would you like to install FileBrowser?",
        "FileBrowser lets mail users browse and manage their files via the browser.",
        options, current or "true", current is not None,
    )


def step_radicale(args, answers):
    current = answers.get("ENABLE_RADICALE")
    options = [
        ("Yes", "Install a CalDAV/CardDAV server at /radicale.", "true"),
        ("No",  "Skip - can be enabled later in /etc/mailinabox.conf.", "false"),
    ]
    return select_prompt(
        "Would you like to install Radicale (CalDAV/CardDAV)?",
        "Radicale lets mail users sync calendars and contacts with their devices.",
        options, current or "true", current is not None,
    )


def step_webmail(args, answers):
    current = answers.get("WEBMAIL_CLIENT")
    options = [
        ("oxi.email",               "Modern webmail built with Rust + Bun. Fast and lightweight.", "oxi"),
        ("None (external clients)", "No webmail - use Thunderbird, Apple Mail, etc. directly.",    "none"),
    ]
    return select_prompt(
        "Which webmail client would you like to install?",
        "Webmail lets users access email from any browser. Choose none to skip.",
        options, current or "oxi", current is not None,
    )


def step_dns_mode(args, answers):
    current = answers.get("DNS_MODE")
    options = [
        ("Self-hosted DNS", "This box manages DNS for your domain (default behavior).", "self"),
        ("External DNS",    "You manage DNS via Cloudflare, Route53, etc. Box is mail-only.", "external"),
    ]
    return select_prompt(
        "How is DNS managed for your domain?",
        "Self-hosted lets this box serve DNS. External skips nameserver checks in status reports.",
        options, current or "self", current is not None,
    )


def step_backup_tool(args, answers):
    current = answers.get("BACKUP_TOOL")
    options = [
        ("restic",    "Faster, deduplicating backups. Recommended for new installs.", "restic"),
        ("duplicity", "The original backup tool. Still fully supported.", "duplicity"),
    ]
    return select_prompt(
        "Which backup tool should this box use?",
        "Switching later starts a brand-new, empty backup history under the new tool - "
        "existing backups are left in place but no longer managed. Nothing migrates automatically.",
        options, current or "restic", current is not None,
    )

# ── Step registry ─────────────────────────────────────────────────────────────

# Each entry: (argparse_flag, conf_key, nav_label, step_fn)
STEPS = [
    ("ask_email",       "EMAIL_ADDR",        "Email",       step_email),
    ("ask_hostname",    "PRIMARY_HOSTNAME",   "Hostname",    step_hostname),
    ("ask_ipv4",        "PUBLIC_IP",          "IPv4",        step_ipv4),
    ("ask_ipv6",        "PUBLIC_IPV6",        "IPv6",        step_ipv6),
    ("ask_filebrowser", "ENABLE_FILEBROWSER", "FileBrowser", step_filebrowser),
    ("ask_radicale",    "ENABLE_RADICALE",    "Radicale",    step_radicale),
    ("ask_webmail",     "WEBMAIL_CLIENT",     "Webmail",     step_webmail),
    ("ask_dns_mode",    "DNS_MODE",           "DNS",         step_dns_mode),
    ("ask_backup_tool", "BACKUP_TOOL",        "Backup",      step_backup_tool),
]

VALUE_DISPLAY = {
    "ENABLE_FILEBROWSER": {"true": "Yes", "false": "No"},
    "ENABLE_RADICALE":    {"true": "Yes", "false": "No"},
    "WEBMAIL_CLIENT":     {"oxi": "oxi.email", "none": "None (external clients)"},
    "DNS_MODE":           {"self": "Self-hosted", "external": "External"},
    "BACKUP_TOOL":        {"restic": "restic", "duplicity": "duplicity"},
}
