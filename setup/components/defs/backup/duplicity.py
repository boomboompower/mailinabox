"""
Duplicity backup backend.

Active when BACKUP_TOOL=duplicity. Duplicity and its cloud backend SDKs are
installed into the management venv (not system pip - Ubuntu 24.04 blocks system
pip installs via PEP 668).

Steps:
  backup-key   - generate backup encryption key (skipped if exists)
  pip-install  - install duplicity and its backend deps into the management venv
"""

import os
import subprocess

from doit.tools import config_changed

from ...component import Component
from ... import task_names
from . import backup_key_task

# ── Component declaration ─────────────────────────────────────────────────────

COMPONENT = Component(
	name="duplicity",
	packages=[],
	services=[],
	docker_services=[],
	enabled=lambda env: env.get("BACKUP_TOOL", "restic") == "duplicity",
)

_VENV = "/usr/local/lib/mailinabox/env"

# duplicity's own packaging hard-requires every cloud backend SDK it supports
# (azure-storage-blob, boxsdk, dropbox, jottalib, megatools, pyrax,
# python-swiftclient, google-api-python-client, lxml, etc.) - none are optional
# extras, they're unconditional requires_dist, even though we only ever use
# file/rsync/s3/b2. Two of those unused deps (lxml, and netifaces transitively
# via pyrax) need a C compiler to build from source when no prebuilt wheel
# exists. Rather than install a compiler just to build packages we'll never
# import, use --no-deps and supply only what our backends actually need:
# fasteners + python-gettext unconditionally, boto3/b2sdk only for s3/b2 status
# listing in backup/status.py (restic's Go binary talks to S3/B2 natively -
# no Python SDK involved there).
_DUPLICITY_PACKAGES = [
	"fasteners",
	"python-gettext",
	"b2sdk",
	"boto3",
]


# ── Tasks ─────────────────────────────────────────────────────────────────────


def make_tasks(env: dict, runtime: str) -> list[dict]:
	return [
		backup_key_task(env["STORAGE_ROOT"]),
		{
			"name": "pip-install",
			"build": True,  # no env needed - safe to run at Docker build time
			"uptodate": [config_changed(":".join(_DUPLICITY_PACKAGES))],
			# The management venv must exist before we can pip install into it.
			"task_dep": [task_names.MANAGEMENT_VIRTUALENV],
			"actions": [(_pip_install,)],
		},
	]


# ── Action functions ──────────────────────────────────────────────────────────


def _pip_install() -> None:
	"""Install duplicity and its backend deps into the management venv."""
	pip = os.path.join(_VENV, "bin", "pip")
	subprocess.run(
		[pip, "install", "--upgrade", "--prefer-binary"] + _DUPLICITY_PACKAGES,
		check=True,
		capture_output=True,
	)
	subprocess.run(
		[pip, "install", "--upgrade", "--prefer-binary", "--no-deps", "duplicity>=1.0"],
		check=True,
		capture_output=True,
	)
