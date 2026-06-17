"""Entry point: python3 setup/boxctl [docker|questions|firstuser|doctor]"""

import argparse, os, signal, sys, termios

# When run as `python3 setup/boxctl`, __package__ is '' and relative imports fail.
# Add the setup/ directory to sys.path so `import boxctl` works as an absolute import.
if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from boxctl.questions import STEPS, VALUE_DISPLAY
    from boxctl.runner import run_questions, run_firstuser, write_output, load_conf
    from boxctl.ui import select_prompt, clear, bold, gray_desc, green, red, _term_width
else:
    from .questions import STEPS, VALUE_DISPLAY
    from .runner import run_questions, run_firstuser, write_output, load_conf
    from .ui import select_prompt, clear, bold, gray_desc, green, red, _term_width

BARE_METAL_CONF = "/etc/mailinabox.conf"
DOCKER_ENV_DEFAULT = "deploy/docker/.env"


def _landing():
    """Interactive landing screen shown when no subcommand is given."""
    clear()
    options = [
        ("Docker",           "Configure a Docker Compose deployment. Generates a .env file and compose command.", "docker"),
        ("Bare metal",       "Install directly on an Ubuntu machine via the guided installer.",                   "baremetal"),
        ("Manage services",  "Check service health and swap services on a running box.",                          "doctor"),
    ]
    return select_prompt(
        "What would you like to do?",
        "Run with a subcommand to skip this screen.",
        options, None, False,
    )


def _preflight():
    """Check RAM and disk space before starting setup. Prints warnings, returns False if critical."""
    import shutil

    OK, WARN, ERR = "ok", "warn", "err"
    checks = []

    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mb = int(line.split()[1]) // 1024
                    if mb < 256:
                        checks.append((ERR,  "RAM", f"{mb} MB available - 512 MB minimum required"))
                    elif mb < 512:
                        checks.append((WARN, "RAM", f"{mb} MB available - 512 MB recommended"))
                    else:
                        checks.append((OK,   "RAM", f"{mb} MB available"))
                    break
    except Exception:
        pass

    try:
        free_gb = shutil.disk_usage("/home").free // (1024 ** 3)
        if free_gb < 2:
            checks.append((ERR,  "Disk", f"{free_gb} GB free at /home - 5 GB recommended"))
        elif free_gb < 5:
            checks.append((WARN, "Disk", f"{free_gb} GB free at /home"))
        else:
            checks.append((OK,   "Disk", f"{free_gb} GB free at /home"))
    except Exception:
        pass

    if not checks:
        return True

    _ICON = {OK: f"\033[38;2;95;255;135m✓\033[0m", WARN: f"\033[38;2;255;215;0m!\033[0m", ERR: f"\033[38;2;255;85;85m✗\033[0m"}
    width  = _term_width() - 2
    label_w = max(len(label) for _, label, _ in checks) + 2
    any_err  = any(s == ERR  for s, _, _ in checks)
    any_warn = any(s == WARN for s, _, _ in checks)

    if any_err or any_warn:
        print(f"\n  {bold('Pre-flight checks')}")
        print(f"  {gray_desc('─' * (width - 2))}")
        for status, label, msg in checks:
            pad = " " * (label_w - len(label))
            print(f"  {_ICON[status]}  {label}{pad}{gray_desc(msg)}")
        print()

    if any_err:
        print(f"  {red('Setup cannot continue. Resolve the issues above first.')}\n")
        return False

    return True


def main():
    if not sys.stdin.isatty():
        sys.exit("Interactive terminal required")

    _saved = termios.tcgetattr(sys.stdin.fileno())

    def _on_sigterm(sig, frame):
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved)
        except Exception:
            pass
        print("\033[?25h", end="", flush=True)
        sys.exit(1)

    signal.signal(signal.SIGTERM, _on_sigterm)

    p = argparse.ArgumentParser(
        description="boxctl - Mail-in-a-Box management CLI. Run with no subcommand for an interactive menu.",
        epilog="Run without a subcommand to choose interactively.",
    )
    sub = p.add_subparsers(dest="command", required=False,
                           title="subcommands",
                           description="Pass one of the following, or omit to get the interactive menu.")

    # ── bare metal: questions ──────────────────────────────────────────────────
    pq = sub.add_parser("questions",
                        help="collect bare metal install answers (called by setup/questions.sh)")
    pq.add_argument("--output",           required=True,  help="file to write answers to")
    pq.add_argument("--default-hostname", default="",     help="suggested hostname")
    pq.add_argument("--guessed-ipv4",     default="",     help="auto-detected public IPv4")
    pq.add_argument("--default-ipv4",     default="",     help="previously configured IPv4")
    pq.add_argument("--guessed-ipv6",     default="",     help="auto-detected public IPv6")
    pq.add_argument("--default-ipv6",     default="",     help="previously configured IPv6")
    pq.add_argument("--ask-email",        action="store_true", help="ask for admin email address")
    pq.add_argument("--ask-hostname",     action="store_true", help="ask for server hostname")
    pq.add_argument("--ask-ipv4",         action="store_true", help="ask for public IPv4")
    pq.add_argument("--ask-ipv6",         action="store_true", help="ask for public IPv6")
    pq.add_argument("--ask-filebrowser",  action="store_true", help="ask whether to install FileBrowser")
    pq.add_argument("--ask-optionals",    action="store_true", help="ask which optional features to install (Radicale, ClamAV)")
    pq.add_argument("--ask-spam-filter",  action="store_true", help="ask which spam filter to use (rspamd or spamassassin)")
    pq.add_argument("--ask-webmail",      action="store_true", help="ask which webmail client to install")
    pq.add_argument("--ask-dns-mode",     action="store_true", help="ask how DNS is managed")
    pq.add_argument("--ask-backup-tool",  action="store_true", help="ask which backup tool to use (restic or duplicity)")
    pq.add_argument("--ask-timezone",     action="store_true", help="ask for the server timezone")

    # ── bare metal: firstuser ──────────────────────────────────────────────────
    pf = sub.add_parser("firstuser",
                        help="create the first admin mail account (called by setup/firstuser.sh)")
    pf.add_argument("--output",           required=True, help="file to write answers to")
    pf.add_argument("--default-hostname", default="",   help="used to suggest a default email address")

    # ── docker wizard ──────────────────────────────────────────────────────────
    pd = sub.add_parser("docker",
                        help="interactive Docker Compose setup - writes .env and prints the compose command")
    pd.add_argument("--env", default="deploy/docker/.env",
                    help="path to write the Docker .env file (default: deploy/docker/.env)")

    # ── doctor ─────────────────────────────────────────────────────────────────
    pd2 = sub.add_parser("doctor",
                         help="check service health and swap services on a running box")
    pd2.add_argument("--check", action="store_true",
                     help="non-interactive: print service status and exit (non-zero if any degraded)")

    args = p.parse_args()

    try:
        if args.command is None:
            mode = _landing()
            if mode is None:
                sys.exit(0)
            elif mode == "docker":
                if __package__ in (None, ''):
                    from boxctl.docker import run as run_docker
                else:
                    from .docker import run as run_docker
                run_docker(DOCKER_ENV_DEFAULT)
            elif mode == "baremetal":
                clear()
                print(f"\n  {bold('Bare metal setup')}\n")
                print(f"  Run the installer on your Ubuntu machine:\n")
                print(f"    sudo setup/start.sh\n")
                print(f"  {gray_desc('boxctl runs automatically during installation.')}\n")
            elif mode == "doctor":
                if __package__ in (None, ''):
                    from boxctl.doctor import run as run_doctor
                else:
                    from .doctor import run as run_doctor
                run_doctor()
            return

        if args.command == "questions":
            if not _preflight():
                sys.exit(1)
            active = [
                (key, label, fn)
                for flag, key, label, fn in STEPS
                if getattr(args, flag.replace("-", "_"), False)
            ]
            all_steps = [(key, label, fn) for _, key, label, fn in STEPS]
            initial = load_conf(BARE_METAL_CONF)
            results = run_questions(active, args, VALUE_DISPLAY, initial=initial, all_steps=all_steps)
            write_output(args.output, results)

        elif args.command == "firstuser":
            conf = load_conf(BARE_METAL_CONF)
            args.existing_email = conf.get("EMAIL_ADDR", "")
            results = run_firstuser(args)
            write_output(args.output, results)

        elif args.command == "docker":
            if __package__ in (None, ''):
                from boxctl.docker import run as run_docker
            else:
                from .docker import run as run_docker
            run_docker(args.env)

        elif args.command == "doctor":
            if __package__ in (None, ''):
                from boxctl.doctor import run as run_doctor
            else:
                from .doctor import run as run_doctor
            run_doctor(check=getattr(args, "check", False))

    except KeyboardInterrupt:
        print("\n\n  Setup cancelled.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
