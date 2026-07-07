from ..registry import check
from ..reporter import CheckFailed
from .. import utils


def _mail_domains(env):
	from mail.mailconfig import get_mail_domains

	return get_mail_domains(env)


@check("mail-domain-mx", category="mail", per_domain=_mail_domains, depends_on=["unbound"])
def check_mail_domain_mx(env, domain, report):
	import asyncio
	import postfix_mta_sts_resolver.resolver

	recommended_mx = "10 " + env['PRIMARY_HOSTNAME']

	with report.step("MX record is correct"):
		mx = utils.query_dns(domain, "MX", nxdomain=None)
		mxhost = None if mx in (None, "[timeout]") else mx.split('; ')[0].split(' ')[1]

		if mxhost is None:
			if domain == env['PRIMARY_HOSTNAME']:
				return  # no MX is fine here - the A record IS the MX fallback
			domain_a = utils.query_dns(domain, "A", nxdomain=None)
			primary_a = utils.query_dns(env['PRIMARY_HOSTNAME'], "A", nxdomain=None)
			if domain_a is not None and domain_a == primary_a:
				return  # no MX, but the A record matches the primary hostname - also fine
			raise CheckFailed(f"This domain's MX record is not set. It should be '{recommended_mx}'. Mail will not be delivered.")

		if mxhost != env['PRIMARY_HOSTNAME']:
			raise CheckFailed(f"This domain's MX record is incorrect. It is currently '{mx}' but should be '{recommended_mx}'. Mail will not be delivered.")

		if mx != recommended_mx:
			report.warn(f"MX is non-standard ('{mx}'). The recommended configuration is '{recommended_mx}'.")

	# MTA-STS only makes sense once MX is confirmed correct - same dependency
	# the original code had (it only checked MTA-STS inside the "MX is right" branch).
	with report.step("MTA-STS policy is present and correct"):
		loop = asyncio.new_event_loop()
		sts_resolver = postfix_mta_sts_resolver.resolver.STSResolver(loop=loop)
		valid, policy = loop.run_until_complete(sts_resolver.resolve(domain))
		if valid != postfix_mta_sts_resolver.resolver.STSFetchResult.VALID:
			raise CheckFailed(f"MTA-STS policy is missing: {valid}")
		if not (policy[1].get("mx") == [env['PRIMARY_HOSTNAME']] and policy[1].get("mode") == "enforce"):
			raise CheckFailed(f"MTA-STS policy is present but has unexpected settings: {policy[1]}")


@check("mail-domain-postmaster", category="mail", per_domain=_mail_domains)
def check_mail_domain_postmaster(env, domain, report):
	from mail.mailconfig import get_mail_aliases

	with report.step("Postmaster contact address exists"):
		# Not required if there's already a catch-all/domain alias for this domain.
		if "@" + domain in [address for address, *_ in get_mail_aliases(env)]:
			return
		ok, msg = utils.alias_exists_message("Postmaster contact address", "postmaster@" + domain, env)
		if not ok:
			raise CheckFailed(msg)


@check("mail-domain-blacklist", category="mail", per_domain=_mail_domains, depends_on=["unbound"])
def check_mail_domain_blacklist(env, domain, report):
	with report.step("Domain is not blacklisted by dbl.spamhaus.org"):
		dbl = utils.query_dns(domain + '.dbl.spamhaus.org', "A", nxdomain=None)
		status, message = utils.evaluate_spamhaus_code(dbl)
		if status == "error":
			raise CheckFailed(f"This domain is listed in the Spamhaus Domain Block List ({message})")
		if status == "warning" and message:
			report.warn(message)
