"""Entry point: python3 setup/wizard [docker|questions|firstuser]"""

import argparse, os, signal, sys, termios

# When run as `python3 setup/wizard`, __package__ is '' and relative imports fail.
# Add the setup/ directory to sys.path so `import wizard` works as an absolute import.
if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from wizard.questions import STEPS, VALUE_DISPLAY
    from wizard.runner import run_questions, run_firstuser, write_output, load_conf
    from wizard.ui import select_prompt, clear, bold, gray_desc
else:
    from .questions import STEPS, VALUE_DISPLAY
    from .runner import run_questions, run_firstuser, write_output, load_conf
    from .ui import select_prompt, clear, bold, gray_desc

BARE_METAL_CONF = "/etc/mailinabox.conf"
DOCKER_ENV_DEFAULT = "deploy/docker/.env"


def _landing():
    """Interactive landing screen shown when no subcommand is given."""
    clear()
    options = [
        ("Docker",     "Configure a Docker Compose deployment. Generates a .env file and compose command.", "docker"),
        ("Bare metal", "Install directly on an Ubuntu machine via the guided installer.",                   "baremetal"),
    ]
    return select_prompt(
        "How would you like to deploy MailFlow?",
        "Choose a deployment method. Run with a subcommand to skip this screen.",
        options, None, False,
    )


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
        description="MailFlow setup wizard. Run with no subcommand for an interactive menu.",
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
    pq.add_argument("--ask-radicale",     action="store_true", help="ask whether to install Radicale")
    pq.add_argument("--ask-webmail",      action="store_true", help="ask which webmail client to install")
    pq.add_argument("--ask-dns-mode",     action="store_true", help="ask how DNS is managed")

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

    args = p.parse_args()

    try:
        if args.command is None:
            mode = _landing()
            if mode is None:
                sys.exit(0)
            elif mode == "docker":
                if __package__ in (None, ''):
                    from wizard.docker import run as run_docker
                else:
                    from .docker import run as run_docker
                run_docker(DOCKER_ENV_DEFAULT)
            elif mode == "baremetal":
                clear()
                print(f"\n  {bold('Bare metal setup')}\n")
                print(f"  Run the installer on your Ubuntu machine:\n")
                print(f"    sudo setup/start.sh\n")
                print(f"  {gray_desc('The wizard runs automatically during installation.')}\n")
            return

        if args.command == "questions":
            active = [
                (key, label, fn)
                for flag, key, label, fn in STEPS
                if getattr(args, flag.replace("-", "_"), False)
            ]
            initial = load_conf(BARE_METAL_CONF)
            results = run_questions(active, args, VALUE_DISPLAY, initial=initial)
            write_output(args.output, results)

        elif args.command == "firstuser":
            results = run_firstuser(args)
            write_output(args.output, results)

        elif args.command == "docker":
            if __package__ in (None, ''):
                from wizard.docker import run as run_docker
            else:
                from .docker import run as run_docker
            run_docker(args.env)

    except KeyboardInterrupt:
        print("\n\n  Setup cancelled.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
