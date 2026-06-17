from ..registry import check
from ..reporter import CheckFailed
from .. import utils

@check("outbound-smtp", category="network")
def check_outbound_smtp(env, report):
	with report.step("Outbound mail (SMTP port 25) is not blocked"):
		# Many residential networks block outbound port 25 to prevent hijacked
		# machines from sending spam. See if we can reach one of Google's MTAs.
		_code, ret = utils.shell("check_call", ["/bin/nc", "-z", "-w5", "aspmx.l.google.com", "25"], trap=True)
		if ret != 0:
			raise CheckFailed("""Outbound mail (SMTP port 25) seems to be blocked by your network. You
				will not be able to send any mail. Many residential networks block port 25 to prevent hijacked
				machines from sending spam. A quick connection test to Google's mail server on port 25 failed.""")

# Each RBL is an independent lookup - one being listed (or timing out) must
# not prevent the others from being checked, so each gets its own check
# rather than being a step inside one bigger check.
_RBLS = ["zen.spamhaus.org", "b.barracudacentral.org", "bl.spamcop.net", "dnsbl.sorbs.net"]

def _make_rbl_check(rbl_domain, ip_type, env_key):
	def check_fn(env, report):
		with report.step(f"Not blacklisted by {rbl_domain} ({ip_type})"):
			ip_address = env[env_key]
			if ip_type == "IPv4":
				reversed_ip = ".".join(reversed(ip_address.split('.')))
			else:
				from ipaddress import IPv6Address
				reversed_ip = ".".join(reversed(IPv6Address(ip_address).exploded.split(':')))

			result = utils.query_dns(reversed_ip + '.' + rbl_domain, 'A', nxdomain=None)
			status, message = utils.evaluate_spamhaus_code(result)
			if status == "error":
				raise CheckFailed(f"The {ip_type} address {ip_address} is listed in {rbl_domain} ({message})")
			if status == "warning" and message:
				report.warn(message)
	return check_fn

for _rbl in _RBLS:
	check(f"rbl-ipv4:{_rbl}", category="network", depends_on=["unbound"])(_make_rbl_check(_rbl, "IPv4", "PUBLIC_IP"))
	check(f"rbl-ipv6:{_rbl}", category="network", depends_on=["unbound"],
		enabled=lambda env: bool(env.get('PUBLIC_IPV6')))(_make_rbl_check(_rbl, "IPv6", "PUBLIC_IPV6"))
