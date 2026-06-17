# The local DNS resolver (unbound) is special: if it's down, every later DNS
# lookup this box does will time out. Other checks declare depends_on=["unbound"]
# so they get skipped (not run at all) rather than hanging for minutes.

from ..registry import check
from ..reporter import CheckFailed
from .. import utils

@check("unbound", category="services")
def check_unbound(env, report):
	with report.step("Local DNS (unbound) is running"):
		service = next((s for s in utils.get_services(env) if s["name"] == "Local DNS (unbound)"), None)
		ok, msg = utils.check_service_reachable(service, env)
		if not ok:
			raise CheckFailed(msg)
