"""Terminal UI primitives - ANSI rendering, raw input, select/text components."""

import os, select, sys, termios

# ── ANSI helpers ──────────────────────────────────────────────────────────────

def _fg(r, g, b, s, bold=False):
    prefix = "\033[1;" if bold else "\033["
    return f"{prefix}38;2;{r};{g};{b}m{s}\033[0m"

def _bg_fg(bgr, bgg, bgb, fgr, fgg, fgb, s, bold=False):
    prefix = "\033[1;" if bold else "\033["
    return f"{prefix}38;2;{fgr};{fgg};{fgb}m\033[48;2;{bgr};{bgg};{bgb}m{s}\033[0m"

def lavender(s, bold=False):  return _fg(0xa6, 0xaf, 0xf3, s, bold)
def white_b(s):               return _fg(0xff, 0xff, 0xff, s, bold=True)
def gray_num(s):              return _fg(0x67, 0x69, 0x72, s)
def gray_desc(s):             return _fg(0x98, 0x9b, 0xa1, s)
def gray_nav(s):              return _fg(0x67, 0x69, 0x72, s)
def green(s):                 return _fg(0x5f, 0xff, 0x87, s)
def red(s):                   return _fg(0xff, 0x55, 0x55, s)
def bold(s):                  return f"\033[1m{s}\033[0m"

def nav_active(label):
    return _bg_fg(0xa6, 0xaf, 0xf3, 0x0d, 0x0e, 0x11, f" □ {label} ", bold=True)

LINE = "─" * 56

HINT_SEL  = "Enter to select  ·  ↑↓/Tab to navigate  ·  Esc to go back"
HINT_EDIT = "Enter to confirm  ·  ←→ to move cursor  ·  Esc to cancel"
HINT_TEXT = "Enter to confirm  ·  ←→ to move cursor  ·  Esc to go back"

# ── Terminal raw mode ─────────────────────────────────────────────────────────

class Raw:
    def __enter__(self):
        self.fd  = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        mode = termios.tcgetattr(self.fd)
        mode[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK |
                     termios.ISTRIP | termios.IXON)
        mode[2] &= ~(termios.CSIZE | termios.PARENB)
        mode[2] |=  termios.CS8
        mode[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
        mode[6][termios.VMIN]  = 1
        mode[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSADRAIN, mode)
        return self

    def __exit__(self, *_):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def read_key():
    """Read one logical keypress, accumulating CSI sequences with a 50ms timeout."""
    fd = sys.stdin.fileno()

    def _rb():
        try:
            return os.read(fd, 1)
        except OSError:
            return b'\x03'

    b = _rb()

    if b != b'\x1b':
        if b in (b'\r', b'\n'): return 'enter'
        if b == b'\x03':        return 'ctrl_c'
        if b == b'\t':          return 'tab'
        if b == b'\x7f':        return 'backspace'
        if b == b'\x01':        return 'home'
        if b == b'\x05':        return 'end'
        return b.decode('utf-8', errors='replace')

    if not select.select([fd], [], [], 0.05)[0]:
        return 'esc'

    b2 = _rb()
    if b2 != b'[':
        return 'esc'

    seq = b''
    while True:
        if not select.select([fd], [], [], 0.05)[0]:
            break
        ch = _rb()
        seq += ch
        if 0x40 <= ch[0] <= 0x7E:
            break

    if seq == b'A': return 'up'
    if seq == b'B': return 'down'
    if seq == b'C': return 'right'
    if seq == b'D': return 'left'
    if seq == b'Z': return 'shift_tab'
    return ''

# ── Layout ────────────────────────────────────────────────────────────────────

def clear():
    print("\033[H\033[J", end="", flush=True)


def nav(labels, current, done):
    parts = []
    for i, label in enumerate(labels):
        if i in done:
            parts.append(green(f"{label} ✓"))
        elif i == current:
            parts.append(nav_active(label))
        else:
            parts.append(gray_nav(f"□ {label}"))
    print(f"\n  ←  {'  '.join(parts)}  →")
    print(f"  {LINE}")

# ── Select component ──────────────────────────────────────────────────────────

def select_prompt(question, subtitle, options, current_value, revisit=False, validate_fn=None):
    """
    options: list of (label, description, value)
    Returns selected value, or None on Esc.
    '__custom__' option activates an inline text editor.
    """
    preset_values = {v for _, _, v in options if v != "__custom__"}
    custom_idx    = next((i for i, (_, _, v) in enumerate(options) if v == "__custom__"), None)

    idx = 0
    for i, (_, _, v) in enumerate(options):
        if v == current_value:
            idx = i
            break
    if current_value and current_value not in preset_values and custom_idx is not None:
        idx = custom_idx

    editing  = False
    edit_buf = list(current_value) if (current_value and current_value not in preset_values) else []
    edit_pos = len(edit_buf)
    err      = ""
    lines_drawn = [0]

    def render(first=False):
        if not first:
            print(f"\033[{lines_drawn[0]}A\033[J", end="")

        out = []
        out.append(f"  {bold(question)}")
        out.append(f"  {gray_desc(subtitle)}" if subtitle else "")
        out.append("")

        for i, (label, desc, value) in enumerate(options):
            is_custom = value == "__custom__"
            selected  = i == idx
            num_s     = gray_num(f"{i + 1}.")
            arrow     = lavender("❯") if selected else " "

            if revisit and not is_custom:
                is_prior   = value == current_value
                chk_prefix = (lavender("[✓]") if is_prior else gray_desc("[ ]")) + " "
            else:
                chk_prefix = ""

            if selected and editing and is_custom:
                s      = "".join(edit_buf)
                before = s[:edit_pos]
                at     = s[edit_pos:edit_pos + 1] or " "
                after  = s[edit_pos + 1:]
                lbl    = f"{white_b(before)}\033[7m{at}\033[27m{white_b(after)}"
            elif is_custom and edit_buf:
                prefix = lavender("✎  ")
                val    = lavender("".join(edit_buf), bold=True) if selected else white_b("".join(edit_buf))
                lbl    = f"{prefix}{val}"
            elif selected:
                lbl = lavender(label, bold=True)
            else:
                lbl = white_b(label)

            out.append(f"  {arrow} {num_s} {chk_prefix}{lbl}")
            if is_custom and err:
                out.append(f"       {red('✗')} {gray_desc(err)}")
            elif desc:
                out.append(f"       {gray_desc(desc)}")

        out.append("")
        out.append(f"  {gray_desc(HINT_EDIT if editing else HINT_SEL)}")

        text = "\n".join(out)
        print(text, end="\n", flush=True)
        lines_drawn[0] = text.count("\n") + 1

    print("\033[?25l", end="", flush=True)
    try:
        render(first=True)
        n_opts = len(options)
        with Raw():
            while True:
                k = read_key()

                if editing:
                    if k == 'enter':
                        value = "".join(edit_buf).strip()
                        if value:
                            if validate_fn:
                                msg = validate_fn(value)
                                if msg is not True:
                                    err = msg
                                else:
                                    return value
                            else:
                                return value
                        else:
                            editing = False
                            err     = ""
                    elif k == 'esc':
                        editing  = False
                        err      = ""
                        edit_buf = list(current_value) if (current_value and current_value not in preset_values) else []
                        edit_pos = len(edit_buf)
                    elif k == 'ctrl_c':
                        raise KeyboardInterrupt
                    elif k == 'backspace' and edit_pos > 0:
                        del edit_buf[edit_pos - 1]
                        edit_pos -= 1
                        err = ""
                    elif k == 'left'  and edit_pos > 0:
                        edit_pos -= 1
                    elif k == 'right' and edit_pos < len(edit_buf):
                        edit_pos += 1
                    elif k == 'home':
                        edit_pos = 0
                    elif k == 'end':
                        edit_pos = len(edit_buf)
                    elif isinstance(k, str) and len(k) == 1 and k.isprintable():
                        edit_buf.insert(edit_pos, k)
                        edit_pos += 1
                        err = ""
                else:
                    if k in ('up', 'shift_tab'):
                        idx = (idx - 1) % n_opts
                    elif k in ('down', 'tab'):
                        idx = (idx + 1) % n_opts
                    elif k == 'enter':
                        if options[idx][2] == '__custom__':
                            editing  = True
                            edit_pos = len(edit_buf)
                        else:
                            return options[idx][2]
                    elif k == 'esc':
                        return None
                    elif k == 'ctrl_c':
                        raise KeyboardInterrupt
                    elif k.isdigit() and 1 <= int(k) <= n_opts:
                        target = int(k) - 1
                        if options[target][2] == '__custom__':
                            idx      = target
                            editing  = True
                            edit_pos = len(edit_buf)
                        else:
                            return options[target][2]

                render()
    finally:
        print("\033[?25h", end="", flush=True)

# ── Text input component ──────────────────────────────────────────────────────

def text_prompt(question, subtitle, default="", validate_fn=None):
    """Raw-mode line editor with cursor movement. Returns stripped string, or None on Esc."""
    buf         = list(default)
    pos         = len(buf)
    err         = ""
    lines_drawn = [0]

    def render(first=False):
        if not first:
            print(f"\033[{lines_drawn[0]}A\033[J", end="")

        s      = "".join(buf)
        before = s[:pos]
        at     = s[pos:pos + 1] or " "
        after  = s[pos + 1:]
        out = [
            f"  {gray_desc(subtitle)}" if subtitle else "",
            "",
            f"  {lavender('❯')} {before}\033[7m{at}\033[27m{after}",
            f"  {red('✗')} {gray_desc(err)}" if err else "",
            "",
            f"  {gray_desc(HINT_TEXT)}",
        ]
        text = "\n".join(out)
        print(text, flush=True)
        lines_drawn[0] = text.count("\n") + 1

    print(f"  {bold(question)}")
    print("\033[?25l", end="", flush=True)

    try:
        render(first=True)
        with Raw():
            while True:
                k = read_key()
                if k == 'enter':
                    value = "".join(buf).strip() or default
                    if validate_fn:
                        result = validate_fn(value)
                        if result is not True:
                            err = result
                            render()
                            continue
                    err = ""
                    return value
                elif k == 'esc':
                    return None
                elif k == 'ctrl_c':
                    raise KeyboardInterrupt
                elif k == 'backspace' and pos > 0:
                    del buf[pos - 1]
                    pos -= 1
                    err = ""
                elif k == 'left' and pos > 0:
                    pos -= 1
                elif k == 'right' and pos < len(buf):
                    pos += 1
                elif k == 'home':
                    pos = 0
                elif k == 'end':
                    pos = len(buf)
                elif isinstance(k, str) and len(k) == 1 and k.isprintable():
                    buf.insert(pos, k)
                    pos += 1
                    err = ""
                render()
    finally:
        print("\033[?25h\n", end="", flush=True)
