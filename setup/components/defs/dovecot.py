"""
Dovecot IMAP/POP3 server and local delivery agent (LDA).

Dovecot is both the IMAP/POP server (the protocol that email applications use
to query a mailbox) and the local delivery agent (LDA), responsible for writing
emails to mailbox storage on disk. As part of local mail delivery, Dovecot
executes actions on incoming mail as defined in sieve scripts.

Dovecot's LDA role comes after spam filtering. Postfix hands mail off to
rspamd (or spampd for the spamassassin path) which in turn hands it off to
Dovecot. This all happens using the LMTP protocol.

Steps:
  sysctl    - raise fs.inotify.max_user_instances for IMAP IDLE connections
  limits    - default_process_limit, default_vsz_limit, log_path in 10-master.conf
  mailboxes - install dovecot-mailboxes.conf → 15-mailboxes.conf
  ports     - disable plain IMAP (143) and POP3 (110) in 10-master.conf [dep: limits]
  idle      - imap_idle_notify_interval in 20-imap.conf
  lda       - postmaster_address in 15-lda.conf
  auth      - enable auth-sql, disable auth-system in 10-auth.conf
  version   - all version-specific config: mail location, SSL, quota, sieve, auth-sql
              [dep: auth, idle - both share files that version also writes]
  sieve     - copy and pre-compile sieve-spam.sieve [dep: version]
  dirs      - create mail/sieve directories, set /etc/dovecot permissions [dep: sieve]
  ufw       - allow imaps, pop3s, and sieve ports

Dovecot 2.3 (Ubuntu 22.04/24.04) and 2.4 (Ubuntu 26.04+) require completely
different config syntax. The version step branches at runtime based on the
installed binary. See the dovecot-2x-compat memory for the full breaking-change list.
"""

import os
import shutil
import subprocess

from doit.tools import config_changed

from .. import artifacts, SETUP_DIR
from ..component import Component

# ── Component declaration ─────────────────────────────────────────────────────

COMPONENT = Component(
	name="dovecot",
	packages=[
		"dovecot-core",
		"dovecot-imapd",
		"dovecot-pop3d",
		"dovecot-lmtpd",
		"dovecot-sqlite",
		"sqlite3",
		"dovecot-sieve",
		"dovecot-managesieved",
	],
	services=["dovecot"],
	docker_services=["dovecot"],
)

_CONF_DIR = os.path.join(SETUP_DIR, "conf", "mail")

_SSL_CIPHERS = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"


# ── Tasks ─────────────────────────────────────────────────────────────────────


def make_tasks(env: dict, runtime: str) -> list[dict]:
	storage_root = env["STORAGE_ROOT"]
	hostname = env.get("PRIMARY_HOSTNAME", "localhost")
	# DOVECOT_IMAP_BIND controls the plain IMAP listener bind address.
	# Default is loopback; set to 0.0.0.0 when the IMAP client is on a
	# separate host or container. LMTP always stays on 127.0.0.1.
	imap_bind = env.get("DOVECOT_IMAP_BIND", "127.0.0.1")

	mailboxes_src = os.path.join(_CONF_DIR, "dovecot-mailboxes.conf")
	sieve_src = os.path.join(_CONF_DIR, "sieve-spam.txt")
	mailcrypt_lua_src = os.path.join(_CONF_DIR, "mailcrypt-auth.lua")

	# Encryption at rest (mail_crypt). When on, the SQL passdb chains to a Lua
	# passdb that delivers the per-user crypt_user_key_password at login. See
	# the mailcrypt task and _mailcrypt for the full wiring.
	encryption = env.get("ENCRYPTION_AT_REST", "false").lower() == "true"

	# Detect installed Dovecot version. Packages are installed before make_tasks
	# is called, so the binary is always available at this point.
	ver_result = subprocess.run(["dovecot", "--version"], capture_output=True, text=True, check=False)
	dovecot_version = ver_result.stdout.split()[0] if ver_result.stdout.strip() else "2.3"

	# System RAM (physical + swap) for vsz_limit calculation.
	mem_result = subprocess.run(["free", "-tm"], capture_output=True, text=True, check=False)
	total_mem_mb = 1024
	if mem_result.returncode == 0 and mem_result.stdout.strip():
		total_mem_mb = int(mem_result.stdout.strip().split("\n")[-1].split()[1])
	nproc = os.cpu_count() or 1

	# Stamp for the version step: re-runs when Dovecot version changes (OS upgrade),
	# storage path changes, IMAP bind address changes, or either branch of the
	# config function changes. Both branch stamps are included so editing 2.4-only
	# or 2.3-only code still invalidates the stamp even if the other branch is live.
	version_stamp = "|".join([
		dovecot_version,
		storage_root,
		imap_bind,
		str(encryption),
		artifacts.fn_stamp(_version_24),
		artifacts.fn_stamp(_version_23),
	])

	tasks = [
		{
			"name": "sysctl",
			"uptodate": [config_changed(artifacts.fn_stamp(_sysctl))],
			"actions": [(_sysctl,)],
		},
		{
			"name": "limits",
			# Per-machine stamp: process limit scales with CPU, vsz with RAM.
			"uptodate": [config_changed(f"{nproc}:{total_mem_mb}:{artifacts.fn_stamp(_limits)}")],
			"actions": [(_limits, [nproc, total_mem_mb])],
		},
		{
			"name": "mailboxes",
			# Re-run when the source conf file changes (updated mailbox defaults).
			"uptodate": [config_changed(artifacts.hash_files(mailboxes_src))],
			"actions": [(_mailboxes, [mailboxes_src])],
		},
		{
			"name": "ports",
			# Shares 10-master.conf with limits; dep prevents concurrent writes.
			"uptodate": [config_changed(artifacts.fn_stamp(_ports))],
			"task_dep": ["dovecot:limits"],
			"actions": [(_ports,)],
		},
		{
			"name": "idle",
			# 20-imap.conf is also written by the version task; dep declared there.
			"uptodate": [config_changed(artifacts.fn_stamp(_idle))],
			"actions": [(_idle,)],
		},
		{
			"name": "lda",
			"uptodate": [config_changed(f"{hostname}:{artifacts.fn_stamp(_lda)}")],
			"actions": [(_lda, [hostname])],
		},
		{
			"name": "auth",
			# Enables auth-sql, disables auth-system in 10-auth.conf.
			# version also writes to 10-auth.conf, so version deps on this.
			"uptodate": [config_changed(artifacts.fn_stamp(_auth))],
			"actions": [(_auth,)],
		},
		{
			"name": "version",
			# Writes to many conf.d files including 10-auth.conf and 20-imap.conf.
			# Deps on auth and idle to prevent concurrent writes to those files.
			"uptodate": [config_changed(version_stamp)],
			"task_dep": ["dovecot:auth", "dovecot:idle"],
			"actions": [(_version, [dovecot_version, storage_root, imap_bind, encryption])],
		},
		{
			"name": "sieve",
			# sievec runs doveconf internally, so all conf.d files must exist first.
			"uptodate": [config_changed(f"{artifacts.hash_files(sieve_src)}:{artifacts.fn_stamp(_sieve)}")],
			"task_dep": ["dovecot:version"],
			"actions": [(_sieve, [sieve_src])],
		},
		{
			"name": "dirs",
			# Creates mail/sieve dirs and locks down /etc/dovecot after all writes.
			"uptodate": [config_changed(f"{storage_root}:{artifacts.fn_stamp(_dirs)}")],
			"task_dep": ["dovecot:sieve"],
			"actions": [(_dirs, [storage_root])],
		},
		{
			"name": "ufw",
			"uptodate": [config_changed(artifacts.fn_stamp(_ufw))],
			"actions": [(_ufw,)],
		},
	]

	# Encryption at rest: install the Lua auth plugin, write the mail_crypt config,
	# and deploy the auth Lua script. Only added when the feature is enabled so
	# installs that don't use it never pull in dovecot-auth-lua. Runs after the
	# version step (which writes auth-sql.conf.ext with the passdb chain) and
	# before dirs (which locks down /etc/dovecot permissions).
	if encryption:
		tasks.append({
			"name": "mailcrypt",
			"uptodate": [config_changed(
				f"{artifacts.fn_stamp(_mailcrypt)}:{artifacts.hash_files(mailcrypt_lua_src)}"
			)],
			"task_dep": ["dovecot:version"],
			"actions": [(_mailcrypt, [mailcrypt_lua_src])],
		})
		# Ensure the /etc/dovecot lockdown runs after the lua script is installed.
		for t in tasks:
			if t["name"] == "sieve":
				t.setdefault("task_dep", []).append("dovecot:mailcrypt")

	return tasks


# ── Action functions ──────────────────────────────────────────────────────────


def _sysctl() -> None:
	"""Raise inotify max_user_instances so many IMAP IDLE connections fit.

	Default is 128; at ~5 open folders per user that limits IDLE push to
	~25 concurrent users. 1024 raises it to ~200 users on a modest server.
	"""
	os.makedirs("/etc/sysctl.d", exist_ok=True)
	artifacts.write_file(
		"/etc/sysctl.d/99-inotify.conf",
		"fs.inotify.max_user_instances=1024\n",
	)
	# Apply immediately - best-effort, may silently fail inside containers.
	subprocess.run(
		["sysctl", "-p", "/etc/sysctl.d/99-inotify.conf"],
		capture_output=True,
		check=False,
	)


def _limits(nproc: int, total_mem_mb: int) -> None:
	"""Set IMAP connection limit and virtual memory cap in 10-master.conf.

	process_limit = 250 * cores (at ~5 connections/user = 50 * cores users).
	vsz_limit = total_mem / 3 so a single runaway process can't OOM the box.
	"""
	artifacts.editconf(
		"/etc/dovecot/conf.d/10-master.conf",
		f"default_process_limit={nproc * 250}",
		f"default_vsz_limit={total_mem_mb // 3}M",
		"log_path=/var/log/mail.log",
	)


def _mailboxes(src: str) -> None:
	"""Install INBOX/Drafts/Sent/Trash/Spam/Archive mailbox subscription config."""
	shutil.copy2(src, "/etc/dovecot/conf.d/15-mailboxes.conf")


def _ports() -> None:
	"""Disable plain-text IMAP (143) and POP3 (110); only TLS variants are exposed.

	The default Dovecot config has these ports commented as '#port = N'. Setting
	them to 0 disables the listener. Both seds are idempotent: after the first
	run the '#port = N' pattern no longer matches.
	"""
	for pattern in [r"s/#port = 143/port = 0/", r"s/#port = 110/port = 0/"]:
		subprocess.run(
			["sed", "-i", pattern, "/etc/dovecot/conf.d/10-master.conf"],
			check=True,
		)


def _idle() -> None:
	"""Reduce IMAP IDLE notify interval to keep NAT connections alive. See [#129]."""
	artifacts.editconf(
		"/etc/dovecot/conf.d/20-imap.conf",
		"imap_idle_notify_interval=4 mins",
	)


def _lda(hostname: str) -> None:
	"""Set postmaster_address; required or Dovecot's LMTP service refuses to start.

	An alias for postmaster@ will be created automatically by the management daemon.
	"""
	artifacts.editconf(
		"/etc/dovecot/conf.d/15-lda.conf",
		f"postmaster_address=postmaster@{hostname}",
	)


def _auth() -> None:
	"""Switch Dovecot from system-user auth to our SQLite-backed auth-sql driver.

	Both sed patterns are idempotent: the first ensures auth-system is commented
	regardless of current state; the second uncomments auth-sql only if commented.
	"""
	for pattern in [
		r"s/#*\(!include auth-system.conf.ext\)/#\1/",
		r"s/#\(!include auth-sql.conf.ext\)/\1/",
	]:
		subprocess.run(
			["sed", "-i", pattern, "/etc/dovecot/conf.d/10-auth.conf"],
			check=True,
		)


def _version(dovecot_version: str, storage_root: str, imap_bind: str, encryption: bool = False) -> None:
	"""Dispatch to the correct version-specific config function.

	This wrapper exists so the action signature is simple; the actual logic
	(and the fn_stamps) live in _version_24 and _version_23.
	"""
	if dovecot_version.startswith("2.4."):
		_version_24(storage_root, imap_bind, encryption)
	else:
		_version_23(storage_root, imap_bind, encryption)


def _version_24(storage_root: str, imap_bind: str, encryption: bool = False) -> None:
	"""Dovecot 2.4 config (Ubuntu 26.04+).

	Opts in to the new config format via dovecot_config_version=2.4.0, which
	makes every 2.4 incompatibility a fatal startup error. Key changes:
	- plugin{} blocks removed (quota and sieve use SET_FILTER_ARRAY blocks)
	- mail_location split into mail_driver + mail_path
	- Variable syntax: %d/%n -> %{user|domain}/%{user|username}
	- SSL settings renamed (ssl_cert -> ssl_server_cert_file, etc.)
	- mail_plugins is BOOLLIST - no $variable expansion, use plain names
	- inet_listener 'address' removed; use 'listen' instead
	- auth-sql is inline in passdb/userdb blocks (no separate .ext file)
	"""
	# Opt in to strict 2.4 parsing. Without this, 2.4 runs in compat mode and
	# some breakage is silent. With it, every incompatibility is a startup error.
	artifacts.editconf(
		"/etc/dovecot/dovecot.conf",
		"dovecot_config_version=2.4.0",
		"dovecot_storage_version=2.4.0",
	)

	artifacts.editconf(
		"/etc/dovecot/conf.d/10-mail.conf",
		"mail_driver=maildir",
		f"mail_path={storage_root}/mail/mailboxes/%{{user|domain}}/%{{user|username}}",
		"mail_privileged_group=mail",
		"first_valid_uid=0",
	)

	# disable_plaintext_auth inverted to auth_allow_cleartext (value also inverted).
	artifacts.editconf(
		"/etc/dovecot/conf.d/10-auth.conf",
		"auth_mechanisms=plain login",
		"auth_allow_cleartext=no",
	)

	# ssl_cert/ssl_key renamed; < prefix gone; ssl_min_protocol removed (TLSv1.2
	# is the floor in 2.4 by default). ssl_prefer_server_ciphers renamed and
	# value changed from yes/no to server/client.
	artifacts.editconf(
		"/etc/dovecot/conf.d/10-ssl.conf",
		"ssl=required",
		f"ssl_server_cert_file={storage_root}/ssl/ssl_certificate.pem",
		f"ssl_server_key_file={storage_root}/ssl/ssl_private_key.pem",
		f"ssl_cipher_list={_SSL_CIPHERS}",
		"ssl_server_prefer_ciphers=client",
	)

	# mail_plugins is a BOOLLIST in 2.4 - the parser does no $variable expansion.
	# Using "$mail_plugins quota" would try to load a plugin literally named
	# "$mail_plugins" and fail fatally. Use plain names only.
	subprocess.run(
		["sed", "-i", r"s/#mail_plugins =.*/mail_plugins = quota/", "/etc/dovecot/conf.d/10-mail.conf"],
		check=True,
	)
	# Guard the imap_quota insertion so re-runs don't duplicate the line.
	if (
		subprocess.run(
			["grep", "-q", "mail_plugins.*imap_quota", "/etc/dovecot/conf.d/20-imap.conf"],
			check=False,
		).returncode
		!= 0
	):
		subprocess.run(
			["sed", "-i", r"s/\(mail_plugins =.*\)/\1\n  mail_plugins = imap_quota/", "/etc/dovecot/conf.d/20-imap.conf"],
			check=True,
		)
	subprocess.run(
		["sed", "-i", r"s/#mail_plugins = .*/mail_plugins = sieve/", "/etc/dovecot/conf.d/20-lmtp.conf"],
		check=True,
	)

	# quota: plugin{} removed; quota roots use SET_FILTER_ARRAY syntax.
	# quota_storage_grace is now a SIZE (bytes); 10M matches the 2.3 spirit of 10%.
	artifacts.write_file(
		"/etc/dovecot/conf.d/90-quota.conf",
		"quota quota {\n"
		"    quota_driver = maildir\n"
		"    quota_storage_grace = 10M\n"
		"}\n"
		"\n"
		"quota_status_success = DUNNO\n"
		"quota_status_nouser = DUNNO\n"
		'quota_status_overquota = "522 5.2.2 Mailbox is full"\n'
		"\n"
		"service quota-status {\n"
		"    executable = quota-status -p postfix\n"
		"    inet_listener quota-status {\n"
		"        port = 12340\n"
		"    }\n"
		"}\n",
	)

	# inet_listener 'address' field removed in 2.4; bind address is now 'listen'.
	artifacts.write_file(
		"/etc/dovecot/conf.d/99-local.conf",
		f"service lmtp {{\n  unix_listener /var/spool/postfix/private/dovecot-lmtp {{\n    mode = 0660\n    user = postfix\n    group = postfix\n  }}\n  inet_listener lmtp {{\n    listen = 127.0.0.1\n    port = 10026\n  }}\n}}\n\nservice imap-login {{\n  inet_listener imap {{\n    listen = {imap_bind}\n    port = 143\n    ssl = no\n  }}\n}}\nprotocol imap {{\n  mail_max_userip_connections = 40\n}}\nprotocol lmtp {{\n  auth_username_format = %{{user | lower}}\n}}\n",
	)

	# sieve: plugin{} removed. Pigeonhole 2.4 uses sieve_script SET_FILTER_ARRAY
	# blocks. sieve_script_active_path replaces the old 'sieve =' symlink setting.
	# sieve_before/after/dir settings are gone; sieve_script_type controls ordering.
	artifacts.write_file(
		"/etc/dovecot/conf.d/99-local-sieve.conf",
		"sieve_redirect_envelope_from = recipient\n"
		"\n"
		"sieve_script spam {\n"
		"  sieve_script_type = before\n"
		"  sieve_script_driver = file\n"
		"  sieve_script_path = /etc/dovecot/sieve-spam.sieve\n"
		"  sieve_script_precedence = 10\n"
		"}\n"
		"\n"
		"sieve_script global_before {\n"
		"  sieve_script_type = before\n"
		"  sieve_script_driver = file\n"
		f"  sieve_script_path = {storage_root}/mail/sieve/global_before\n"
		"  sieve_script_precedence = 20\n"
		"}\n"
		"\n"
		"sieve_script global_after {\n"
		"  sieve_script_type = after\n"
		"  sieve_script_driver = file\n"
		f"  sieve_script_path = {storage_root}/mail/sieve/global_after\n"
		"}\n"
		"\n"
		"sieve_script personal {\n"
		"  sieve_script_type = personal\n"
		"  sieve_script_driver = file\n"
		f"  sieve_script_path = {storage_root}/mail/sieve/%{{user|domain}}/%{{user|username}}\n"
		f"  sieve_script_active_path = {storage_root}/mail/sieve/%{{user|domain}}/%{{user|username}}.sieve\n"
		"}\n",
	)

	# 2.4 auth-sql: inline passdb/userdb blocks; no separate dovecot-sql.conf.ext.
	# quota_storage_size column returns per-user limit (replaces 2.3 quota_rule).
	# When encryption at rest is on, the SQL passdb must not stop after verifying
	# the password: it continues to the Lua passdb (defined in 95-mail-crypt.conf)
	# which delivers crypt_user_key_password. result_failure=return-fail keeps a
	# failed SQL verification authoritative so the Lua passdb can never override it.
	chain = (
		"  result_success = continue\n"
		"  result_failure = return-fail\n"
		if encryption else ""
	)
	# Per-user mail_crypt activation. mail_crypt needs crypt_user_key_curve at
	# delivery time (userdb) to generate per-folder keys. Returning it only for
	# users who have a committed password slot scopes encryption to opted-in
	# mailboxes: the subquery yields NULL (field absent) for everyone else, so
	# mail_crypt stays inactive for them. crypt_user_key_password is delivered
	# separately by the Lua passdb at login for decryption.
	curve_field = (
		", \\\n"
		"    (SELECT 'prime256v1' FROM mail_keys k WHERE k.user_id = users.id "
		"AND k.slot_type='password' LIMIT 1) AS crypt_user_key_curve"
		if encryption else ""
	)
	db_path = os.path.join(storage_root, "mail", "db", "users.sqlite")
	artifacts.write_file(
		"/etc/dovecot/conf.d/auth-sql.conf.ext",
		"passdb sql {\n"
		+ chain
		+ "  sql_driver = sqlite\n"
		f"  sqlite_path = {db_path}\n"
		"  passdb_default_password_scheme = BLF-CRYPT\n"
		"  passdb_sql_query = SELECT password FROM users WHERE email='%{user}'\n"
		"}\n"
		"userdb sql {\n"
		"  sql_driver = sqlite\n"
		f"  sqlite_path = {db_path}\n"
		"  userdb_sql_query = SELECT email, \\\n"
		f"    '{storage_root}/mail/mailboxes/%{{user|domain}}/%{{user|username}}' AS home, \\\n"
		"    'mail' AS uid, 'mail' AS gid, \\\n"
		"    CASE WHEN quota='0' OR quota='' THEN 0 ELSE CAST(quota AS INTEGER) END AS quota_storage_size"
		+ curve_field
		+ " \\\n"
		"    FROM users WHERE email='%{user}'\n"
		"  userdb_sql_iterate_query = SELECT email AS user FROM users\n"
		"}\n",
	)


def _version_23(storage_root: str, imap_bind: str, encryption: bool = False) -> None:
	"""Dovecot 2.3 config (Ubuntu 22.04/24.04). Uses legacy plugin{} syntax.

	TODO: encryption-at-rest wiring for 2.3 (plugin{} mail_crypt block + Lua
	passdb) is not yet implemented. The 2.4 path is the supported target; 2.3
	installs currently ignore ENCRYPTION_AT_REST. The mailcrypt task writes 2.4
	config, so enabling this on 2.3 would need a version branch there too.
	"""
	artifacts.editconf(
		"/etc/dovecot/conf.d/10-mail.conf",
		f"mail_location=maildir:{storage_root}/mail/mailboxes/%d/%n",
		"mail_privileged_group=mail",
		"first_valid_uid=0",
	)

	artifacts.editconf(
		"/etc/dovecot/conf.d/10-auth.conf",
		"disable_plaintext_auth=yes",
		"auth_mechanisms=plain login",
	)

	# 2.3 uses '<' prefix to read cert/key from file. ssl_min_protocol caps at
	# TLSv1.2 since 2.3 does not support TLSv1.3.
	artifacts.editconf(
		"/etc/dovecot/conf.d/10-ssl.conf",
		"ssl=required",
		f"ssl_cert=<{storage_root}/ssl/ssl_certificate.pem",
		f"ssl_key=<{storage_root}/ssl/ssl_private_key.pem",
		"ssl_min_protocol=TLSv1.2",
		f"ssl_cipher_list={_SSL_CIPHERS}",
		"ssl_prefer_server_ciphers=no",
	)

	# 2.3 mail_plugins use $mail_plugins to append to the package defaults.
	subprocess.run(
		["sed", "-i", r"s/#mail_plugins =\(.*\)/mail_plugins =\1 $mail_plugins quota/", "/etc/dovecot/conf.d/10-mail.conf"],
		check=True,
	)
	if (
		subprocess.run(
			["grep", "-q", r"mail_plugins.* imap_quota", "/etc/dovecot/conf.d/20-imap.conf"],
			check=False,
		).returncode
		!= 0
	):
		subprocess.run(
			["sed", "-i", r"s/\(mail_plugins =.*\)/\1\n  mail_plugins = $mail_plugins imap_quota/", "/etc/dovecot/conf.d/20-imap.conf"],
			check=True,
		)
	subprocess.run(
		["sed", "-i", r"s/#mail_plugins = .*/mail_plugins = $mail_plugins sieve/", "/etc/dovecot/conf.d/20-lmtp.conf"],
		check=True,
	)

	artifacts.write_file(
		"/etc/dovecot/conf.d/90-quota.conf",
		"plugin {\n  quota = maildir\n\n  quota_grace = 10%\n\n  quota_status_success = DUNNO\n  quota_status_nouser = DUNNO\n  quota_status_overquota = \"522 5.2.2 Mailbox is full\"\n}\n\nservice quota-status {\n    executable = quota-status -p postfix\n    inet_listener {\n        port = 12340\n    }\n}\n",
	)

	# 2.3 pop3_uidl_format: must be set explicitly. 2.4's default is already
	# equivalent (%{uid|hex(8)}%{uidvalidity|hex(8)}) and does not accept this
	# printf-style format, so this setting is 2.3-only.
	artifacts.editconf(
		"/etc/dovecot/conf.d/20-pop3.conf",
		"pop3_uidl_format=%08Xu%08Xv",
	)

	# 2.3 uses 'address' inside inet_listener blocks.
	artifacts.write_file(
		"/etc/dovecot/conf.d/99-local.conf",
		f"service lmtp {{\n  unix_listener /var/spool/postfix/private/dovecot-lmtp {{\n    mode = 0660\n    user = postfix\n    group = postfix\n  }}\n  inet_listener lmtp {{\n    address = 127.0.0.1\n    port = 10026\n  }}\n}}\n\nservice imap-login {{\n  inet_listener imap {{\n    address = {imap_bind}\n    port = 143\n    ssl = no\n  }}\n}}\nprotocol imap {{\n  mail_max_userip_connections = 40\n}}\nprotocol lmtp {{\n  auth_username_format = %Lu\n}}\n",
	)

	# 2.3 sieve uses plugin{} with sieve_before/after/dir settings.
	artifacts.write_file(
		"/etc/dovecot/conf.d/99-local-sieve.conf",
		"plugin {\n"
		"  sieve_before = /etc/dovecot/sieve-spam.sieve\n"
		f"  sieve_before2 = {storage_root}/mail/sieve/global_before\n"
		f"  sieve_after = {storage_root}/mail/sieve/global_after\n"
		f"  sieve = {storage_root}/mail/sieve/%d/%n.sieve\n"
		f"  sieve_dir = {storage_root}/mail/sieve/%d/%n\n"
		"  sieve_redirect_envelope_from = recipient\n"
		"}\n",
	)

	# 2.3 auth-sql references a separate dovecot-sql.conf.ext file (written by
	# the users component after this one runs).
	artifacts.write_file(
		"/etc/dovecot/conf.d/auth-sql.conf.ext",
		"passdb {\n  driver = sql\n  args = /etc/dovecot/dovecot-sql.conf.ext\n}\nuserdb {\n  driver = sql\n  args = /etc/dovecot/dovecot-sql.conf.ext\n}\n",
	)


def _mailcrypt(lua_src: str) -> None:
	"""Configure encryption at rest (mail_crypt) for Dovecot 2.4.

	Loads the mail_crypt plugin, gives it a per-home file attribute dict (where it
	stores key metadata), and adds the Lua passdb that delivers the per-user
	crypt_user_key_password at login (SQL passdb chains into it - see _version_24).

	Deliberately does NOT set a global crypt_user_key_curve: that would make
	mail_crypt auto-generate keypairs for every user on delivery and encrypt
	everyone's mail. Instead, a user's keypair is generated explicitly only when
	they enable encryption (management runs `doveadm mailbox cryptokey generate`).
	So keypair existence is the per-user switch, and non-opted-in mailboxes are
	untouched.
	"""
	# Install the Lua auth plugin only now (feature is opt-in).
	from .. import packages

	packages.ensure_installed(["dovecot-auth-lua"])

	# Install the auth Lua script (root-owned, group dovecot, not world-readable).
	dest_lua = "/etc/dovecot/mailcrypt-auth.lua"
	shutil.copy2(lua_src, dest_lua)
	subprocess.run(["chown", "root:dovecot", dest_lua], check=True)
	subprocess.run(["chmod", "0640", dest_lua], check=True)

	# mail_crypt config. crypt_write_algorithm is the default; set explicitly for
	# clarity. mail_attribute uses the 2.4 dict-block form (validated on 2.4.2).
	artifacts.write_file(
		"/etc/dovecot/conf.d/95-mail-crypt.conf",
		"mail_plugins {\n"
		"  mail_crypt = yes\n"
		"}\n"
		"crypt_write_algorithm = aes-256-gcm-sha256\n"
		"mail_attribute {\n"
		"  dict file {\n"
		"    path = %{home}/dovecot-attributes\n"
		"  }\n"
		"}\n"
		"passdb lua {\n"
		"  lua_file = /etc/dovecot/mailcrypt-auth.lua\n"
		"}\n"
		"\n"
		"# Cache passdb results so the Lua->management->Argon2id unwrap runs on a\n"
		"# cache miss, not on every IMAP/POP connection. The unwrapped key sits in\n"
		"# the auth cache for the TTL (bounded); it is already in the mail process\n"
		"# during a session, so the marginal exposure is the TTL window.\n"
		"auth_cache_size = 10M\n"
		"auth_cache_ttl = 5 mins\n"
		"auth_cache_negative_ttl = 30 secs\n",
	)


def _sieve(src: str) -> None:
	"""Copy and pre-compile the global spam sieve script.

	sievec runs doveconf internally to validate the script against the active
	config. It must run after the version step has written all conf.d files.
	Pre-compiling as root avoids silent failures at LMTP delivery time when
	Dovecot's LMTP process lacks write access to /etc/dovecot.
	"""
	dest = "/etc/dovecot/sieve-spam.sieve"
	shutil.copy2(src, dest)
	subprocess.run(["sievec", dest], check=True)


def _dirs(storage_root: str) -> None:
	"""Create mail/sieve directories and lock down /etc/dovecot permissions.

	chown -R is only issued on first creation to avoid traversing a live mail
	store on every run. Directory creation is always idempotent.
	"""
	mailboxes = os.path.join(storage_root, "mail", "mailboxes")
	first_run = not os.path.isdir(mailboxes)
	os.makedirs(mailboxes, exist_ok=True)
	if first_run:
		subprocess.run(["chown", "-R", "mail:mail", mailboxes], check=True)

	sieve_root = os.path.join(storage_root, "mail", "sieve")
	first_run_sieve = not os.path.isdir(sieve_root)
	for d in [
		sieve_root,
		os.path.join(sieve_root, "global_before"),
		os.path.join(sieve_root, "global_after"),
	]:
		os.makedirs(d, exist_ok=True)
	if first_run_sieve:
		subprocess.run(["chown", "-R", "mail:mail", sieve_root], check=True)

	# Dovecot binds its SASL auth socket inside the Postfix spool chroot.
	# Postfix creates this directory on its first start, but dovecot starts
	# first on a fresh install. Create it with postfix:postfix 0700 so
	# postfix can bind sockets there - root:root 0755 causes Permission Denied.
	priv = "/var/spool/postfix/private"
	if not os.path.isdir(priv):
		import pwd as _pwd, grp as _grp

		os.makedirs(priv)
		pw = _pwd.getpwnam("postfix")
		os.chown(priv, pw.pw_uid, _grp.getgrnam("postfix").gr_gid)
		os.chmod(priv, 0o700)

	# Lock down /etc/dovecot: owned by mail:dovecot, not world-readable.
	# Run after all conf.d files are written (sieve task is the last writer).
	owner = subprocess.run(
		["stat", "-c", "%U", "/etc/dovecot"],
		capture_output=True,
		text=True,
		check=False,
	).stdout.strip()
	if owner != "mail":
		subprocess.run(["chown", "-R", "mail:dovecot", "/etc/dovecot"], check=True)
	subprocess.run(["chmod", "-R", "o-rwx", "/etc/dovecot"], check=True)


def _ufw() -> None:
	"""Allow IMAPS (993), POP3S (995), and Sieve (4190) through the firewall."""
	artifacts.ufw_allow("imaps")
	artifacts.ufw_allow("pop3s")
	artifacts.ufw_allow("sieve")
