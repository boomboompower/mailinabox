"""
Shared helpers for backup component defs (restic, duplicity).
"""

import os
import subprocess

from ... import artifacts


def backup_key_task(storage_root: str) -> dict:
	"""Return a doit task dict that generates the backup encryption key."""
	return {
		"name": "backup-key",
		# doit skips this task if the file already exists (targets check).
		"targets": [os.path.join(storage_root, "backup", "secret_key.txt")],
		"actions": [(_backup_key, [storage_root])],
	}


def _backup_key(storage_root: str) -> None:
	"""Generate a random backup encryption key.

	This key doubles as RESTIC_PASSWORD for restic repositories. Losing or
	replacing this file makes all existing backups permanently unreadable.
	Written with umask 077 so only root can read it.
	"""
	backup_dir = os.path.join(storage_root, "backup")
	key_path = os.path.join(backup_dir, "secret_key.txt")
	os.makedirs(backup_dir, exist_ok=True)
	if os.path.exists(key_path):
		print(f"Backup key already exists at {key_path} - skipping generation.")
		return

	old_umask = os.umask(0o077)
	try:
		result = subprocess.run(
			["openssl", "rand", "-base64", "2048"],
			check=True,
			capture_output=True,
		)
		artifacts.write_file(key_path, result.stdout.decode())
	finally:
		os.umask(old_umask)
	os.chmod(key_path, 0o600)
