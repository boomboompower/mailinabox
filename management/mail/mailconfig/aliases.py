import operator
import re
import sqlite3

from core import utils
from .database import open_database
from .validation import (
	validate_email, sanitize_idn_email_address, prettify_idn_email_address,
	is_dcv_address, get_domain,
)

def get_mail_aliases(env):
	# Returns a sorted list of tuples of (address, forward-tos, permitted-senders, auto).
	conn, c = open_database(env, with_connection=True)
	c.execute('SELECT source, destination, permitted_senders, 0 as auto FROM aliases UNION SELECT source, destination, permitted_senders, 1 as auto FROM auto_aliases')
	aliases = { row[0]: row for row in c.fetchall() } # make dict
	conn.close()

	# put in a canonical order: sort by domain, then by email address lexicographically
	return [ aliases[address] for address in utils.sort_email_addresses(aliases.keys(), env) ]

def get_mail_aliases_ex(env):
	# Returns a complex data structure of all mail aliases, similar
	# to get_mail_users_ex.
	#
	# [
	#   {
	#     domain: "domain.tld",
	#     alias: [
	#       {
	#         address: "name@domain.tld", # IDNA-encoded
	#         address_display: "name@domain.tld", # full Unicode
	#         forwards_to: ["user1@domain.com", "receiver-only1@domain.com", ...],
	#         permitted_senders: ["user1@domain.com", "sender-only1@domain.com", ...] OR null,
	#         auto: True|False
	#       },
	#       ...
	#     ]
	#   },
	#   ...
	# ]

	domains = {}
	for address, forwards_to, permitted_senders, auto in get_mail_aliases(env):
		# skip auto domain maps since these are not informative in the control panel's aliases list
		if auto and address.startswith("@"): continue

		# get alias info
		domain = get_domain(address)

		# add to list
		if domain not in domains:
			domains[domain] = {
				"domain": domain,
				"aliases": [],
			}
		domains[domain]["aliases"].append({
			"address": address,
			"address_display": prettify_idn_email_address(address),
			"forwards_to": [prettify_idn_email_address(r.strip()) for r in forwards_to.split(",")] if forwards_to else [],
			"permitted_senders": [prettify_idn_email_address(s.strip()) for s in permitted_senders.split(",")] if permitted_senders is not None else None,
			"auto": bool(auto),
		})

	# Sort domains.
	domains = [domains[domain] for domain in utils.sort_domains(domains.keys(), env)]

	# Sort aliases within each domain first by required-ness then lexicographically by address.
	for domain in domains:
		domain["aliases"].sort(key = operator.itemgetter("auto", "address"))
	return domains

def add_mail_alias(address, forwards_to, permitted_senders, env, update_if_exists=False, do_kick=True):
	from .users import get_mail_users, get_mail_user_privileges

	# convert Unicode domain to IDNA
	address = sanitize_idn_email_address(address)

	# Our database is case sensitive (oops), which affects mail delivery
	# (Postfix always queries in lowercase?), so force lowercase.
	address = address.lower()

	# validate address
	address = address.strip()
	if address == "":
		return ("No email address provided.", 400)
	if not validate_email(address, mode='alias'):
		return (f"Invalid email address ({address}).", 400)

	# validate forwards_to
	validated_forwards_to = []
	forwards_to = forwards_to.strip()

	# extra checks for email addresses used in domain control validation
	is_dcv_source = is_dcv_address(address)

	# Postfix allows a single @domain.tld as the destination, which means
	# the local part on the address is preserved in the rewrite. We must
	# try to convert Unicode to IDNA first before validating that it's a
	# legitimate alias address. Don't allow this sort of rewriting for
	# DCV source addresses.
	r1 = sanitize_idn_email_address(forwards_to)
	if validate_email(r1, mode='alias') and not is_dcv_source:
		validated_forwards_to.append(r1)

	else:
		# Parse comma and \n-separated destination emails & validate. In this
		# case, the forwards_to must be complete email addresses.
		for line in forwards_to.split("\n"):
			for email in line.split(","):
				email = email.strip()
				if email == "": continue
				email = sanitize_idn_email_address(email) # Unicode => IDNA
				# Strip any +tag from email alias and check privileges
				privileged_email = re.sub(r"(?=\+)[^@]*(?=@)",'',email)
				if not validate_email(email):
					return (f"Invalid receiver email address ({email}).", 400)
				if is_dcv_source and not is_dcv_address(email) and "admin" not in get_mail_user_privileges(privileged_email, env, empty_on_error=True):
					# Make domain control validation hijacking a little harder to mess up by
					# requiring aliases for email addresses typically used in DCV to forward
					# only to accounts that are administrators on this system.
					return ("This alias can only have administrators of this system as destinations because the address is frequently used for domain control validation.", 400)
				validated_forwards_to.append(email)

	# validate permitted_senders
	valid_logins = get_mail_users(env)
	validated_permitted_senders = []
	permitted_senders = permitted_senders.strip()

	# Parse comma and \n-separated sender logins & validate. The permitted_senders must be
	# valid usernames.
	for line in permitted_senders.split("\n"):
		for login in line.split(","):
			login = login.strip()
			if login == "": continue
			if login not in valid_logins:
				return (f"Invalid permitted sender: {login} is not a user on this system.", 400)
			validated_permitted_senders.append(login)

	# Make sure the alias has either a forwards_to or a permitted_sender.
	if len(validated_forwards_to) + len(validated_permitted_senders) == 0:
		return ("The alias must either forward to an address or have a permitted sender.", 400)

	# save to db

	forwards_to = ",".join(validated_forwards_to)

	permitted_senders = None if len(validated_permitted_senders) == 0 else ",".join(validated_permitted_senders)

	conn, c = open_database(env, with_connection=True)
	try:
		c.execute("INSERT INTO aliases (source, destination, permitted_senders) VALUES (?, ?, ?)", (address, forwards_to, permitted_senders))
		return_status = "alias added"
	except sqlite3.IntegrityError:
		if not update_if_exists:
			conn.close()
			return (f"Alias already exists ({address}).", 400)
		c.execute("UPDATE aliases SET destination = ?, permitted_senders = ? WHERE source = ?", (forwards_to, permitted_senders, address))
		return_status = "alias updated"

	conn.commit()
	conn.close()

	if do_kick:
		# Update things in case any new domains are added.
		from .sync import kick
		return kick(env, return_status)
	return None

def remove_mail_alias(address, env, do_kick=True):
	# convert Unicode domain to IDNA
	address = sanitize_idn_email_address(address)

	# remove
	conn, c = open_database(env, with_connection=True)
	c.execute("DELETE FROM aliases WHERE source=?", (address,))
	if c.rowcount != 1:
		conn.close()
		return (f"That's not an alias ({address}).", 400)
	conn.commit()
	conn.close()

	if do_kick:
		# Update things in case any domains are removed.
		from .sync import kick
		return kick(env, "alias removed")
	return None

def add_auto_aliases(aliases, env):
	conn, c = open_database(env, with_connection=True)
	c.execute("DELETE FROM auto_aliases")
	for source, destination in aliases.items():
		c.execute("INSERT INTO auto_aliases (source, destination) VALUES (?, ?)", (source, destination))
	conn.commit()
	conn.close()
