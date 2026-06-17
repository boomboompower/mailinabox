"""Shared wizard orchestration - step runner, confirm screen, first-user flow."""

import os, sys
from .ui import (
    bold, lavender, white_b, gray_num, gray_desc, green, red,
    LINE, clear, nav,
)


def confirm_screen(active, answers, value_display=None):
    """
    Summary screen showing all collected answers with Confirm / Go back options.

    active:        list of (key, label, fn)
    value_display: optional dict mapping key -> {raw_value -> display_value}

    Returns True to proceed, None to go back.
    """
    from .ui import read_key, Raw

    rows = []
    for key, label, _ in active:
        val = answers.get(key, "")
        if value_display:
            val = value_display.get(key, {}).get(val, val)
        rows.append((label, val))

    choices = [
        ("Confirm and continue", True),
        ("Go back and make changes", None),
    ]
    sel         = 0
    lines_drawn = [0]
    col_w       = max(len(r[0]) for r in rows) + 2

    def render(first=False):
        if not first:
            print(f"\033[{lines_drawn[0]}A\033[J", end="")

        out = []
        out.append(f"  {bold('Review your configuration')}")
        out.append(f"  {gray_desc('Everything look right? Confirm to continue.')}")
        out.append("")

        for label, val in rows:
            pad     = " " * (col_w - len(label) - 1)
            display = white_b(val) if val else gray_desc("(none)")
            out.append(f"    {gray_desc(label + ':')}{pad}{display}")

        out.append("")

        for i, (label, _) in enumerate(choices):
            selected = i == sel
            arrow    = lavender("❯") if selected else " "
            lbl      = lavender(label, bold=True) if selected else white_b(label)
            out.append(f"  {arrow} {gray_num(str(i + 1) + '.')} {lbl}")

        out.append("")
        out.append(f"  {gray_desc('Enter to confirm  ·  ↑↓ to navigate  ·  Esc to go back')}")

        text = "\n".join(out)
        print(text, end="\n", flush=True)
        lines_drawn[0] = text.count("\n") + 1

    print("\033[?25l", end="", flush=True)
    try:
        render(first=True)
        with Raw():
            while True:
                k = read_key()
                if k in ('up', 'shift_tab'):
                    sel = (sel - 1) % len(choices)
                elif k in ('down', 'tab'):
                    sel = (sel + 1) % len(choices)
                elif k == 'enter':
                    return choices[sel][1]
                elif k == 'esc':
                    return None
                elif k == 'ctrl_c':
                    raise KeyboardInterrupt
                elif k == '1':
                    return True
                elif k == '2':
                    return None
                render()
    finally:
        print("\033[?25h", end="", flush=True)


def run_questions(steps, args, value_display=None, initial=None):
    """
    Run a wizard flow over a list of steps.

    steps:         list of (key, label, fn) - already filtered/selected by the caller
    args:          passed through to each step function
    value_display: optional dict for confirm_screen display formatting
    initial:       optional dict of pre-populated answers (e.g. loaded from .env)

    Returns dict of answers, or exits on cancellation.
    """
    if not steps:
        return {}

    labels  = [label for _, label, _ in steps] + ["Confirm"]
    answers = dict(initial) if initial else {}
    done    = set()
    idx     = 0

    while idx <= len(steps):
        clear()
        nav(labels, idx, done)
        print()

        if idx == len(steps):
            try:
                result = confirm_screen(steps, answers, value_display)
            except KeyboardInterrupt:
                clear()
                print("\n  Setup cancelled.\n")
                sys.exit(1)
            if result is True:
                break
            idx -= 1
        else:
            key, label, fn = steps[idx]
            try:
                result = fn(args, answers)
            except KeyboardInterrupt:
                clear()
                print("\n  Setup cancelled.\n")
                sys.exit(1)

            if result is None:
                if idx == 0:
                    clear()
                    print("\n  Setup cancelled.\n")
                    sys.exit(1)
                done.discard(idx)
                idx -= 1
            else:
                answers[key] = result
                done.add(idx)
                idx += 1

    clear()
    return answers


def run_firstuser(args):
    """Standalone first-user creation prompt (bare metal post-install)."""
    from .ui import text_prompt

    clear()
    print(f"\n  {bold('MailFlow - First Mail Account')}")
    print(f"  {LINE}")

    from .questions import validate_email

    try:
        email = text_prompt(
            "What email address should the admin account use?",
            "This creates your first mail account and gives it admin access to the control panel.",
            f"me@{args.default_hostname}" if args.default_hostname else "",
            validate_email,
        )
    except KeyboardInterrupt:
        email = None

    if email is None:
        clear()
        print("\n  Setup cancelled.\n")
        sys.exit(1)

    print(f"  {LINE}\n")
    return {"EMAIL_ADDR": email}


def write_output(path, results):
    """Write shell-sourceable key=value pairs (bare metal wizard output)."""
    def q(v): return "'" + v.replace("'", "'\\''") + "'"
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for k, v in results.items():
            f.write(f"{k}={q(v)}\n")
    os.replace(tmp, path)


def load_conf(path):
    """
    Parse a key=value config file into a dict.

    Handles both shell-quoted values (KEY='value' or KEY="value") written by
    write_output, and plain unquoted values (KEY=value) written by write_env.
    Skips comments and blank lines. Returns {} if the file does not exist.
    """
    values = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                # Strip matching outer quotes
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                values[k] = v
    except FileNotFoundError:
        pass
    return values
