"""
User authentication and mail routing.

Steps:
  db-group        - create mail-db group; add postfix + dovecot; set DB dir perms
  postfix-maps    - write sqlite .cf map files for virtual mailboxes, aliases, domains
  postfix-main    - editconf main.cf for map paths and SASL settings [dep: postfix:spam-filter]
  dovecot-auth    - write auth unix-listener config and dovecot-sql.conf.ext
  db-init         - initialize SQLite user/alias schema (skipped if DB file exists)

Both postfix and dovecot are restarted when any task runs, since mail routing
and IMAP auth both depend on the database and Postfix/Dovecot config here.
"""

import os
import subprocess
import sys

from doit.tools import config_changed, run_once

from .. import artifacts, SETUP_DIR
from ..component import Component
from ..task_names import POSTFIX_SPAM_FILTER

# ── Component declaration ─────────────────────────────────────────────────────

COMPONENT = Component(
	name="users",
	packages=[],
	# Both postfix and dovecot pick up the map changes after their restarts.
	services=["postfix", "dovecot"],
	docker_services=["postfix", "dovecot"],
)


# ── Tasks ─────────────────────────────────────────────────────────────────────


def make_tasks(env: dict, runtime: str) -> list[dict]:
	storage_root = env["STORAGE_ROOT"]
	db_path = os.path.join(storage_root, "mail", "db", "users.sqlite")
	db_dir = os.path.dirname(db_path)

	return [
		{
			"name": "db-group",
			# Create the shared group that allows both Dovecot auth-workers and
			# Postfix proxymap to write to SQLite's WAL -shm file. The setgid bit
			# on the DB directory ensures new files (including -shm) inherit the group.
			"uptodate": [config_changed(f"{db_dir}:{artifacts.fn_stamp(_db_group)}")],
			"actions": [(_db_group, [db_dir])],
		},
		{
			"name": "postfix-maps",
			# Write the four sqlite .cf lookup files. Stamp: db_path (appears in
			# each file's dbpath field) and function source.
			"uptodate": [config_changed(f"{db_path}:{artifacts.fn_stamp(_postfix_maps)}")],
			"actions": [(_postfix_maps, [db_path])],
		},
		{
			"name": "postfix-main",
			# editconf main.cf to wire in map paths and SASL settings.
			# Shares main.cf with postfix component; dep ensures we run after it.
			"uptodate": [config_changed(f"{db_path}:{artifacts.fn_stamp(_postfix_main)}")],
			"task_dep": [POSTFIX_SPAM_FILTER, "users:postfix-maps"],
			"actions": [(_postfix_main, [db_path])],
		},
		{
			"name": "dovecot-auth",
			# Write auth unix-listener conf (Postfix uses it for SASL) and the
			# 2.3 dovecot-sql.conf.ext. On 2.4 the SQL is inline in auth-sql.conf.ext
			# (written by the dovecot component); dovecot-sql.conf.ext is harmless.
			"uptodate": [config_changed(f"{storage_root}:{artifacts.fn_stamp(_dovecot_auth)}")],
			"actions": [(_dovecot_auth, [storage_root, db_path])],
		},
		{
			"name": "db-init",
			# Initialize the schema. targets= causes doit to re-run only if the
			# DB file is missing; once it exists the task is considered done.
			# initialize_database() uses CREATE TABLE IF NOT EXISTS, so re-running
			# on a live DB is safe if the file is ever accidentally removed.
			"targets": [db_path],
			"actions": [(_db_init, [storage_root])],
		},
	]


# ── Action functions ──────────────────────────────────────────────────────────


def _db_group(db_dir: str) -> None:
	"""Create the mail-db group and grant postfix + dovecot access to the DB dir.

	The setgid bit on db_dir ensures that SQLite's -shm and -wal files created
	at runtime inherit the mail-db group and become group-writable (SQLite copies
	the database file's mode to -shm via fchmod, bypassing the process umask).
	"""
	subprocess.run(["groupadd", "--system", "mail-db"], check=False)
	subprocess.run(["usermod", "-aG", "mail-db", "postfix"], check=True)
	subprocess.run(["usermod", "-aG", "mail-db", "dovecot"], check=True)

	os.makedirs(db_dir, exist_ok=True)
	subprocess.run(["chown", "root:mail-db", db_dir], check=True)
	subprocess.run(["chmod", "2770", db_dir], check=True)


def _postfix_maps(db_path: str) -> None:
	"""Write sqlite lookup map configs for Postfix virtual mail routing.

	All maps use proxy:sqlite: in main.cf so lookups route through proxymap,
	which runs un-chrooted and can reach the DB path. The chrooted smtpd cannot.
	"""
	# sender-login-maps: who is allowed to claim a given MAIL FROM address.
	# Checks explicit permitted_senders on aliases first, then alias destinations,
	# then direct user entries.
	artifacts.write_file(
		"/etc/postfix/sender-login-maps.cf",
		f"dbpath={db_path}\n"
		"query=SELECT permitted_senders FROM (\n"
		"  SELECT permitted_senders, 0 AS priority FROM aliases WHERE source='%s' AND permitted_senders IS NOT NULL\n"
		"  UNION SELECT destination AS permitted_senders, 1 AS priority FROM aliases WHERE source='%s' AND permitted_senders IS NULL\n"
		"  UNION SELECT email AS permitted_senders, 2 AS priority FROM users WHERE email='%s'\n"
		"  ) ORDER BY priority LIMIT 1\n",
	)

	# virtual-mailbox-domains: which domains we accept mail for.
	artifacts.write_file(
		"/etc/postfix/virtual-mailbox-domains.cf",
		f"dbpath={db_path}\nquery=SELECT 1 FROM users WHERE email LIKE '%%@%s'\n  UNION SELECT 1 FROM aliases WHERE source LIKE '%%@%s'\n  UNION SELECT 1 FROM auto_aliases WHERE source LIKE '%%@%s'\n  LIMIT 1\n",
	)

	# virtual-mailbox-maps: which addresses have actual mailboxes (not just aliases).
	artifacts.write_file(
		"/etc/postfix/virtual-mailbox-maps.cf",
		f"dbpath={db_path}\nquery=SELECT 1 FROM users WHERE email='%s'\n",
	)

	# virtual-alias-maps: expand aliases and catch-alls.
	# Postfix queries this map multiple times per message: first the full address,
	# then just @domain (catch-all). virtual-alias-maps has precedence over
	# virtual-mailbox-maps, so catch-alls would swallow mail for real users unless
	# users also appear here - hence the UNION on the users table (each user becomes
	# an alias to themselves). Priority ordering: direct alias > user entry > catch-all.
	# Empty destination rows are excluded so permitted_senders-only aliases don't
	# accidentally absorb mail.
	artifacts.write_file(
		"/etc/postfix/virtual-alias-maps.cf",
		f"dbpath={db_path}\n"
		"query=SELECT destination FROM (\n"
		"  SELECT destination, 0 AS priority FROM aliases WHERE source='%s' AND destination<>''\n"
		"  UNION SELECT email AS destination, 1 AS priority FROM users WHERE email='%s'\n"
		"  UNION SELECT destination, 2 AS priority FROM auto_aliases WHERE source='%s' AND destination<>''\n"
		"  ) ORDER BY priority LIMIT 1\n",
	)


def _postfix_main(db_path: str) -> None:
	"""Wire up Postfix to use our sqlite maps and configure SASL auth via Dovecot.

	SMTP AUTH is disabled on port 25 (smtpd_sasl_auth_enable=no) to prevent
	outbound relay without DKIM signing; it is enabled explicitly for the
	submission port in master.cf.
	"""
	# Prevent intra-domain spoofing: MAIL FROM must be owned by the logged-in user.
	artifacts.editconf(
		"/etc/postfix/main.cf",
		"smtpd_sender_login_maps=proxy:sqlite:/etc/postfix/sender-login-maps.cf",
	)

	# SMTPUTF8 is disabled because Dovecot's LMTP doesn't support it; any message
	# received with the SMTPUTF8 flag would bounce on delivery.
	artifacts.editconf(
		"/etc/postfix/main.cf",
		"smtputf8_enable=no",
		"virtual_mailbox_domains=proxy:sqlite:/etc/postfix/virtual-mailbox-domains.cf",
		"virtual_mailbox_maps=proxy:sqlite:/etc/postfix/virtual-mailbox-maps.cf",
		"virtual_alias_maps=proxy:sqlite:/etc/postfix/virtual-alias-maps.cf",
		r"local_recipient_maps=$virtual_mailbox_maps",
	)

	# Point Postfix at Dovecot's auth socket. Auth is disabled on port 25 (see #830):
	# port 25 does not run DKIM on relayed mail, so outbound authenticated mail
	# wouldn't be signed. Auth is enabled explicitly for the submission ports in master.cf.
	artifacts.editconf(
		"/etc/postfix/main.cf",
		"smtpd_sasl_type=dovecot",
		"smtpd_sasl_path=private/auth",
		"smtpd_sasl_auth_enable=no",
	)


def _dovecot_auth(storage_root: str, db_path: str) -> None:
	"""Write the Dovecot auth unix-listener and the 2.3 SQL config file.

	99-local-auth.conf exposes Dovecot's auth service on a socket that Postfix
	can reach (it lives inside /var/spool/postfix/private, within Postfix's
	chroot jail). Mode 0666 + postfix user/group so smtpd can connect.

	dovecot-sql.conf.ext is only used by Dovecot 2.3 (2.4 uses inline SQL in
	auth-sql.conf.ext written by the dovecot component). Writing it on 2.4 is
	harmless since auth-sql.conf.ext no longer references it.
	"""
	artifacts.write_file(
		"/etc/dovecot/conf.d/99-local-auth.conf",
		"service auth {\n  unix_listener /var/spool/postfix/private/auth {\n    mode = 0666\n    user = postfix\n    group = postfix\n  }\n}\n",
	)

	# 2.3 SQL config. %Lu normalises the username to lowercase for lookups.
	artifacts.write_file(
		"/etc/dovecot/dovecot-sql.conf.ext",
		"driver = sqlite\n"
		f"connect = {db_path}\n"
		"default_pass_scheme = BLF-CRYPT\n"
		"password_query = SELECT password FROM users WHERE email='%Lu'\n"
		"user_query = SELECT email, \\\n"
		f"  '{storage_root}/mail/mailboxes/%Ld/%Ln' AS home, \\\n"
		"  'mail' AS uid, 'mail' AS gid, \\\n"
		"  CASE WHEN quota='0' OR quota='' THEN '' ELSE concat('*:bytes=', quota) END AS quota_rule \\\n"
		"  FROM users WHERE email='%Lu'\n"
		"iterate_query = SELECT email FROM users\n",
	)
	os.chmod("/etc/dovecot/dovecot-sql.conf.ext", 0o600)


def _db_init(storage_root: str) -> None:
	"""Initialize the SQLite mail user/alias schema via mailconfig.

	Note: the bash equivalent runs `doveadm quota recalc -A` after schema init.
	The component runner restarts Dovecot after this task completes; quota
	recalculation is left as a post-restart operational step, not run here.

	initialize_database() uses CREATE TABLE IF NOT EXISTS so it is safe to run
	on an existing database. After schema creation, the DB file is set to 660
	so SQLite copies that mode to -shm on creation (SQLite's robust_open uses
	fchmod to match the database file permissions, bypassing the process umask).
	"""
	# Management is installed under /usr/local/lib/mailinabox/ after setup.
	# During initial setup the repo management/ directory is available.
	mgmt_path = "/usr/local/lib/mailinabox/management"
	if not os.path.isdir(mgmt_path):
		mgmt_path = os.path.join(os.path.dirname(SETUP_DIR), "management")
	sys.path.insert(0, mgmt_path)
	# Import only database.py - not the full mailconfig package, which pulls in
	# mailconfig/users.py at load time and that requires passlib. The mail
	# container runs system Python and only needs the schema init, not passlib.
	from mail.mailconfig.database import initialize_database  # type: ignore[import]

	initialize_database({"STORAGE_ROOT": storage_root})

	db_path = os.path.join(storage_root, "mail", "db", "users.sqlite")
	if os.path.exists(db_path):
		os.chmod(db_path, 0o660)
