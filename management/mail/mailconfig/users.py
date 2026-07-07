import logging
import os
import re
import sqlite3


def _passlib():
	# Lazy import: passlib lives in the management venv and is not available in
	# the mail container. Importing at module level would break db-init there.
	from passlib.hash import bcrypt, sha512_crypt

	return bcrypt, sha512_crypt


from core import utils
from .database import open_database
from .validation import (
	validate_email,
	validate_password,
	validate_quota,
	validate_privilege,
	parse_privs,
	is_dcv_address,
	get_domain,
)

log = logging.getLogger(__name__)

# Archived mailbox directory names become email addresses in the admin UI, so
# reject any entry containing characters outside a basic email-safe charset.
_ARCHIVED_LOCAL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+$')
_ARCHIVED_DOMAIN_RE = re.compile(r'^[a-zA-Z0-9.-]+$')


def get_mail_users(env):
	# Returns a flat, sorted list of all user accounts.
	conn, c = open_database(env, with_connection=True)
	c.execute('SELECT email FROM users')
	users = [row[0] for row in c.fetchall()]
	conn.close()
	return utils.sort_email_addresses(users, env)


def sizeof_fmt(num):
	for unit in ['', 'K', 'M', 'G', 'T']:
		if abs(num) < 1024.0:
			if abs(num) > 99:
				return f"{num:3.0f}{unit}"
			return f"{num:2.1f}{unit}"

		num /= 1024.0

	return str(num)


def get_mail_users_ex(env, with_archived=False):
	# Returns a complex data structure of all user accounts, optionally
	# including archived (status="inactive") accounts.
	#
	# [
	#   {
	#     domain: "domain.tld",
	#     users: [
	#       {
	#         email: "name@domain.tld",
	#         privileges: [ "priv1", "priv2", ... ],
	#         status: "active" | "inactive",
	#       },
	#       ...
	#     ]
	#   },
	#   ...
	# ]

	# Get users and their privileges.
	users = []
	active_accounts = set()
	conn, c = open_database(env, with_connection=True)
	c.execute('SELECT email, privileges, quota FROM users')
	rows = c.fetchall()
	conn.close()
	for email, privileges, quota in rows:
		active_accounts.add(email)

		(user, domain) = email.split('@')
		box_size = 0
		box_quota = 0
		percent = ''
		try:
			dirsize_file = os.path.join(env['STORAGE_ROOT'], f'mail/mailboxes/{domain}/{user}/maildirsize')
			with open(dirsize_file, encoding="utf-8") as f:
				box_quota = int(f.readline().split('S')[0])
				for line in f:
					(size, _count) = line.split(' ')
					box_size += int(size)

			try:
				percent = (box_size / box_quota) * 100
			except ZeroDivisionError:
				percent = 'Error'

		except (OSError, ValueError):
			box_size = '?'
			box_quota = '?'
			percent = '?'

		if quota == '0':
			percent = ''

		user = {
			"email": email,
			"privileges": parse_privs(privileges),
			"quota": quota,
			"box_quota": box_quota,
			"box_size": sizeof_fmt(box_size) if box_size != '?' else box_size,
			"percent": f'{percent:3.0f}%' if type(percent) != str else percent,
			"status": "active",
		}
		users.append(user)

	# Add in archived accounts.
	if with_archived:
		root = os.path.join(env['STORAGE_ROOT'], 'mail/mailboxes')
		for domain in os.listdir(root):
			if os.path.isdir(os.path.join(root, domain)):
				if not _ARCHIVED_DOMAIN_RE.match(domain):
					log.warning("Skipping archived mailbox domain with invalid name: %r", domain)
					continue
				for user in os.listdir(os.path.join(root, domain)):
					if not _ARCHIVED_LOCAL_RE.match(user):
						log.warning("Skipping archived mailbox with invalid name: %r in %r", user, domain)
						continue
					email = user + "@" + domain
					mbox = os.path.join(root, domain, user)
					if email in active_accounts:
						continue
					user = {
						"email": email,
						"privileges": [],
						"status": "inactive",
						"mailbox": mbox,
						"box_size": '?',
						"box_quota": '?',
						"percent": '?',
					}
					users.append(user)

	# Group by domain.
	domains = {}
	for user in users:
		domain = get_domain(user["email"])
		if domain not in domains:
			domains[domain] = {"domain": domain, "users": []}
		domains[domain]["users"].append(user)

	# Sort domains.
	domains = [domains[domain] for domain in utils.sort_domains(domains.keys(), env)]

	# Sort users within each domain first by status then lexicographically by email address.
	for domain in domains:
		domain["users"].sort(key=lambda user: (user["status"] != "active", user["email"]))

	return domains


def get_admins(env):
	# Returns a set of users with admin privileges.
	users = set()
	for domain in get_mail_users_ex(env):
		for user in domain["users"]:
			if "admin" in user["privileges"]:
				users.add(user["email"])
	return users


def add_mail_user(email, pw, privs, quota, env):
	# validate email
	if email.strip() == "":
		return ("No email address provided.", 400)
	if not validate_email(email):
		return ("Invalid email address.", 400)
	if not validate_email(email, mode='user'):
		return ("User account email addresses may only use the lowercase ASCII letters a-z, the digits 0-9, underscore (_), hyphen (-), and period (.).", 400)
	if is_dcv_address(email) and len(get_mail_users(env)) > 0:
		# Make domain control validation hijacking a little harder to mess up by preventing the usual
		# addresses used for DCV from being user accounts. Except let it be the first account because
		# during box setup the user won't know the rules.
		return ("You may not make a user account for that address because it is frequently used for domain control validation. Use an alias instead if necessary.", 400)

	# validate password
	validate_password(pw)

	# validate privileges
	if privs is None or privs.strip() == "":
		privs = []
	else:
		privs = privs.split("\n")
		for p in privs:
			validation = validate_privilege(p)
			if validation:
				return validation

	if quota is None:
		quota = '0'

	try:
		quota = validate_quota(quota)
	except ValueError as e:
		return (str(e), 400)

	# get the database
	conn, c = open_database(env, with_connection=True)

	# hash the password
	pw = hash_password(pw)

	# add the user to the database
	try:
		c.execute("INSERT INTO users (email, password, privileges, quota) VALUES (?, ?, ?, ?)", (email, pw, "\n".join(privs), quota))
	except sqlite3.IntegrityError:
		conn.close()
		return ("User already exists.", 400)

	# write databasebefore next step
	conn.commit()
	conn.close()

	dovecot_quota_recalc(email)

	# Update things in case any new domains are added.
	from .sync import kick

	return kick(env, "mail user added")


def set_mail_password(email, pw, env):
	# validate that password is acceptable
	validate_password(pw)

	# hash the password
	pw = hash_password(pw)

	# update the database
	conn, c = open_database(env, with_connection=True)
	c.execute("UPDATE users SET password=? WHERE email=?", (pw, email))
	if c.rowcount != 1:
		conn.close()
		return (f"That's not a user ({email}).", 400)
	conn.commit()
	conn.close()
	return "OK"


def hash_password(pw):
	# Turn the plain password into a Dovecot-format hashed password.
	# Dovecot stores passwords as "{SCHEME}hashedpassworddata".
	# http://wiki2.dovecot.org/Authentication/PasswordSchemes
	bcrypt, _sha = _passlib()
	return "{BLF-CRYPT}" + bcrypt.hash(pw)


def verify_password(pw_hash: str, pw: str) -> bool:
	"""Verify a password against a Dovecot-format hash.
	Handles both BLF-CRYPT (current) and SHA512-CRYPT (legacy) so existing
	hashes keep working until users change their passwords."""
	bcrypt, sha512_crypt = _passlib()
	if pw_hash.startswith("{BLF-CRYPT}"):
		try:
			return bcrypt.verify(pw, pw_hash[len("{BLF-CRYPT}") :])
		except Exception:
			return False
	if pw_hash.startswith("{SHA512-CRYPT}"):
		try:
			return sha512_crypt.verify(pw, pw_hash[len("{SHA512-CRYPT}") :])
		except Exception:
			return False
	# Unknown scheme - strip any prefix and fall back to sha512_crypt for legacy hashes.
	raw = pw_hash.split("}", 1)[-1] if pw_hash.startswith("{") else pw_hash
	try:
		return sha512_crypt.verify(pw, raw)
	except Exception:
		return False


def get_mail_quota(email, env):
	conn, c = open_database(env, with_connection=True)
	c.execute("SELECT quota FROM users WHERE email=?", (email,))
	rows = c.fetchall()
	conn.close()
	if len(rows) != 1:
		return (f"That's not a user ({email}).", 400)

	return rows[0][0]


def set_mail_quota(email, quota, env):
	try:
		quota = validate_quota(quota)
	except ValueError as e:
		return (str(e), 400)

	# update the database
	conn, c = open_database(env, with_connection=True)
	c.execute("UPDATE users SET quota=? WHERE email=?", (quota, email))
	if c.rowcount != 1:
		conn.close()
		return (f"That's not a user ({email}).", 400)
	conn.commit()
	conn.close()

	dovecot_quota_recalc(email)

	return "OK"


def dovecot_quota_recalc(email):
	# Force dovecot to recalculate the quota info for the user.
	# Best-effort: on the same host as Dovecot this works immediately;
	# in Docker the management container doesn't have doveadm, so we skip it -
	# Dovecot will pick up the new quota from SQLite on the next IMAP connection.
	try:
		utils.shell("check_call", ["doveadm", "quota", "recalc", "-u", email])
	except Exception:
		pass


def get_mail_password(email, env):
	# Gets the hashed password for a user. Passwords are stored in Dovecot's
	# password format, with a prefixed scheme.
	# http://wiki2.dovecot.org/Authentication/PasswordSchemes
	# update the database
	conn, c = open_database(env, with_connection=True)
	c.execute('SELECT password FROM users WHERE email=?', (email,))
	rows = c.fetchall()
	conn.close()
	if len(rows) != 1:
		msg = f"That's not a user ({email})."
		raise ValueError(msg)
	return rows[0][0]


def remove_mail_user(email, env):
	# Revoke tokens before deleting the user row so nothing is left dangling
	# even if the FK cascade somehow doesn't fire.
	from auth.api_tokens import revoke_all_tokens

	revoke_all_tokens(email, env)

	conn, c = open_database(env, with_connection=True)
	c.execute("DELETE FROM users WHERE email=?", (email,))
	if c.rowcount != 1:
		conn.close()
		return (f"That's not a user ({email}).", 400)
	conn.commit()
	conn.close()

	# Update things in case any domains are removed.
	from .sync import kick

	return kick(env, "mail user removed")


def get_mail_user_privileges(email, env, empty_on_error=False):
	# get privs
	conn, c = open_database(env, with_connection=True)
	c.execute('SELECT privileges FROM users WHERE email=?', (email,))
	rows = c.fetchall()
	conn.close()
	if len(rows) != 1:
		if empty_on_error:
			return []
		return (f"That's not a user ({email}).", 400)
	return parse_privs(rows[0][0])


def add_remove_mail_user_privilege(email, priv, action, env):
	# validate
	validation = validate_privilege(priv)
	if validation:
		return validation

	# get existing privs, but may fail
	privs = get_mail_user_privileges(email, env)
	if isinstance(privs, tuple):
		return privs  # error

	# update privs set
	if action == "add":
		if priv not in privs:
			privs.append(priv)
	elif action == "remove":
		privs = [p for p in privs if p != priv]
	else:
		return ("Invalid action.", 400)

	# commit to database
	conn, c = open_database(env, with_connection=True)
	c.execute("UPDATE users SET privileges=? WHERE email=?", ("\n".join(privs), email))
	if c.rowcount != 1:
		conn.close()
		return ("Something went wrong.", 400)
	conn.commit()
	conn.close()

	# Revoke all API tokens when admin privilege is removed - a demoted user
	# should have zero access immediately, not just inert tokens sitting in the DB.
	if action == "remove" and priv == "admin":
		from auth.api_tokens import revoke_all_tokens

		revoke_all_tokens(email, env)

	return "OK"
