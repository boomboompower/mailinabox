"""Shared wizard orchestration - step runner, confirm screen, first-user flow."""

import os, sys
from .ui import (
    bold, lavender, white_b, gray_num, gray_desc, green, red,
    clear, nav, _term_width,
)

def _line(): return "─" * (_term_width() - 2)


def confirm_screen(active, answers, value_display=None, all_steps=None):
    """
    Summary screen showing all collected answers.

    All rows are navigable - pressing Enter on a row jumps back to edit that
    specific step, then returns here. Esc goes back to the previous step.

    active:        list of (key, label, fn) - steps asked this run
    answers:       full answers dict including values loaded from existing conf
    all_steps:     full STEPS list; if provided, shows every step that has a value
    value_display: optional dict mapping key -> {raw_value -> display_value}

    Returns:
      True            - user confirmed, proceed
      None            - Esc pressed, go back one step
      ("edit", key)   - user wants to re-answer the step for this key
    """
    from .ui import read_key, Raw

    display_steps = all_steps if all_steps else active
    rows = []  # (key, label, display_val, is_active)
    active_keys = {key for key, _, _ in active}
    for key, label, *_ in display_steps:
        val = answers.get(key, "")
        if not val and key not in active_keys:
            continue
        if isinstance(val, dict):
            enabled = [k.replace("ENABLE_", "").title() for k, v in val.items() if v == "true"]
            val = ", ".join(enabled) if enabled else "None"
        elif value_display:
            val = value_display.get(key, {}).get(val, val)
        rows.append((key, label, val, key in active_keys))

    # Navigable items: each config row + the "Confirm" action at the bottom.
    n_items     = len(rows) + 1
    CONFIRM_IDX = len(rows)
    sel         = CONFIRM_IDX  # start cursor on Confirm
    col_w       = max((len(r[1]) for r in rows), default=10) + 2
    def render(first=False):
        if first:
            print("\033[s", end="", flush=True)
        else:
            print("\033[u\033[J", end="", flush=True)

        out = []
        out.append(f"  {bold('Review your configuration')}")
        out.append(f"  {gray_desc('Navigate to edit a value, or confirm to continue.')}")
        out.append("")

        for i, (key, label, val, is_active) in enumerate(rows):
            pad = " " * (col_w - len(label) - 1)
            if i == sel:
                out.append(f"  {lavender('❯')} {gray_desc(label + ':')}{pad}{lavender(val or '(none)', bold=True)}")
            else:
                display = white_b(val) if (val and is_active) else gray_desc(val or "(none)")
                out.append(f"    {gray_desc(label + ':')}{pad}{display}")

        out.append("")
        if sel == CONFIRM_IDX:
            out.append(f"  {lavender('❯')} {lavender('Confirm and continue', bold=True)}")
        else:
            out.append(f"    {white_b('Confirm and continue')}")

        out.append("")
        out.append(f"  {gray_desc('↑↓ navigate  ·  Enter to edit / confirm  ·  Esc to go back')}")

        text = "\n".join(out)
        print(text, end="\n", flush=True)

    print("\033[?25l", end="", flush=True)
    try:
        render(first=True)
        with Raw():
            while True:
                k = read_key()
                if k in ('up', 'shift_tab'):
                    sel = (sel - 1) % n_items
                elif k in ('down', 'tab'):
                    sel = (sel + 1) % n_items
                elif k == 'enter':
                    if sel == CONFIRM_IDX:
                        return True
                    key = rows[sel][0]
                    # Only allow editing steps that were asked this run.
                    if key in active_keys:
                        return ("edit", key)
                    # Pre-existing (gray) rows are display-only - ignore Enter.
                elif k == 'esc':
                    return None
                elif k == 'ctrl_c':
                    raise KeyboardInterrupt
                render()
    finally:
        print("\033[?25h", end="", flush=True)


def run_questions(steps, args, value_display=None, initial=None, all_steps=None):
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
                result = confirm_screen(steps, answers, value_display, all_steps=all_steps)
            except KeyboardInterrupt:
                clear()
                print("\n  Setup cancelled.\n")
                sys.exit(1)
            if result is True:
                break
            elif isinstance(result, tuple) and result[0] == "edit":
                # User picked a specific row to re-answer. Run just that step,
                # then return to confirm regardless of what they entered.
                edit_key = result[1]
                step_idx = next((i for i, (k, _, _) in enumerate(steps) if k == edit_key), None)
                if step_idx is not None:
                    _, _, fn = steps[step_idx]
                    clear()
                    nav(labels, step_idx, done)
                    print()
                    try:
                        step_result = fn(args, answers)
                    except KeyboardInterrupt:
                        step_result = None
                    if step_result is not None:
                        if isinstance(step_result, dict):
                            answers.update(step_result)
                        answers[edit_key] = step_result
                        done.add(step_idx)
                # idx stays at len(steps) - we return to confirm either way
            else:
                # Esc - go back to previous step
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
                if isinstance(result, dict):
                    # Multi-select: merge individual keys into answers, keep
                    # dict under step key so confirm_screen can display it.
                    answers.update(result)
                answers[key] = result
                done.add(idx)
                idx += 1

    clear()
    return answers


def run_firstuser(args):
    """Standalone first-user creation prompt (bare metal post-install)."""
    from .ui import text_prompt, password_prompt, clear, bold, gray_desc

    clear()
    print(f"\n  {bold('Mail-in-a-Box - First Mail Account')}")
    print(f"  {_line()}")

    from .questions import validate_email

    existing_email = getattr(args, 'existing_email', '') or ''
    default_email  = existing_email or (f"me@{args.default_hostname}" if args.default_hostname else "")

    try:
        email = text_prompt(
            "Confirm or change the admin email address:",
            "This account will have admin access to the control panel.",
            default_email,
            validate_email,
        )
    except KeyboardInterrupt:
        email = None

    if email is None:
        clear()
        print("\n  Setup cancelled.\n")
        sys.exit(1)

    # Collect password with confirmation. Esc on confirm goes back to re-enter password.
    while True:
        clear()
        print(f"\n  {bold('Mail-in-a-Box - First Mail Account')}")
        print(f"  {gray_desc(f'Account: {email}')}")
        print(f"  {_line()}")

        try:
            pw = password_prompt(
                "Choose a password for your account:",
                "Must be at least 8 characters.",
                validate_fn=lambda p: True if len(p) >= 8 else "Password must be at least 8 characters.",
            )
        except KeyboardInterrupt:
            pw = None

        if pw is None:
            clear()
            print("\n  Setup cancelled.\n")
            sys.exit(1)

        clear()
        print(f"\n  {bold('Mail-in-a-Box - First Mail Account')}")
        print(f"  {gray_desc(f'Account: {email}')}")
        print(f"  {_line()}")

        try:
            pw2 = password_prompt(
                "Confirm password:",
                validate_fn=lambda p: True if p == pw else "Passwords do not match.",
            )
        except KeyboardInterrupt:
            pw2 = None

        if pw2 is not None:
            break
        # Esc on confirm - redraw and re-enter password

    print(f"  {_line()}\n")
    return {"EMAIL_ADDR": email, "EMAIL_PW": pw}


def write_output(path, results):
    """Write shell-sourceable key=value pairs (bare metal wizard output)."""
    def q(v): return "'" + v.replace("'", "'\\''") + "'"
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for k, v in results.items():
            if k.startswith("__") or isinstance(v, dict):
                continue  # sentinel keys from multi-select steps; real values already merged
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
