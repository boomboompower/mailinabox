"""
Mail-in-a-Box installer - called by setup/install.sh.

Flow:
  1. Preflight (RAM / disk)
  2. Questions wizard  ->  writes /etc/mailinabox.conf
  3. System packages (apt-get, rolling log)
  4. Components (one doit run, rolling log with active-component tracking)
  5. dns_update + web_update
  6. boxctl bootstrap --install  (admin URL + TLS fingerprint)
"""

import os, re, shutil, signal, socket, subprocess, sys, termios, threading, time, urllib.request, ipaddress
from datetime import datetime

# ── sys.path: add setup/ so boxctl.* and components.* are importable ─────────

_HERE = os.path.dirname(os.path.abspath(__file__))  # setup/boxctl/
_SETUP = os.path.dirname(_HERE)  # setup/
_REPO = os.path.dirname(_SETUP)  # repo root

for _p in (_SETUP, _REPO):
	if _p not in sys.path:
		sys.path.insert(0, _p)

from boxctl.ui import (
	bold,
	gray_desc,
	white_b,
	green,
	red,
	clear,
	_term_width,
)
from boxctl.questions import STEPS, VALUE_DISPLAY, PROFILES
from boxctl.runner import run_questions, write_output, load_conf

CONF_PATH = "/etc/mailinabox.conf"
LOG_LINES = 10

# doit output prefix when a task actually ran:  ".  compname:taskname"
_TASK_RE = re.compile(r'^(?:\.  |-- )([a-z][a-z0-9_-]*):[a-z]')
# Strip ANSI escape sequences from subprocess output before displaying.
# apt and dpkg emit \033[K (erase-to-EOL), \033[Nm (colors) etc. which corrupt
# our cursor-based log panel if re-emitted inside it.
_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')

LOG_PATH = "/tmp/mailinabox-setup.log"
_logfile: "open | None" = None


def _log(line: str) -> None:
	"""Write a line to the log file. No-op until _open_log() is called."""
	if _logfile is not None:
		_logfile.write(line + "\n")
		_logfile.flush()


def _open_log() -> None:
	global _logfile
	# Rotate: preserve the previous run as .prev so failure context survives a re-run,
	# but truncate the current log so it never grows unboundedly.
	if os.path.exists(LOG_PATH):
		os.replace(LOG_PATH, LOG_PATH + ".prev")
	_logfile = open(LOG_PATH, "w")
	width = 72
	ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	_log("=" * width)
	_log("  Mail-in-a-Box - Setup Log")
	_log(f"  Started: {ts}")
	_log("=" * width)


# ── Rendering helpers ─────────────────────────────────────────────────────────


def _header(subtitle: str | None = None) -> None:
	clear()
	suffix = f"  {gray_desc('-')}  {gray_desc(subtitle)}" if subtitle else ""
	print(f"\n  {bold('Mail-in-a-Box')}{suffix}")
	print(f"  {gray_desc('─' * (_term_width() - 4))}")
	print()


def _redraw_log(buf: list[str], log_lines: int) -> None:
	"""Rewrite the reserved log panel in-place (same technique as doctor.py).

	All output is batched into a single write() call so the terminal never
	sees a partial update - important when output arrives at high speed.
	"""
	width = _term_width() - 6
	visible = buf[-log_lines:]
	parts = [f"\033[{log_lines}A"]
	for i in range(log_lines):
		line = visible[i][:width] if i < len(visible) else ""
		parts.append(f"  {gray_desc(line)}\033[K\n")
	sys.stdout.write("".join(parts))
	sys.stdout.flush()


# ── Phase runner ──────────────────────────────────────────────────────────────


def _run_phase(
	label: str,
	cmd: list[str],
	track_component: bool = False,
	timeout: int = 1800,
	cwd: str | None = None,
) -> bool:
	"""
	Run cmd as a subprocess with a 10-line rolling log.

	Prints an active (↻) header, streams output into the log panel,
	then collapses to a single ✓/✗ line on completion.

	If track_component=True, parses doit task lines and updates a
	subtitle showing the currently running component.
	"""
	current = [label]
	spin = "\033[38;2;255;215;0m↻\033[0m"

	def _draw_header() -> None:
		subtitle = gray_desc(current[0]) if track_component else ""
		suffix = f"  {subtitle}" if subtitle and current[0] != label else ""
		sys.stdout.write(f"  {spin}  {white_b(label)}{suffix}\n")
		sys.stdout.write(f"  {gray_desc('─' * (_term_width() - 6))}\n")

	_log(f"\n=== {label} ===")
	_draw_header()
	for _ in range(LOG_LINES):
		sys.stdout.write("\n")
	sys.stdout.flush()

	log_buf: list[str] = []

	proc = subprocess.Popen(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		stdin=subprocess.DEVNULL,  # prevent apt from sniffing the terminal via stdin
		text=False,  # binary - we handle \r ourselves
		bufsize=0,
		cwd=cwd or _REPO,
		env={**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "dumb"},
	)

	def _reader() -> None:
		partial = b""
		last_draw = 0.0
		_DRAW_INTERVAL = 0.05  # 20fps max - prevents cursor-storm on rapid apt output

		def _maybe_redraw(force: bool = False) -> None:
			nonlocal last_draw
			now = time.monotonic()
			if force or now - last_draw >= _DRAW_INTERVAL:
				_redraw_log(log_buf, LOG_LINES)
				last_draw = now

		while True:
			chunk = proc.stdout.read(512)
			if not chunk:
				break
			data = partial + chunk
			# Split on \n; each segment may itself contain \r-overwritten content.
			# Keep only the last \r-separated piece (what a terminal would show).
			*segments, partial = data.split(b"\n")
			for seg in segments:
				# \r within a segment: apt progress lines overwrite in place.
				# Take the last non-empty piece - that's what the terminal shows.
				cr_parts = [p for p in seg.split(b"\r") if p]
				if not cr_parts:
					continue
				line = _ANSI_RE.sub("", cr_parts[-1].decode("utf-8", errors="replace")).rstrip()
				if not line:
					continue
				_log(line)
				if track_component:
					m = _TASK_RE.match(line)
					if m and m.group(1) != current[0]:
						current[0] = m.group(1)
						sys.stdout.write(f"\033[{LOG_LINES + 2}A")
						_draw_header()
						# _draw_header writes 2 lines so cursor is at log line 1;
						# go down LOG_LINES to return to the bottom of the panel.
						sys.stdout.write(f"\033[{LOG_LINES}B")
						sys.stdout.flush()
				log_buf.append(line)
				_maybe_redraw()
		# Flush any remaining partial line and do a final forced redraw.
		if partial:
			line = _ANSI_RE.sub("", partial.split(b"\r")[-1].decode("utf-8", errors="replace")).rstrip()
			if line:
				_log(line)
				log_buf.append(line)
		_maybe_redraw(force=True)

	t = threading.Thread(target=_reader, daemon=True)
	t.start()
	try:
		proc.wait(timeout=timeout)
	except subprocess.TimeoutExpired:
		proc.kill()
		proc.wait()
		log_buf.append(f"[timed out after {timeout // 60} minutes]")
		_redraw_log(log_buf, LOG_LINES)
	except (KeyboardInterrupt, SystemExit) as _exc:
		proc.kill()
		proc.wait()
		# Collapse the log panel before the terminal is restored.
		sys.stdout.write(f"\033[{LOG_LINES + 2}A")
		sys.stdout.write(f"  {red('✗')}  {bold(label)}  {gray_desc('(cancelled)')}\033[K\n\033[J")
		sys.stdout.flush()
		raise _exc
	t.join()

	ok = proc.returncode == 0
	_log(f"=== {label} {'ok' if ok else 'FAILED'} ===")

	# Collapse: rewind past log + separator + header, write result, clear below.
	sys.stdout.write(f"\033[{LOG_LINES + 2}A")
	icon = green("✓") if ok else red("✗")
	sys.stdout.write(f"  {icon}  {bold(label)}\033[K\n")
	if not ok and log_buf:
		# Show the last few lines so the user can see what failed.
		width = _term_width() - 8
		for line in log_buf[-3:]:
			sys.stdout.write(f"     {gray_desc(line[:width])}\033[K\n")
	sys.stdout.write("\033[J")
	sys.stdout.flush()
	return ok


# ── IP detection ──────────────────────────────────────────────────────────────


def _detect_public_ip(version: int) -> str:
	"""Try to determine the public IPv4 or IPv6 via external HTTP services."""
	services_v4 = [
		"https://ipv4.icanhazip.com",
		"https://ifconfig.me/ip",
		"https://api.ipify.org",
		"https://api4.my-ip.io/ip",
	]
	services_v6 = [
		"https://ipv6.icanhazip.com",
		"https://api6.ipify.org",
		"https://api6.my-ip.io/ip",
	]
	services = services_v6 if version == 6 else services_v4
	for url in services:
		try:
			with urllib.request.urlopen(url, timeout=3) as r:
				ip = r.read().decode().strip()
				parsed = ipaddress.ip_address(ip)

				if parsed.version == version:
					return ip
		except Exception:
			pass
	return ""


def _detect_private_ip(version: int) -> str:
	"""Return the local interface address used to reach the internet."""
	try:
		family = socket.AF_INET6 if version == 6 else socket.AF_INET
		target = ("2001:4860:4860::8888", 80) if version == 6 else ("8.8.8.8", 80)
		with socket.socket(family, socket.SOCK_DGRAM) as s:
			s.connect(target)
			return s.getsockname()[0]
	except Exception:
		return ""


# ── Preflight ─────────────────────────────────────────────────────────────────


def _preflight() -> bool:
	import shutil

	OK, WARN, ERR = "ok", "warn", "err"
	checks: list[tuple[str, str, str]] = []

	try:
		with open("/proc/meminfo") as f:
			for line in f:
				if line.startswith("MemTotal:"):
					mb = int(line.split()[1]) // 1024
					if mb < 256:
						checks.append((ERR, "RAM", f"{mb} MB - 512 MB minimum required"))
					elif mb < 512:
						checks.append((WARN, "RAM", f"{mb} MB - 512 MB recommended"))
					else:
						checks.append((OK, "RAM", f"{mb} MB available"))
					break
	except Exception:
		pass

	try:
		# Check the partitions that actually receive install artifacts.
		low: list[str] = []
		warn: list[str] = []
		for mount in ("/", "/home", "/var", "/tmp"):
			try:
				free_mb = shutil.disk_usage(mount).free // (1024**2)
				if free_mb < 500:
					low.append(f"{mount} ({free_mb} MB)")
				elif free_mb < 1024:
					warn.append(f"{mount} ({free_mb} MB)")
			except Exception:
				pass
		if low:
			checks.append((ERR, "Disk", f"< 500 MB free on: {', '.join(low)} - 1 GB recommended"))
		elif warn:
			checks.append((WARN, "Disk", f"< 1 GB free on: {', '.join(warn)}"))
		else:
			checks.append((OK, "Disk", "sufficient free space on all partitions"))
	except Exception:
		pass

	if not checks:
		return True

	_ICON = {
		OK: "\033[38;2;95;255;135m✓\033[0m",
		WARN: "\033[38;2;255;215;0m!\033[0m",
		ERR: "\033[38;2;255;85;85m✗\033[0m",
	}
	any_err = any(s == ERR for s, _, _ in checks)
	any_warn = any(s == WARN for s, _, _ in checks)

	if any_err or any_warn:
		label_w = max(len(lbl) for _, lbl, _ in checks) + 2
		print(f"  {bold('Pre-flight')}")
		print(f"  {gray_desc('─' * (_term_width() - 4))}")
		for status, lbl, msg in checks:
			pad = " " * (label_w - len(lbl))
			print(f"  {_ICON[status]}  {lbl}{pad}{gray_desc(msg)}")
		print()

	if any_err:
		print(f"  {red('Setup cannot continue. Resolve the issues above first.')}\n")
		return False

	return True


# ── Main ──────────────────────────────────────────────────────────────────────


def _choose_profile() -> str:
	"""Show the install profile selection screen. Returns 'recommended', 'original', or 'custom'."""
	from boxctl.ui import select_prompt

	_header("Installation profile")
	return select_prompt(
		"Which installation profile would you like to use?",
		"Recommended and Original pre-fill all settings. You can still adjust anything before confirming.",
		[
			("Recommended", "Modern stack: oxi.email, rspamd, restic, Beszel, external DNS, Radicale.", "recommended"),
			("Original", "Classic stack: Roundcube, SpamAssassin, duplicity, Munin, self-hosted DNS, Radicale, FileBrowser.", "original"),
			("Custom", "Step through every option and choose yourself.", "custom"),
		],
		"recommended",
		False,
	)


def _resolve_auto(value: str, auto_value: str) -> str:
	"""Return auto_value if value is 'auto' or empty, otherwise value."""
	v = value.strip()
	return auto_value if (not v or v == "auto") else v


def main() -> None:
	if os.geteuid() != 0:
		print(f"\n  {red('install.py must be run as root.')}\n")
		sys.exit(1)

	noninteractive = os.environ.get("NONINTERACTIVE", "").strip() == "1"

	if not noninteractive and not sys.stdin.isatty():
		sys.exit("Interactive terminal required.")

	if not noninteractive:
		_saved = termios.tcgetattr(sys.stdin.fileno())

		def _restore(sig, frame):
			try:
				termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved)
			except Exception:
				pass
			print("\033[?25h", end="", flush=True)
			sys.exit(1)

		signal.signal(signal.SIGTERM, _restore)
		signal.signal(signal.SIGINT, _restore)

	# Ensure UTF-8 locale so Python reads/writes files consistently.
	subprocess.run(["locale-gen", "en_US.UTF-8"], capture_output=True)
	os.environ.update({
		"LANGUAGE": "en_US.UTF-8",
		"LC_ALL": "en_US.UTF-8",
		"LANG": "en_US.UTF-8",
		"LC_TYPE": "en_US.UTF-8",
		"NCURSES_NO_UTF8_ACS": "1",
	})

	import fcntl

	_install_lockfile = open("/tmp/mailinabox-install.lock", "w")
	try:
		fcntl.flock(_install_lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
	except BlockingIOError:
		sys.exit("Another setup run is already in progress.")

	_open_log()

	# ── Preflight ─────────────────────────────────────────────────────────────
	if not noninteractive:
		_header()
	if not _preflight():
		sys.exit(1)

	# ── Migrations (re-run only) ───────────────────────────────────────────────
	if os.path.exists(CONF_PATH):
		migrate = os.path.join(_SETUP, "migrate.py")
		if os.path.exists(migrate):
			r = subprocess.run(
				[sys.executable, migrate, "--migrate"],
				capture_output=True,
				text=True,
			)
			if r.returncode != 0:
				print(f"  {red('Migration failed:')}\n{(r.stdout + r.stderr).strip()}\n")
				sys.exit(1)

	# ── Detect IPs (best-effort, shown as defaults in the wizard) ────────────
	initial = load_conf(CONF_PATH)

	guessed_v4 = _detect_public_ip(4)
	guessed_v6 = _detect_public_ip(6)
	private_v4 = _detect_private_ip(4)
	private_v6 = _detect_private_ip(6)

	class _Args:
		default_hostname = initial.get("PRIMARY_HOSTNAME", "")
		guessed_ipv4 = guessed_v4
		default_ipv4 = initial.get("PUBLIC_IP", guessed_v4)
		guessed_ipv6 = guessed_v6
		default_ipv6 = initial.get("PUBLIC_IPV6", guessed_v6)

	# ── Wizard / non-interactive conf resolution ──────────────────────────────
	if noninteractive:
		e = os.environ
		answers: dict[str, str] = {
			"PRIMARY_HOSTNAME": _resolve_auto(e.get("PRIMARY_HOSTNAME", ""), socket.getfqdn()),
			"PUBLIC_IP": _resolve_auto(e.get("PUBLIC_IP", ""), guessed_v4),
			"PUBLIC_IPV6": _resolve_auto(e.get("PUBLIC_IPV6", ""), guessed_v6),
			"ENABLE_FILEBROWSER": e.get("ENABLE_FILEBROWSER", initial.get("ENABLE_FILEBROWSER", "true")),
			"ENABLE_RADICALE": e.get("ENABLE_RADICALE", initial.get("ENABLE_RADICALE", "true")),
			"ENABLE_CLAMAV": e.get("ENABLE_CLAMAV", initial.get("ENABLE_CLAMAV", "false")),
			"WEBMAIL_CLIENT": e.get("WEBMAIL_CLIENT", initial.get("WEBMAIL_CLIENT", "oxi")),
			"SPAM_FILTER": e.get("SPAM_FILTER", initial.get("SPAM_FILTER", "rspamd")),
			"DNS_MODE": e.get("DNS_MODE", initial.get("DNS_MODE", "self")),
			"BACKUP_TOOL": e.get("BACKUP_TOOL", initial.get("BACKUP_TOOL", "restic")),
			"MONITORING_TOOL": e.get("MONITORING_TOOL", initial.get("MONITORING_TOOL", "none")),
			"TIMEZONE": e.get("TIMEZONE", initial.get("TIMEZONE", "")),
		}
		from .questions import validate_hostname, validate_ipv4

		hostname_err = validate_hostname(answers["PRIMARY_HOSTNAME"])
		ip_err = validate_ipv4(answers["PUBLIC_IP"])
		if hostname_err is not True:
			print(f"ERROR: PRIMARY_HOSTNAME is invalid: {hostname_err}")
			sys.exit(1)
		if ip_err is not True:
			print(f"ERROR: PUBLIC_IP is invalid: {ip_err}")
			sys.exit(1)
		print(f"Non-interactive install: PRIMARY_HOSTNAME={answers['PRIMARY_HOSTNAME']} PUBLIC_IP={answers['PUBLIC_IP']}")
	else:
		try:
			profile = _choose_profile()
			all_steps = [(key, label, fn) for _, key, label, fn in STEPS]

			if profile in PROFILES:
				# Merge preset values - existing conf values win on re-installs.
				for k, v in PROFILES[profile].items():
					if k not in initial:
						initial[k] = v
				# Seed auto-detected IPs so they appear on the confirm screen.
				initial.setdefault("PUBLIC_IP", guessed_v4)
				initial.setdefault("PUBLIC_IPV6", guessed_v6)
				# Populate the optionals synthetic key for confirm display.
				initial["__optionals__"] = {
					"ENABLE_RADICALE": initial.get("ENABLE_RADICALE", "false"),
					"ENABLE_CLAMAV": initial.get("ENABLE_CLAMAV", "false"),
				}
				# Only ask hostname interactively; everything else is pre-filled.
				hostname_step = [(key, label, fn) for _, key, label, fn in STEPS if key == "PRIMARY_HOSTNAME"]
				answers = run_questions(hostname_step, _Args(), VALUE_DISPLAY, initial=initial, all_steps=all_steps, all_editable=True)
			else:
				# Custom: walk through every step.
				answers = run_questions(all_steps, _Args(), VALUE_DISPLAY, initial=initial, all_steps=all_steps)

		except KeyboardInterrupt:
			clear()
			print("\n  Setup cancelled.\n")
			sys.exit(0)

	# ── Build and write /etc/mailinabox.conf ──────────────────────────────────
	storage_user = initial.get("STORAGE_USER", "user-data")
	storage_root = initial.get("STORAGE_ROOT", f"/home/{storage_user}")

	conf: dict[str, str] = {
		"STORAGE_USER": storage_user,
		"STORAGE_ROOT": storage_root,
		"PRIMARY_HOSTNAME": answers.get("PRIMARY_HOSTNAME", ""),
		"PUBLIC_IP": answers.get("PUBLIC_IP", guessed_v4),
		"PUBLIC_IPV6": answers.get("PUBLIC_IPV6", guessed_v6),
		"PRIVATE_IP": initial.get("PRIVATE_IP", private_v4),
		"PRIVATE_IPV6": initial.get("PRIVATE_IPV6", private_v6),
		"MTA_STS_MODE": initial.get("MTA_STS_MODE", "enforce"),
		"ENABLE_FILEBROWSER": answers.get("ENABLE_FILEBROWSER", initial.get("ENABLE_FILEBROWSER", "true")),
		"ENABLE_RADICALE": answers.get("ENABLE_RADICALE", initial.get("ENABLE_RADICALE", "true")),
		"ENABLE_CLAMAV": answers.get("ENABLE_CLAMAV", initial.get("ENABLE_CLAMAV", "false")),
		"WEBMAIL_CLIENT": answers.get("WEBMAIL_CLIENT", initial.get("WEBMAIL_CLIENT", "oxi")),
		"SPAM_FILTER": answers.get("SPAM_FILTER", initial.get("SPAM_FILTER", "rspamd")),
		"DNS_MODE": answers.get("DNS_MODE", initial.get("DNS_MODE", "self")),
		"BACKUP_TOOL": answers.get("BACKUP_TOOL", initial.get("BACKUP_TOOL", "restic")),
		"MONITORING_TOOL": answers.get("MONITORING_TOOL", initial.get("MONITORING_TOOL", "none")),
		"TIMEZONE": answers.get("TIMEZONE", initial.get("TIMEZONE", "")),
	}

	write_output(CONF_PATH, conf)

	# Ensure STORAGE_ROOT exists with the right ownership.
	if not os.path.isdir(storage_root):
		os.makedirs(storage_root, exist_ok=True)
	# Create system user for storage if not already present.
	r = subprocess.run(["id", "-u", storage_user], capture_output=True)
	if r.returncode != 0:
		subprocess.run(
			["useradd", "-r", "-m", "-d", storage_root, storage_user],
			check=True,
		)
	# World-readable up the directory chain (mirrors start.sh behaviour).
	d = storage_root
	while d != "/":
		os.chmod(d, 0o755)
		d = os.path.dirname(d)
	# Stamp migration number on first install.
	ver_file = os.path.join(storage_root, "mailinabox.version")
	if not os.path.exists(ver_file):
		migrate = os.path.join(_SETUP, "migrate.py")
		if os.path.exists(migrate):
			r = subprocess.run(
				[sys.executable, migrate, "--current"],
				capture_output=True,
				text=True,
			)
			if r.returncode == 0 and r.stdout.strip():
				with open(ver_file, "w") as fh:
					fh.write(r.stdout.strip() + "\n")
				subprocess.run(
					["chown", f"{storage_user}:{storage_user}", ver_file],
					capture_output=True,
				)

	# Install boxctl and component runner to a stable system path so they work
	# after the repo/tarball is deleted or moved.
	_BOXCTL_LIB = "/usr/local/lib/mailinabox"
	for src, dst in [
		(os.path.join(_SETUP, "boxctl"), os.path.join(_BOXCTL_LIB, "boxctl")),
		(os.path.join(_SETUP, "components"), os.path.join(_BOXCTL_LIB, "components")),
	]:
		if os.path.exists(dst):
			shutil.rmtree(dst)
		shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

	# Put mailinabox / boxctl on PATH. Always write so the wrapper is refreshed on re-install.
	for name, content in [
		("/usr/local/bin/mailinabox", "#!/bin/bash\nexec boxctl \"$@\"\n"),
		("/usr/local/bin/boxctl", f"#!/bin/bash\nexec python3 {_BOXCTL_LIB}/boxctl/__main__.py \"$@\"\n"),
	]:
		with open(name, "w") as fh:
			fh.write(content)
		os.chmod(name, 0o755)

	# ── Install screen ────────────────────────────────────────────────────────
	if not noninteractive:
		_header("Installing...")

	errors: list[str] = []

	# Repair any interrupted dpkg state before touching apt. This is a no-op
	# on a clean system but recovers from a previous interrupted install.
	subprocess.run(
		["dpkg", "--configure", "-a"],
		env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
		capture_output=True,
	)

	# System packages: python3-venv, doit, exclusiveprocess, email_validator -
	# the minimum needed before the component runner can import itself.
	base_packages = [
		"python3",
		"python3-venv",
		"python3-pip",
		"apt-utils",
		"lsb-release",
		"git",
		"wget",
		"curl",
		"ca-certificates",
	]
	if not _run_phase(
		"System packages",
		[
			"apt-get",
			"install",
			"-y",
			"--no-install-recommends",
			"-o",
			"Dpkg::Options::=--force-confdef",
			"-o",
			"Dpkg::Options::=--force-confnew",
			"-o",
			"DPkg::Lock::Timeout=300",
			*base_packages,
		],
	):
		errors.append("packages")

	if not errors:
		# Ensure doit is available in system Python.
		if not _run_phase(
			"Python dependencies",
			[sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "doit"],
		):
			errors.append("python-deps")

	if not errors:
		# Run as a module so relative imports inside runner.py work.
		# cwd=_SETUP makes `components` importable as a top-level package.
		if not _run_phase(
			"Components",
			[sys.executable, "-m", "components.runner"],
			track_component=True,
			timeout=2700,  # 45 min for first install
			cwd=_SETUP,
		):
			errors.append("components")

	if not errors:
		for label, path in [
			("DNS update", "/usr/local/lib/mailinabox/dns_update"),
			("Web config", "/usr/local/lib/mailinabox/web_update"),
		]:
			if os.path.exists(path):
				if not _run_phase(label, [path]):
					errors.append(label.lower().replace(" ", "-"))
			else:
				errors.append(f"{label.lower()} not installed (component may have failed)")

	# ── Result ────────────────────────────────────────────────────────────────
	if errors:
		print(f"\n  {red('Setup finished with errors:')} {', '.join(errors)}")
		print(f"  {gray_desc('Run sudo setup/install.sh to retry.')}\n")
		sys.exit(1)

	ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	width = 72
	_log("\n" + "=" * width)
	_log("  Mail-in-a-Box - Setup Complete")
	_log(f"  Finished: {ts}")
	_log(f"  Next step: sudo boxctl bootstrap")
	_log("=" * width)
	print(f"\n  {green('✓')}  {bold('Setup complete.')}\n")

	# Show admin URL, setup code, and TLS fingerprint.
	# Not logged - the setup code is a credential.
	try:
		from boxctl.bootstrap import run as _bootstrap

		_bootstrap(show_cert=True, install=True, from_installer=True)
	except Exception:
		# Bootstrap can fail if the management service isn't up yet.
		# Give the user a clear next step rather than silent nothing.
		print(f"  {gray_desc('─' * (_term_width() - 4))}")
		print(f"  To finish setup, run:  {bold('sudo boxctl bootstrap')}")
		print(f"  {gray_desc('─' * (_term_width() - 4))}")
		print()


if __name__ == "__main__":
	main()
