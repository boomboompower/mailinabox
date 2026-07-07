"""
Privileged helper daemon (helperd, Go).

Executes the fixed menu of privileged operations (service lifecycle,
allowlisted postfix/config writes, apt, reboot) over
/run/mailinabox/helper.sock so the management daemon can run without root.
The management daemon delegates automatically when the socket exists
(management/services/control_plane.py).

Steps:
  group  - create the 'mailinabox' system group that may connect to the socket
  binary - build daemon/cmd/helperd with an ephemeral Go toolchain in /tmp
  unit   - install and enable the systemd unit

Bare metal only: in Docker, per-container control sockets already fill the
helper role and the management container holds no host privileges.
"""

import grp
import json
import os
import shutil
import subprocess

from doit.tools import config_changed

from .. import artifacts, SETUP_DIR
from ..component import Component

COMPONENT = Component(
	name="helper",
	packages=[],
	services=["mailinabox-helper"],
	docker_services=[],
	skip_on=["docker"],
)

_INST_DIR = "/usr/local/lib/mailinabox"
_BIN = os.path.join(_INST_DIR, "helperd")
_UNIT_DEST = "/lib/systemd/system/mailinabox-helper.service"
_SOCKET_GROUP = "mailinabox"


def make_tasks(env: dict, runtime: str) -> list[dict]:
	repo_root = os.path.dirname(SETUP_DIR)
	daemon_src = os.path.join(repo_root, "daemon")
	unit_src = os.path.join(daemon_src, "systemd", "mailinabox-helper.service")

	return [
		{
			"name": "group",
			"uptodate": [config_changed(artifacts.fn_stamp(_group))],
			"actions": [(_group,)],
		},
		{
			"name": "binary",
			# Re-runs when any Go source changes. When the repo is gone
			# (re-run after install), fall back to the installed binary's
			# hash so the task doesn't re-run spuriously.
			"uptodate": [config_changed(artifacts.hash_files(daemon_src) if os.path.isdir(daemon_src) else artifacts.file_hash(_BIN) if os.path.exists(_BIN) else "")],
			"targets": [_BIN],
			"actions": [(_binary, [daemon_src])],
		},
		{
			"name": "unit",
			"uptodate": [config_changed((artifacts.hash_files(unit_src) if os.path.exists(unit_src) else artifacts.hash_files(_UNIT_DEST) if os.path.exists(_UNIT_DEST) else "") + ":" + artifacts.fn_stamp(_unit))],
			"task_dep": ["helper:group", "helper:binary"],
			"actions": [(_unit, [unit_src])],
		},
	]


def _group() -> None:
	"""Create the system group whose members may connect to the helper socket.

	The management daemon's user joins this group when the web process is
	de-rooted; until then the socket is simply root-connectable.
	"""
	try:
		grp.getgrnam(_SOCKET_GROUP)
	except KeyError:
		subprocess.run(["groupadd", "--system", _SOCKET_GROUP], check=True, capture_output=True)


def _binary(daemon_src: str) -> None:
	"""Build helperd with an ephemeral Go toolchain under /tmp.

	Downloads the latest stable Go release (sha256-verified against the
	go.dev release manifest - same-source verification, like the frontend
	artifact sidecar: transit integrity, not independent provenance),
	builds a static binary, then deletes the toolchain. Nothing is
	installed system-wide; the box never carries a compiler.
	"""
	if not os.path.isdir(daemon_src):
		if os.path.exists(_BIN):
			return
		raise RuntimeError(f"helperd binary is not installed and daemon source directory does not exist ({daemon_src}). Run setup from the repo root.")

	arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
	if arch is None:
		raise RuntimeError(f"unsupported architecture for Go toolchain: {os.uname().machine}")

	manifest = subprocess.run(
		["curl", "-fsSL", "https://go.dev/dl/?mode=json"],
		check=True,
		capture_output=True,
		text=True,
	)
	release = json.loads(manifest.stdout)[0]
	tarball = next(f for f in release["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive")

	work = "/tmp/go-toolchain"
	shutil.rmtree(work, ignore_errors=True)
	os.makedirs(work)
	try:
		tar_path = os.path.join(work, tarball["filename"])
		subprocess.run(
			["curl", "-fsSL", "-o", tar_path, f"https://go.dev/dl/{tarball['filename']}"],
			check=True,
			capture_output=True,
		)
		subprocess.run(
			["sha256sum", "--check", "--strict"],
			input=f"{tarball['sha256']}  {tar_path}",
			text=True,
			check=True,
			capture_output=True,
		)
		subprocess.run(["tar", "-xzf", tar_path, "-C", work], check=True, capture_output=True)

		os.makedirs(_INST_DIR, exist_ok=True)
		build_env = os.environ.copy()
		build_env.update({
			"CGO_ENABLED": "0",
			"GOCACHE": os.path.join(work, "cache"),
			"GOPATH": os.path.join(work, "gopath"),
		})
		subprocess.run(
			[os.path.join(work, "go", "bin", "go"), "build", "-trimpath", "-ldflags", "-s -w", "-o", _BIN, "./cmd/helperd"],
			cwd=daemon_src,
			env=build_env,
			check=True,
			capture_output=True,
		)
		os.chmod(_BIN, 0o755)
	finally:
		shutil.rmtree(work, ignore_errors=True)


def _unit(unit_src: str) -> None:
	"""Install and enable the helper systemd unit.

	The unit file at /lib/systemd/system/ is the durable copy; the repo
	source is only needed the first time (or when the unit changes).
	"""
	if os.path.exists(unit_src):
		shutil.copy2(unit_src, _UNIT_DEST)
	elif not os.path.exists(_UNIT_DEST):
		raise RuntimeError(f"helper unit file not found at {unit_src} or {_UNIT_DEST}")
	subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
	subprocess.run(["systemctl", "enable", "mailinabox-helper.service"], check=True, capture_output=True)
