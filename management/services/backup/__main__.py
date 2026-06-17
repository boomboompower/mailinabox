"""Entry point: python3 management/services/backup [-q|--verify|--list|--status|--restore <args>|--duplicity-command]"""

import os
import sys

# When run as `python3 management/services/backup`, __package__ is '' and
# relative imports fail - same situation setup/wizard/__main__.py solves.
if __package__ in (None, ''):
	sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
	from core.utils import load_environment
	from services.backup.config import get_backup_config
	from services.backup.status import backup_status, list_target_files
	from services.backup.actions import perform_backup, verify_backup, run_duplicity_restore, print_duplicity_command
else:
	from core.utils import load_environment
	from .config import get_backup_config
	from .status import backup_status, list_target_files
	from .actions import perform_backup, verify_backup, run_duplicity_restore, print_duplicity_command

if __name__ == "__main__":
	if sys.argv[-1] == "--verify":
		# Run the active backend's verification: checks a) the backup files
		# are readable, and b) reports if they are up to date.
		verify_backup()

	elif sys.argv[-1] == "--list":
		# List the saved backup files (duplicity only - restic's status
		# already lists snapshots via --status below).
		for fn, size in list_target_files(get_backup_config(load_environment())):
			print(f"{fn}\t{size}")

	elif sys.argv[-1] == "--status":
		# Show backup status.
		import rtyaml
		ret = backup_status(load_environment())
		print(rtyaml.dump(ret["backups"]))
		print("Storage for unmatched files:", ret["unmatched_file_size"])

	elif len(sys.argv) >= 2 and sys.argv[1] == "--restore":
		# Run a restore. Rest of command line passed as arguments to
		# duplicity (this flag is duplicity-specific passthrough, kept for
		# backward compatibility - see restore_backup() for the unified API).
		run_duplicity_restore(sys.argv[2:])

	elif sys.argv[-1] == "--duplicity-command":
		print_duplicity_command()

	else:
		# Perform a backup. Add --full to force a full backup rather than
		# possibly performing an incremental backup (duplicity-only; restic
		# has no full/incremental distinction so this flag is a no-op there).
		full_backup = "--full" in sys.argv
		perform_backup(full_backup)
