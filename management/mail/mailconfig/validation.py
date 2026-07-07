# Pure validation/formatting helpers - no database access. Kept separate so
# the rules for what's a valid email/password/quota/privilege are easy to
# find and audit without wading through SQL.

import re

import idna


def validate_email(email, mode=None):
	# Checks that an email address is syntactically valid. Returns True/False.
	# An email address may contain ASCII characters only because Dovecot's
	# authentication mechanism gets confused with other character encodings.
	#
	# When mode=="user", we're checking that this can be a user account name.
	# Dovecot has tighter restrictions - letters, numbers, underscore, and
	# dash only!
	#
	# When mode=="alias", we're allowing anything that can be in a Postfix
	# alias table, i.e. omitting the local part ("@domain.tld") is OK.

	# Check the syntax of the address.
	from email_validator import validate_email as validate_email_, EmailNotValidError

	try:
		validate_email_(email, allow_smtputf8=False, check_deliverability=False, allow_empty_local=(mode == "alias"))
	except EmailNotValidError:
		return False

	if mode == 'user':
		# There are a lot of characters permitted in email addresses, but
		# Dovecot's sqlite auth driver seems to get confused if there are any
		# unusual characters in the address. Bah. Also note that since
		# the mailbox path name is based on the email address, the address
		# shouldn't be absurdly long and must not have a forward slash.
		# Our database is case sensitive (oops), which affects mail delivery
		# (Postfix always queries in lowercase?), so also only permit lowercase
		# letters.
		if len(email) > 255:
			return False
		if re.search(r'[^\@\.a-z0-9_\-]+', email):
			return False

	# Everything looks good.
	return True


def sanitize_idn_email_address(email):
	# The user may enter Unicode in an email address. Convert the domain part
	# to IDNA before going into our database. Leave the local part alone ---
	# although validate_email will reject non-ASCII characters.
	#
	# The domain name system only exists in ASCII, so it doesn't make sense
	# to store domain names in Unicode. We want to store what is meaningful
	# to the underlying protocols.
	try:
		localpart, domainpart = email.split("@")
		domainpart = idna.encode(domainpart).decode('ascii')
		return localpart + "@" + domainpart
	except (ValueError, idna.IDNAError):
		# ValueError: String does not have a single @-sign, so it is not
		# a valid email address. IDNAError: Domain part is not IDNA-valid.
		# Validation is not this function's job, so return value unchanged.
		# If there are non-ASCII characters it will be filtered out by
		# validate_email.
		return email


def prettify_idn_email_address(email):
	# This is the opposite of sanitize_idn_email_address. We store domain
	# names in IDNA in the database, but we want to show Unicode to the user.
	try:
		localpart, domainpart = email.split("@")
		domainpart = idna.decode(domainpart.encode("ascii"))
		return localpart + "@" + domainpart
	except (ValueError, UnicodeError, idna.IDNAError):
		# Failed to decode IDNA, or the email address does not have a
		# single @-sign. Should never happen.
		return email


def is_dcv_address(email):
	email = email.lower()
	return any(email.startswith((localpart + "@", localpart + "+")) for localpart in ("admin", "administrator", "postmaster", "hostmaster", "webmaster", "abuse"))


def get_domain(emailaddr, as_unicode=True):
	# Gets the domain part of an email address. Turns IDNA
	# back to Unicode for display.
	ret = emailaddr.split('@', 1)[1]
	if as_unicode:
		try:
			ret = idna.decode(ret.encode('ascii'))
		except (ValueError, UnicodeError, idna.IDNAError):
			# Looks like we have an invalid email address in
			# the database. Now is not the time to complain.
			pass
	return ret


def validate_password(pw):
	# validate password
	if pw.strip() == "":
		msg = "No password provided."
		raise ValueError(msg)
	if len(pw) < 8:
		msg = "Passwords must be at least eight characters."
		raise ValueError(msg)
	if len(pw) > 1024:
		msg = "Passwords must be at most 1024 characters."
		raise ValueError(msg)


def validate_quota(quota):
	# validate quota
	quota = quota.strip().upper()

	if quota == "":
		msg = "No quota provided."
		raise ValueError(msg)
	if re.search(r"[\s,.]", quota):
		msg = "Quotas cannot contain spaces, commas, or decimal points."
		raise ValueError(msg)
	if not re.match(r'^[\d]+[GM]?$', quota):
		msg = "Invalid quota."
		raise ValueError(msg)

	return quota


def parse_privs(value):
	return [p for p in value.split("\n") if p.strip() != ""]


def validate_privilege(priv):
	if priv != "admin":
		return (f"That's not a valid privilege ({priv}).", 400)
	return None
