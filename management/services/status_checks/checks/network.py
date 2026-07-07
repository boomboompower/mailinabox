from ..registry import check
from ..reporter import CheckFailed
from .. import utils


@check("outbound-smtp", category="network")
def check_outbound_smtp(env, report):
	from core.utils import load_settings

	relay = load_settings(env).get("smtp_relay", {})
	relay_host = (relay.get("host") or "").strip()

	if relay_host:
		relay_port = relay.get("port", 587)
		with report.step(f"Outbound relay ({relay_host}:{relay_port}) is reachable"):
			_code, ret = utils.shell("check_call", ["/bin/nc", "-z", "-w5", relay_host, str(relay_port)], trap=True)
			if ret != 0:
				raise CheckFailed(f"Cannot reach the configured SMTP relay {relay_host}:{relay_port}. Outbound mail will fail until the relay is reachable or reconfigured in System -> Outbound Mail Relay.")

		spf_include = (relay.get("spf_include") or "").strip()
		with report.step("Relay SPF include is configured"):
			if not spf_include:
				report.warn(f"SMTP relay is configured ({relay_host}) but no SPF include domain is set. Mail forwarded via this relay may fail SPF checks at recipients. Set the relay's SPF include domain in System -> Outbound Mail Relay.")
			else:
				# Verify the live SPF record actually contains the include.
				primary = env.get("PRIMARY_HOSTNAME", "")
				if not primary:
					return
				try:
					spf_records = utils.query_dns(primary, "TXT", nxdomain=None, as_list=True) or []
				except Exception:
					report.warn(f"Could not query DNS for {primary} to verify SPF record.")
					return
				spf_txt = next((r for r in spf_records if isinstance(r, str) and r.startswith("v=spf1 ")), None)
				if spf_txt is None:
					report.warn(f"No SPF record found for {primary} - relay SPF include cannot be verified.")
				elif f"include:{spf_include}" not in spf_txt:
					report.warn(f"SPF record for {primary} does not include {spf_include}. Forwarded mail may fail SPF at recipients. Add 'include:{{spf_include}}' to your SPF record, or re-run setup if using self-hosted DNS.")
	else:
		with report.step("Outbound mail (SMTP port 25) is not blocked"):
			# Many residential networks block outbound port 25 to prevent hijacked
			# machines from sending spam. See if we can reach one of Google's MTAs.
			_code, ret = utils.shell("check_call", ["/bin/nc", "-z", "-w5", "aspmx.l.google.com", "25"], trap=True)
			if ret != 0:
				raise CheckFailed("Outbound mail (SMTP port 25) seems to be blocked by your network. Configure an outbound SMTP relay in System -> Outbound Mail Relay to send mail through an external provider.")


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
	check(f"rbl-ipv6:{_rbl}", category="network", depends_on=["unbound"], enabled=lambda env: bool(env.get('PUBLIC_IPV6')))(_make_rbl_check(_rbl, "IPv6", "PUBLIC_IPV6"))
