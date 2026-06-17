import os
import sys

from core.utils import load_environment, shell

def _email_administrator(subject, body):
	# email_administrator.py is a script, not an importable module - it reads
	# sys.argv/stdin and runs top-level code unconditionally, so it must be
	# invoked as a subprocess (matching how daily_tasks.sh already pipes other
	# backup output into it), never imported directly.
	script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
		'mail', 'email_administrator.py')
	shell('check_output', [script, subject], input=body.encode())

def perform_backup(full_backup):
	"""Dispatches to the active backend. Callers never branch on BACKUP_TOOL -
	this is the one place that decision is made."""
	from .config import get_backup_config

	env = load_environment()

	from exclusiveprocess import Lock
	Lock(die=True).forever()

	config = get_backup_config(env)
	if config["target"] == "off":
		return

	if env.get("BACKUP_TOOL", "duplicity") == "restic":
		_perform_backup_restic(env, config)
	else:
		_perform_backup_duplicity(env, config, full_backup)

def _checkpoint_sqlite_databases(storage_root):
	# Flush WAL logs for every SQLite database under storage_root so that
	# a plain file copy (duplicity, or restic's own file scan) sees a fully
	# consistent database file. All databases are opened with WAL mode via
	# initialize_database().
	import sqlite3, pathlib
	for db_path in pathlib.Path(storage_root).rglob('*.sqlite'):
		try:
			conn = sqlite3.connect(str(db_path), timeout=10)
			conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
			conn.close()
		except Exception:
			pass

def _run_pre_script(env, backup_root, config):
	# Execute a pre-backup script that copies files outside the homedir.
	# Run as the STORAGE_USER user, not as root. Pass our settings in
	# environment variables so the script has access to STORAGE_ROOT.
	pre_script = os.path.join(backup_root, 'before-backup')
	if os.path.exists(pre_script):
		shell('check_call',
			['su', env['STORAGE_USER'], '-c', pre_script, config["target"]],
			env=env)

def _run_post_script(env, backup_root, config):
	post_script = os.path.join(backup_root, 'after-backup')
	if os.path.exists(post_script):
		shell('check_call',
			['su', env['STORAGE_USER'], '-c', post_script, config["target"]],
			env=env)

def _perform_backup_duplicity(env, config, full_backup):
	from .duplicity_args import DUPLICITY, get_duplicity_additional_args, get_duplicity_env_vars, get_duplicity_target_url
	from .status import should_force_full, _backup_cache_dir
	from .config import get_target_type

	backup_root = os.path.join(env["STORAGE_ROOT"], 'backup')
	backup_cache_dir = _backup_cache_dir(env)
	backup_dir = os.path.join(backup_root, 'encrypted')

	# On the first run, always do a full backup. Incremental
	# will fail. Otherwise do a full backup when the size of
	# the increments since the most recent full backup are
	# large.
	try:
		full_backup = full_backup or should_force_full(config, env)
	except Exception as e:
		# This was the first call to duplicity, and there might
		# be an error already.
		print(e)
		sys.exit(1)

	# Checkpoint all SQLite databases in STORAGE_ROOT before backup.
	_checkpoint_sqlite_databases(env["STORAGE_ROOT"])

	_run_pre_script(env, backup_root, config)

	# Run a backup of STORAGE_ROOT (but excluding the backups themselves!).
	# --allow-source-mismatch is needed in case the box's hostname is changed
	# after the first backup. See #396.
	shell('check_call', [
		DUPLICITY,
		"full" if full_backup else "incr",
		"--verbosity", "warning", "--no-print-statistics",
		"--archive-dir", backup_cache_dir,
		"--exclude", backup_root,
		"--exclude", os.path.join(env["STORAGE_ROOT"], "owncloud-backup"),
		"--volsize", "250",
		"--gpg-options", "'--cipher-algo=AES256'",
		"--allow-source-mismatch",
		*get_duplicity_additional_args(env),
		env["STORAGE_ROOT"],
		get_duplicity_target_url(config),
		],
		get_duplicity_env_vars(env))

	# Remove old backups. This deletes all backup data no longer needed
	# from more than 3 days ago.
	shell('check_call', [
		DUPLICITY,
		"remove-older-than",
		"%dD" % config["min_age_in_days"],
		"--verbosity", "error",
		"--archive-dir", backup_cache_dir,
		"--force",
		*get_duplicity_additional_args(env),
		get_duplicity_target_url(config)
		],
		get_duplicity_env_vars(env))

	# From duplicity's manual:
	# "This should only be necessary after a duplicity session fails or is
	# aborted prematurely."
	# That may be unlikely here but we may as well ensure we tidy up if
	# that does happen - it might just have been a poorly timed reboot.
	shell('check_call', [
		DUPLICITY,
		"cleanup",
		"--verbosity", "error",
		"--archive-dir", backup_cache_dir,
		"--force",
		*get_duplicity_additional_args(env),
		get_duplicity_target_url(config)
		],
		get_duplicity_env_vars(env))

	# Change ownership of backups to the user-data user, so that the after-bcakup
	# script can access them.
	if get_target_type(config) == 'file':
		shell('check_call', ["/bin/chown", "-R", env["STORAGE_USER"], backup_dir])

	_run_post_script(env, backup_root, config)

def _restic_repo_exists(repo, extra_args, restic_env):
	from .restic_args import RESTIC
	code, output = shell('check_output', [RESTIC, "-r", repo, "snapshots", "--json", *extra_args], restic_env, trap=True, capture_stderr=True)
	if code == 0:
		return True
	# restic's specific "repository does not exist yet" signature - this is the
	# expected first-run condition, not a failure. Anything else (auth, network,
	# wrong password) must not be masked as "needs init."
	if "Is there a repository at the following location" in output or "unable to open config file" in output:
		return False
	raise Exception("Something is wrong with the backup: " + output)

def _perform_backup_restic(env, config):
	from .restic_args import RESTIC, get_restic_repository, get_restic_extra_args, get_restic_env_vars

	backup_root = os.path.join(env["STORAGE_ROOT"], 'backup')
	repo = get_restic_repository(env, config)
	extra_args = get_restic_extra_args(env, config)
	restic_env = get_restic_env_vars(env, config)

	# restic init is atomic by restic's own design (the config object is
	# written last) - an interrupted init simply isn't "initialized" yet and
	# the next run's existence check correctly retries it. No custom
	# partial-init recovery is needed.
	if not _restic_repo_exists(repo, extra_args, restic_env):
		shell('check_call', [RESTIC, "-r", repo, "init", *extra_args], restic_env)

	_checkpoint_sqlite_databases(env["STORAGE_ROOT"])

	_run_pre_script(env, backup_root, config)

	# Back up STORAGE_ROOT, excluding the backup directories themselves.
	shell('check_call', [
		RESTIC, "-r", repo, "backup",
		"--exclude", backup_root,
		"--exclude", os.path.join(env["STORAGE_ROOT"], "owncloud-backup"),
		*extra_args,
		env["STORAGE_ROOT"],
		], restic_env)

	# Pruning lifecycle guarantee: forget --keep-within {N}d --prune always
	# runs immediately after a successful backup. It is never skipped. If it
	# fails (e.g. a stale lock from a previous crashed run), retry once after
	# unlocking. If it still fails, the backup itself is NOT marked as failed -
	# a dirty retention window doesn't invalidate data that was just safely
	# taken - but the failure must surface as a non-fatal operational error
	# through both logging and email_administrator.py, never silently swallowed.
	_prune_restic(repo, extra_args, restic_env, config)

	_run_post_script(env, backup_root, config)

def _prune_restic(repo, extra_args, restic_env, config):
	from .restic_args import RESTIC

	forget_cmd = [RESTIC, "-r", repo, "forget", "--keep-within", f"{config['min_age_in_days']}d", "--prune", *extra_args]
	code, output = shell('check_output', forget_cmd, restic_env, trap=True, capture_stderr=True)
	if code == 0:
		return

	if "unable to create lock" in output or "already locked" in output:
		shell('check_call', [RESTIC, "-r", repo, "unlock", *extra_args], restic_env)
		code, output = shell('check_output', forget_cmd, restic_env, trap=True, capture_stderr=True)
		if code == 0:
			return

	# Still failing after one retry - report, don't fail the backup. Both
	# channels, every time: this must never go unreported, and it must never
	# be conflated with the backup itself having failed.
	warning = f"restic forget --prune failed and did not recover after one retry:\n\n{output}"
	print(f"WARNING: {warning}", file=sys.stderr)
	try:
		_email_administrator("Backup Retention Warning", warning)
	except Exception:
		pass

def run_duplicity_verification():
	from .config import get_backup_config
	from .duplicity_args import DUPLICITY, get_duplicity_additional_args, get_duplicity_env_vars, get_duplicity_target_url
	from .status import _backup_cache_dir

	env = load_environment()
	backup_root = os.path.join(env["STORAGE_ROOT"], 'backup')
	config = get_backup_config(env)
	backup_cache_dir = _backup_cache_dir(env)

	shell('check_call', [
		DUPLICITY,
		"--verbosity", "info",
		"verify",
		"--compare-data",
		"--archive-dir", backup_cache_dir,
		"--exclude", backup_root,
		"--exclude", os.path.join(env["STORAGE_ROOT"], "owncloud-backup"),
		*get_duplicity_additional_args(env),
		get_duplicity_target_url(config),
		env["STORAGE_ROOT"],
	], get_duplicity_env_vars(env))

def run_duplicity_restore(args):
	from .config import get_backup_config
	from .duplicity_args import DUPLICITY, get_duplicity_additional_args, get_duplicity_env_vars, get_duplicity_target_url
	from .status import _backup_cache_dir

	env = load_environment()
	config = get_backup_config(env)
	backup_cache_dir = _backup_cache_dir(env)
	shell('check_call', [
		DUPLICITY,
		"restore",
		"--archive-dir", backup_cache_dir,
		*get_duplicity_additional_args(env),
		get_duplicity_target_url(config),
		*args],
		get_duplicity_env_vars(env))

def verify_backup():
	"""Unified, backend-agnostic entry point. Callers must never branch on
	BACKUP_TOOL themselves - this dispatcher is the only place that happens."""
	env = load_environment()
	from .config import get_backup_config
	config = get_backup_config(env)

	if env.get("BACKUP_TOOL", "duplicity") == "restic":
		from .restic_args import RESTIC, get_restic_repository, get_restic_extra_args, get_restic_env_vars
		repo = get_restic_repository(env, config)
		extra_args = get_restic_extra_args(env, config)
		restic_env = get_restic_env_vars(env, config)
		shell('check_call', [RESTIC, "-r", repo, "check", *extra_args], restic_env)
	else:
		run_duplicity_verification()

def restore_backup(snapshot, target_dir):
	"""Unified, backend-agnostic entry point.

	`snapshot` is backend-specific by contract:
	  - restic: a snapshot ID (the `id`/`short_id` field from /backup/status entries)
	  - duplicity: a time specifier (ISO date, or a duplicity relative-time
	    string like "3D"), matching the `date` field from /backup/status entries

	Callers must never branch on BACKUP_TOOL themselves - this dispatcher is
	the only place that happens.
	"""
	env = load_environment()
	from .config import get_backup_config
	config = get_backup_config(env)

	if env.get("BACKUP_TOOL", "duplicity") == "restic":
		from .restic_args import RESTIC, get_restic_repository, get_restic_extra_args, get_restic_env_vars
		repo = get_restic_repository(env, config)
		extra_args = get_restic_extra_args(env, config)
		restic_env = get_restic_env_vars(env, config)
		shell('check_call', [RESTIC, "-r", repo, "restore", snapshot, "--target", target_dir, *extra_args], restic_env)
	else:
		run_duplicity_restore(["--time", snapshot, target_dir])

def print_duplicity_command():
	import shlex
	from .config import get_backup_config
	from .duplicity_args import get_duplicity_additional_args, get_duplicity_env_vars, get_duplicity_target_url
	from .status import _backup_cache_dir

	env = load_environment()
	config = get_backup_config(env)
	backup_cache_dir = _backup_cache_dir(env)
	for k, v in get_duplicity_env_vars(env).items():
		print(f"export {k}={shlex.quote(v)}")
	print("duplicity", "{command}", shlex.join([
		"--archive-dir", backup_cache_dir,
		*get_duplicity_additional_args(env),
		get_duplicity_target_url(config)
		]))
