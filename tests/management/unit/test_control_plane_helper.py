"""Bare-metal helper delegation in services.control_plane.

Verifies the Python side of the helperd wire protocol: intent JSON out,
{"ok": ...} JSON back, subprocess fallback only when no helper socket
exists, and Docker mode untouched.
"""

import json
import socket
import threading

import pytest

from services import control_plane


class FakeHelper:
	"""One-shot helper socket: accepts a single connection, records the
	request line, replies with a scripted response."""

	def __init__(self, sock_path, response=b'{"ok": true}\n'):
		self.received = None
		self._response = response
		self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		sock_path.unlink(missing_ok=True)
		self._server.bind(str(sock_path))
		self._server.listen(1)
		self._thread = threading.Thread(target=self._serve, daemon=True)
		self._thread.start()

	def _serve(self):
		conn, _ = self._server.accept()
		buf = b""
		while not buf.endswith(b"\n"):
			chunk = conn.recv(4096)
			if not chunk:
				break
			buf += chunk
		self.received = buf
		conn.sendall(self._response)
		conn.close()

	def close(self):
		self._server.close()
		self._thread.join(timeout=2)


@pytest.fixture
def bare_metal(monkeypatch, tmp_path):
	"""Force bare-metal mode with a helper socket path inside tmp_path."""
	monkeypatch.setattr(control_plane, "RUNTIME", "baremetal")
	sock_path = tmp_path / "helper.sock"
	monkeypatch.setattr(control_plane, "HELPER_SOCKET", str(sock_path))
	return sock_path


def test_restart_delegates_to_helper(bare_metal):
	helper = FakeHelper(bare_metal)
	control_plane.restart("dovecot")
	helper.close()

	req = json.loads(helper.received)
	assert req == {"intent": "service.restart", "args": {"service": "dovecot"}}


def test_reload_delegates_even_for_custom_sequence_services(bare_metal):
	# nsd has a custom bare-metal reload sequence; with a helper present
	# the sequence is the helper's job, not this process's.
	helper = FakeHelper(bare_metal)
	control_plane.reload("nsd")
	helper.close()

	req = json.loads(helper.received)
	assert req == {"intent": "service.reload", "args": {"service": "nsd"}}


def test_stop_and_disable_delegate(bare_metal):
	for func, intent in ((control_plane.stop, "service.stop"), (control_plane.disable, "service.disable")):
		helper = FakeHelper(bare_metal)
		func("filebrowser")
		helper.close()
		req = json.loads(helper.received)
		assert req == {"intent": intent, "args": {"service": "filebrowser"}}


def test_helper_error_raises_runtime_error(bare_metal):
	helper = FakeHelper(bare_metal, response=b'{"ok": false, "error": "service \\"sshd\\" not in allowlist"}\n')
	with pytest.raises(RuntimeError, match="not in allowlist"):
		control_plane.restart("sshd")
	helper.close()


def test_dead_helper_socket_raises_not_falls_back(bare_metal, monkeypatch):
	# Socket file exists but nothing is listening: this must surface as an
	# error (ConnectionRefusedError), never silently fall back to running
	# privileged subprocesses in-process.
	stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	stale.bind(str(bare_metal))
	stale.close()  # closed without listen/accept -> connect refused

	ran = []
	monkeypatch.setattr(control_plane.subprocess, "run", lambda *a, **k: ran.append(a))
	with pytest.raises(OSError):
		control_plane.restart("dovecot")
	assert ran == []


def test_no_helper_socket_falls_back_to_subprocess(bare_metal, monkeypatch):
	# No socket file at all (helper not installed): the pre-helper
	# subprocess path must still work.
	ran = []
	monkeypatch.setattr(control_plane.subprocess, "run", lambda argv, **k: ran.append(argv))
	control_plane.restart("dovecot")
	assert ran == [["/usr/sbin/service", "dovecot", "restart"]]


def test_docker_mode_ignores_helper(monkeypatch, tmp_path):
	monkeypatch.setattr(control_plane, "RUNTIME", "docker")
	monkeypatch.setattr(control_plane, "HELPER_SOCKET", str(tmp_path / "helper.sock"))

	sent = []
	monkeypatch.setattr(control_plane, "_send", lambda service, action: sent.append((service, action)))
	control_plane.restart("postfix")
	assert sent == [("postfix", "restart")]
