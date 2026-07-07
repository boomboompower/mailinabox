from ..registry import check
from ..reporter import CheckFailed
from .. import utils


def _web_domains(env):
	from services.web_update import get_web_domains

	return get_web_domains(env)


@check("web-domain", category="web", per_domain=_web_domains, depends_on=["unbound"])
def check_web_domain(env, domain, report):
	from services.ssl_certificates import get_ssl_certificates, get_domain_ssl_files, check_certificate

	# A/AAAA is already required (and checked) for PRIMARY_HOSTNAME by the
	# primary-hostname-dns check. For other domains, it's required to serve a
	# website here at all - if it's wrong, there's no point checking the cert.
	if domain != env['PRIMARY_HOSTNAME']:
		with report.step("Domain resolves to this box's IP address"):
			ok_values = []
			for rtype, expected in (("A", env['PUBLIC_IP']), ("AAAA", env.get('PUBLIC_IPV6'))):
				if not expected:
					continue
				value = utils.query_dns(domain, rtype)
				if value != utils.normalize_ip(expected):
					raise CheckFailed(f"This domain should resolve to this box's IP address ({rtype} {expected}) to serve webmail or a website here. It currently resolves to {value}.")
				ok_values.append(value)

	with report.step("TLS certificate is signed and valid"):
		# Skip if the A record doesn't point here - covers PRIMARY_HOSTNAME, whose
		# A record isn't re-checked above (that's primary-hostname-dns's job).
		if utils.query_dns(domain, "A", None) not in {env['PUBLIC_IP'], None}:
			return

		ssl_certificates = get_ssl_certificates(env)
		tls_cert = get_domain_ssl_files(domain, ssl_certificates, env, allow_missing_cert=True)
		if tls_cert is None:
			report.warn("No TLS (SSL) certificate is installed for this domain. Visitors will get a security warning. Use the TLS Certificates page in the control panel to install one.")
			return

		cert_status, cert_status_details = check_certificate(domain, tls_cert["certificate"], tls_cert["private-key"], rounded_time=True)
		if cert_status == "OK":
			return
		if cert_status == "SELF-SIGNED":
			raise CheckFailed("The TLS (SSL) certificate for this domain is currently self-signed.")
		raise CheckFailed(f"The TLS (SSL) certificate has a problem: {cert_status}" + (f" ({cert_status_details})" if cert_status_details else ""))
