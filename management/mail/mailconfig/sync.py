import idna


def get_system_administrator(env):
	return "administrator@" + env['PRIMARY_HOSTNAME']


def get_required_aliases(env):
	from .domains import get_mail_domains

	# These are the aliases that must exist.
	aliases = set()

	# The system administrator alias is required.
	aliases.add(get_system_administrator(env))

	# The hostmaster alias is exposed in the DNS SOA for each zone.
	aliases.add("hostmaster@" + env['PRIMARY_HOSTNAME'])

	# Get a list of domains we serve mail for, except ones for which the only
	# email on that domain are the required aliases or a catch-all/domain-forwarder.
	real_mail_domains = get_mail_domains(env, filter_aliases=lambda alias: not alias.startswith("postmaster@") and not alias.startswith("admin@") and not alias.startswith("abuse@") and not alias.startswith("@"))

	# Create postmaster@, admin@ and abuse@ for all domains we serve
	# mail on. postmaster@ is assumed to exist by our Postfix configuration.
	# admin@isn't anything, but it might save the user some trouble e.g. when
	# buying an SSL certificate.
	# abuse@ is part of RFC2142: https://www.ietf.org/rfc/rfc2142.txt
	for domain in real_mail_domains:
		aliases.add("postmaster@" + domain)
		aliases.add("admin@" + domain)
		aliases.add("abuse@" + domain)

	return aliases


def kick(env, mail_result=None):
	from .domains import get_mail_domains
	from .aliases import get_mail_aliases, remove_mail_alias, add_auto_aliases

	results = []

	# Include the current operation's result in output.

	if mail_result is not None:
		results.append(mail_result + "\n")

	auto_aliases = {}

	# Map required aliases to the administrator alias (which should be created manually).
	administrator = get_system_administrator(env)
	required_aliases = get_required_aliases(env)
	for alias in required_aliases:
		if alias == administrator:
			continue  # don't make an alias from the administrator to itself --- this alias must be created manually
		auto_aliases[alias] = administrator

	# Add domain maps from Unicode forms of IDNA domains to the ASCII forms stored in the alias table.
	for domain in get_mail_domains(env):
		try:
			domain_unicode = idna.decode(domain.encode("ascii"))
			if domain == domain_unicode:
				continue  # not an IDNA/Unicode domain
			auto_aliases["@" + domain_unicode] = "@" + domain
		except (ValueError, UnicodeError, idna.IDNAError):
			continue

	add_auto_aliases(auto_aliases, env)

	# Remove auto-generated postmaster/admin/abuse alises from the main aliases table.
	# They are now stored in the auto_aliases table.
	for address, forwards_to, _permitted_senders, auto in get_mail_aliases(env):
		user, domain = address.split("@")
		if user in {"postmaster", "admin", "abuse"} and address not in required_aliases and forwards_to == get_system_administrator(env) and not auto:
			remove_mail_alias(address, env, do_kick=False)
			results.append(f"removed alias {address} (was to {forwards_to}; domain no longer used for email)\n")

	# Update DNS and nginx in case any domains are added/removed.

	from services.dns_update import do_dns_update

	results.append(do_dns_update(env))

	from services.web_update import do_web_update

	results.append(do_web_update(env))

	return "".join(s for s in results if s != "")
