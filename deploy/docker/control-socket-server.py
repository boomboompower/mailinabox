#!/usr/bin/env python3
"""
Per-container control socket server.

Listens on a Unix socket and dispatches service lifecycle requests to
handler scripts. Returns a synchronous OK/ERROR response so the caller
(management container's control_plane.py) gets the same error semantics
as a bare-metal subprocess.run(..., check=True).

Designed for one purpose, and one purpose alone - to be a simple, secure
and robust way for the management container to trigger actions in other
containers. This socket does not do anything except run handler scripts
with the requested action and return OK/ERROR. For all purposes outside
of bugs or vulnerabilities, this file is feature-complete and should
not be modified or extended.

Usage: control-socket-server.py <socket_path> <handlers_dir>

Wire protocol (newline-delimited, one request per connection):
  Request:  "<service>\\n<action>\\n"
  Response: "OK\\n"  or  "ERROR: <message>\\n"
"""

import os
import socket
import subprocess
import sys
import re


def main() -> None:
	if len(sys.argv) != 3:
		print(f"Usage: {sys.argv[0]} <socket_path> <handlers_dir>", file=sys.stderr)
		sys.exit(1)

	socket_path = sys.argv[1]
	handlers_dir = sys.argv[2]

	os.makedirs(os.path.dirname(socket_path), exist_ok=True)
	try:
		os.unlink(socket_path)
	except FileNotFoundError:
		pass

	server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	server.bind(socket_path)
	os.chmod(socket_path, 0o600)
	server.listen(5)

	while True:
		conn, _ = server.accept()
		with conn:
			try:
				data = conn.recv(256).decode().strip().split("\n")
				if len(data) < 2 or not data[0] or not data[1]:
					conn.sendall(b"ERROR: malformed request\n")
					continue

				service, action = data[0].strip(), data[1].strip()

				if not re.fullmatch(r"[A-Za-z0-9._-]+", service):
					conn.sendall(b"ERROR: invalid service name\n")
					continue

				handler = os.path.join(handlers_dir, service)

				if not os.path.isfile(handler) or not os.access(handler, os.X_OK):
					conn.sendall(f"ERROR: no handler for service '{service}'\n".encode())
					continue

				result = subprocess.run(
					[handler, action],
					capture_output=True,
					timeout=30,
				)
				if result.returncode == 0:
					conn.sendall(b"OK\n")
				else:
					msg = result.stderr.decode().strip() or result.stdout.decode().strip() or f"exited {result.returncode}"

					# Log to docker logs for easier debugging of handler failures
					print(
						f"{service} {action}: {msg}",
						file=sys.stderr,
						flush=True,
					)

					conn.sendall(f"ERROR: {service} {action} failed: {msg}\n".encode())

			except subprocess.TimeoutExpired:
				print(
					f"TIMEOUT {service} {action}",
					file=sys.stderr,
					flush=True,
				)
				conn.sendall(b"ERROR: handler timed out after 30s\n")
			except Exception as exc:
				print(
					"ERROR malformed request",
					file=sys.stderr,
					flush=True,
				)
				conn.sendall(f"ERROR: {exc}\n".encode())


if __name__ == "__main__":
	main()
