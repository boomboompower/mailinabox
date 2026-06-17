from .validation import get_domain

def get_mail_domains(env, filter_aliases=lambda alias : True, users_only=False):
	# Returns the domain names (IDNA-encoded) of all of the email addresses
	# configured on the system. If users_only is True, only return domains
	# with email addresses that correspond to user accounts. Exclude Unicode
	# forms of domain names listed in the automatic aliases table.
	from .users import get_mail_users
	from .aliases import get_mail_aliases

	domains = []
	domains.extend([get_domain(login, as_unicode=False) for login in get_mail_users(env)])
	if not users_only:
		domains.extend([get_domain(address, as_unicode=False) for address, _, _, auto in get_mail_aliases(env) if filter_aliases(address) and not auto ])
	return set(domains)
