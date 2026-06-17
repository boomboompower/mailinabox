import re

from flask import Blueprint, Response, request

from core import utils
from core.app_context import env
from core.auth_decorators import require_admin
from core.web_helpers import json_response, sanitize_error_message, validate_hostname

bp = Blueprint("dns", __name__, url_prefix="/dns")
bp.before_request(require_admin)

@bp.route('/zones')
def dns_zones():
	from services.dns_update import get_dns_zones
	return json_response([z[0] for z in get_dns_zones(env)])

@bp.route('/update', methods=['POST'])
def dns_update():
	from services.dns_update import do_dns_update
	try:
		return do_dns_update(env, force=request.form.get('force', '') == '1')
	except Exception as e:
		return (sanitize_error_message(str(e)), 500)

@bp.route('/secondary-nameserver')
def dns_get_secondary_nameserver():
	from services.dns_update import get_custom_dns_config, get_secondary_dns
	return json_response({ "hostnames": get_secondary_dns(get_custom_dns_config(env), mode=None) })

@bp.route('/secondary-nameserver', methods=['POST'])
def dns_set_secondary_nameserver():
	from services.dns_update import set_secondary_dns
	try:
		# Parse and validate each hostname to prevent command injection
		hostnames_input = request.form.get('hostnames') or ""
		hostnames = [ns.strip() for ns in re.split(r"[, ]+", hostnames_input) if ns.strip() != ""]
		# Validate each hostname
		validated_hostnames = [validate_hostname(ns) for ns in hostnames]
		return set_secondary_dns(validated_hostnames, env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/custom')
def dns_get_records(qname=None, rtype=None):
	# Get the current set of custom DNS records.
	from services.dns_update import get_custom_dns_config, get_dns_zones
	records = get_custom_dns_config(env, only_real_records=True)

	# Filter per the arguments for the more complex GET routes below.
	records = [r for r in records
		if (not qname or r[0] == qname)
		and (not rtype or r[1] == rtype) ]

	# Make a better data structure.
	records = [
        {
                "qname": r[0],
                "rtype": r[1],
                "value": r[2],
		"sort-order": { },
        } for r in records ]

	# To help with grouping by zone in qname sorting, label each record with which zone it is in.
	# There's an inconsistency in how we handle zones in get_dns_zones and in sort_domains, so
	# do this first before sorting the domains within the zones.
	zones = utils.sort_domains([z[0] for z in get_dns_zones(env)], env)
	for r in records:
		for z in zones:
			if r["qname"] == z or r["qname"].endswith("." + z):
				r["zone"] = z
				break

	# Add sorting information. The 'created' order follows the order in the YAML file on disk,
	# which tracs the order entries were added in the control panel since we append to the end.
	# The 'qname' sort order sorts by our standard domain name sort (by zone then by qname),
	# then by rtype, and last by the original order in the YAML file (since sorting by value
	# may not make sense, unless we parse IP addresses, for example).
	for i, r in enumerate(records):
		r["sort-order"]["created"] = i
	domain_sort_order = utils.sort_domains([r["qname"] for r in records], env)
	for i, r in enumerate(sorted(records, key = lambda r : (
			zones.index(r["zone"]) if r.get("zone") else 0, # record is not within a zone managed by the box
			domain_sort_order.index(r["qname"]),
			r["rtype"]))):
		r["sort-order"]["qname"] = i

	# Return.
	return json_response(records)

@bp.route('/custom/<qname>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@bp.route('/custom/<qname>/<rtype>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def dns_set_record(qname, rtype="A"):
	from services.dns_update import do_dns_update, set_custom_dns_record
	try:
		# Normalize.
		rtype = rtype.upper()

		# Read the record value from the request BODY, which must be
		# ASCII-only. Not used with GET.
		value = request.stream.read().decode("ascii", "ignore").strip()

		if request.method == "GET":
			# Get the existing records matching the qname and rtype.
			return dns_get_records(qname, rtype)

		if request.method in {"POST", "PUT"}:
			# There is a default value for A/AAAA records.
			if rtype in {"A", "AAAA"} and value == "":
				value = request.environ.get("HTTP_X_FORWARDED_FOR") # normally REMOTE_ADDR but we're behind nginx as a reverse proxy

			# Cannot add empty records.
			if value == '':
				return ("No value for the record provided.", 400)

			if request.method == "POST":
				# Add a new record (in addition to any existing records
				# for this qname-rtype pair).
				action = "add"
			elif request.method == "PUT":
				# In REST, PUT is supposed to be idempotent, so we'll
				# make this action set (replace all records for this
				# qname-rtype pair) rather than add (add a new record).
				action = "set"

		elif request.method == "DELETE":
			if value == '':
				# Delete all records for this qname-type pair.
				value = None
			else:
				# Delete just the qname-rtype-value record exactly.
				pass
			action = "remove"

		if set_custom_dns_record(qname, rtype, value, action, env):
			return do_dns_update(env) or "Something isn't right."
		return "OK"

	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/dump')
def dns_get_dump():
	from services.dns_update import build_recommended_dns
	return json_response(build_recommended_dns(env))

@bp.route('/zonefile/<zone>')
def dns_get_zonefile(zone):
	from services.dns_update import get_dns_zonefile
	return Response(get_dns_zonefile(zone, env), status=200, mimetype='text/plain')
