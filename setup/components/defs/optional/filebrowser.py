"""
FileBrowser web file manager (optional).

Steps:
  fetch        - download and install the pinned filebrowser binary (SHA256 stamp)
  dirs         - create files/ and filebrowser/ directories in STORAGE_ROOT
  auth-hook    - write filebrowser-auth.py (delegates auth to management daemon)
  config-init  - initialize the BoltDB config file (skipped if already exists)
  config-set   - apply filebrowser settings on every run
  logrotate    - write logrotate config for /var/log/filebrowser.log
  systemd      - install and enable the systemd unit
"""

import os
import shutil
import subprocess

from doit.tools import config_changed

from ... import artifacts, SETUP_DIR
from ...component import Component

# ── Component declaration ─────────────────────────────────────────────────────

COMPONENT = Component(
	name="filebrowser",
	packages=[],
	services=["filebrowser"],
	docker_services=["filebrowser"],
	enabled=lambda env: env.get("ENABLE_FILEBROWSER", "false").lower() == "true",
)

FB_VERSION = "v2.63.17"
FB_SHA256 = "d463799e80bebff70f2e6faddf8628184b11248722cd0298ca3fd340f98914e9"
FB_URL = f"https://github.com/filebrowser/filebrowser/releases/download/{FB_VERSION}/linux-amd64-filebrowser.tar.gz"

_FB_BINARY = "/usr/local/bin/filebrowser"

_CONF_DIR = os.path.join(SETUP_DIR, "conf", "systemd")


# ── Tasks ─────────────────────────────────────────────────────────────────────


def make_tasks(env: dict, runtime: str) -> list[dict]:
	storage_root = env["STORAGE_ROOT"]
	hostname = env.get("PRIMARY_HOSTNAME", "localhost")
	# FILEBROWSER_BIND: 127.0.0.1 on bare metal (nginx co-located);
	# set to 0.0.0.0 in Docker so nginx can reach it from a separate container.
	fb_bind = env.get("FILEBROWSER_BIND", "127.0.0.1")
	management_host = env.get("MANAGEMENT_HOST", "127.0.0.1")
	db_path = os.path.join(storage_root, "filebrowser", "filebrowser.db")

	return [
		{
			"name": "fetch",
			"build": True,  # binary download, no env needed
			"targets": [_FB_BINARY],
			"uptodate": [config_changed(FB_SHA256)],
			"actions": [(_fetch,)],
		},
		{
			"name": "dirs",
			"uptodate": [config_changed(f"{storage_root}:{artifacts.fn_stamp(_dirs)}")],
			"actions": [(_dirs, [storage_root])],
		},
		{
			"name": "auth-hook",
			# auth hook includes storage_root and management_host as embedded literals.
			"uptodate": [config_changed(f"{storage_root}:{management_host}:{artifacts.fn_stamp(_auth_hook)}")],
			"actions": [(_auth_hook, [storage_root, management_host])],
		},
		{
			"name": "config-init",
			# Only run if the database file doesn't exist yet.
			"targets": [db_path],
			"actions": [(_config_init, [db_path])],
		},
		{
			"name": "config-set",
			# Apply on every run so settings are updated when setup re-runs.
			"uptodate": [config_changed(f"{storage_root}:{hostname}:{fb_bind}:{artifacts.fn_stamp(_config_set)}")],
			"task_dep": ["filebrowser:config-init"],
			"actions": [(_config_set, [db_path, storage_root, hostname, fb_bind])],
		},
		{
			"name": "logrotate",
			"uptodate": [config_changed(artifacts.fn_stamp(_logrotate))],
			"actions": [(_logrotate,)],
		},
		{
			"name": "systemd",
			"targets": ["/lib/systemd/system/filebrowser.service"],
			"uptodate": [config_changed(f"{storage_root}:{artifacts.fn_stamp(_systemd)}")],
			"task_dep": ["filebrowser:config-init"],
			"actions": [(_systemd, [storage_root])],
		},
	]


# ── Action functions ──────────────────────────────────────────────────────────


def _fetch() -> None:
	"""Download, verify (SHA256), and install the pinned filebrowser binary."""
	import hashlib

	tmp = "/tmp/filebrowser.tar.gz"
	try:
		subprocess.run(["wget", "-q", "-O", tmp, FB_URL], check=True)

		h = hashlib.sha256()
		with open(tmp, "rb") as f:
			for chunk in iter(lambda: f.read(65536), b""):
				h.update(chunk)
		actual = h.hexdigest()
		if actual != FB_SHA256:
			raise RuntimeError(f"filebrowser SHA256 mismatch: got {actual}, expected {FB_SHA256}")

		subprocess.run(
			["tar", "-xzf", tmp, "-C", "/usr/local/bin", "filebrowser"],
			check=True,
		)
		os.chmod(_FB_BINARY, 0o755)
	finally:
		if os.path.exists(tmp):
			os.unlink(tmp)


def _dirs(storage_root: str) -> None:
	"""Create files/ and filebrowser/ directories. chown -R only on first creation."""
	files_dir = os.path.join(storage_root, "files")
	if not os.path.isdir(files_dir):
		os.makedirs(files_dir, exist_ok=True)
		subprocess.run(["chown", "-R", "www-data:www-data", files_dir], check=True)
	else:
		os.makedirs(files_dir, exist_ok=True)

	fb_dir = os.path.join(storage_root, "filebrowser")
	os.makedirs(fb_dir, exist_ok=True)
	subprocess.run(["chown", "www-data:www-data", fb_dir], check=True)


def _auth_hook(storage_root: str, management_host: str) -> None:
	"""Write the filebrowser auth hook script.

	The hook verifies credentials against the management daemon's /auth/verify
	endpoint. Bad credentials exit 0 with hook.action=block (not exit 1) because
	FileBrowser returns 500 on non-zero exit, which breaks fail2ban targeting.
	"""
	artifacts.write_file(
		"/usr/local/lib/filebrowser-auth.py",
		"#!/usr/bin/env python3\n"
		"import hashlib, os, sys, urllib.error, urllib.parse, urllib.request\n"
		"\n"
		f"FILES_ROOT = {storage_root!r}\n"
		f"MANAGEMENT_HOST = {management_host!r}\n"
		"\n"
		"username = os.environ.get('USERNAME', '')\n"
		"password = os.environ.get('PASSWORD', '')\n"
		"\n"
		"if not username or not password:\n"
		"    print('hook.action=block')\n"
		"    sys.exit(0)\n"
		"\n"
		"try:\n"
		"    data = urllib.parse.urlencode({'email': username, 'password': password}).encode()\n"
		"    req = urllib.request.Request(\n"
		"        f'http://{MANAGEMENT_HOST}:10222/auth/verify',\n"
		"        data=data,\n"
		"        method='POST',\n"
		"    )\n"
		"    with urllib.request.urlopen(req, timeout=5) as resp:\n"
		"        resp.read()\n"
		"\n"
		"    # Hash the email to avoid exposing addresses in the filesystem.\n"
		"    # SHA-256 of raw email bytes (lowercase hex) to match other systems.\n"
		"    user_hash = hashlib.sha256(username.encode()).hexdigest()\n"
		"    os.makedirs(os.path.join(FILES_ROOT, user_hash), mode=0o750, exist_ok=True)\n"
		"\n"
		"    print('hook.action=auth')\n"
		"    print(f'user.scope={user_hash}')\n"
		"    sys.exit(0)\n"
		"except urllib.error.HTTPError as e:\n"
		"    if e.code == 401:\n"
		"        print('hook.action=block')\n"
		"        sys.exit(0)\n"
		"    sys.exit(1)\n"
		"except Exception:\n"
		"    sys.exit(1)\n",
		mode=0o755,
	)
	subprocess.run(["chown", "root:root", "/usr/local/lib/filebrowser-auth.py"], check=True)


def _config_init(db_path: str) -> None:
	"""Initialize the BoltDB database file as www-data (only on first run)."""
	if os.path.exists(db_path):
		return  # Database already initialized

	# Stop the service first: FileBrowser holds a BoltDB exclusive lock while running.
	subprocess.run(["systemctl", "stop", "filebrowser"], check=False, capture_output=True)
	subprocess.run(
		["sudo", "-u", "www-data", "filebrowser", "config", "init", "--database", db_path],
		check=True,
		capture_output=True,
	)


def _config_set(db_path: str, storage_root: str, hostname: str, fb_bind: str) -> None:
	"""Apply filebrowser settings. Runs every setup pass so settings stay current."""
	subprocess.run(
		[
			"sudo",
			"-u",
			"www-data",
			"filebrowser",
			"config",
			"set",
			"--database",
			db_path,
			"--address",
			fb_bind,
			"--port",
			"8080",
			"--root",
			os.path.join(storage_root, "files"),
			"--baseURL",
			"/files",
			"--auth.method",
			"hook",
			"--auth.command",
			"python3 /usr/local/lib/filebrowser-auth.py",
			"--minimumPasswordLength",
			"1",  # 0 is treated as unset (Go zero value), reverts to default 12
			"--createUserDir",  # each user gets their own subdirectory under the files root
			"--branding.name",
			hostname,
		],
		check=True,
		capture_output=True,
	)

	# Ensure the log file exists before fail2ban starts watching it.
	log = "/var/log/filebrowser.log"
	if not os.path.exists(log):
		open(log, "a").close()
	subprocess.run(["chown", "www-data:www-data", log], check=True)


def _logrotate() -> None:
	"""Write logrotate config using copytruncate (no SIGUSR1 support in FileBrowser)."""
	artifacts.write_file(
		"/etc/logrotate.d/filebrowser",
		"/var/log/filebrowser.log {\n    weekly\n    rotate 4\n    compress\n    delaycompress\n    missingok\n    notifempty\n    create 0640 www-data www-data\n    copytruncate\n}\n",
	)


def _systemd(storage_root: str) -> None:
	"""Install and enable the filebrowser systemd unit."""
	unit_src = os.path.join(_CONF_DIR, "filebrowser.service")
	if os.path.exists(unit_src):
		with open(unit_src) as fh:
			unit_content = fh.read().replace("${STORAGE_ROOT}", storage_root)
		artifacts.write_file("/lib/systemd/system/filebrowser.service", unit_content)

	subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
	subprocess.run(["systemctl", "enable", "filebrowser"], check=True, capture_output=True)
