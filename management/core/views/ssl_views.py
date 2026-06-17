import os

from flask import Blueprint, request

from core import utils
from core.app_context import env
from core.auth_decorators import require_admin
from core.web_helpers import json_response

bp = Blueprint("ssl", __name__, url_prefix="/ssl")
bp.before_request(require_admin)

@bp.route('/status')
def ssl_get_status():
	from services.ssl_certificates import get_certificates_to_provision
	from services.web_update import get_web_domains_info, get_web_domains

	# What domains can we provision certificates for? What unexpected problems do we have?
	provision, cant_provision = get_certificates_to_provision(env, show_valid_certs=False)

	# What's the current status of TLS certificates on all of the domain?
	domains_status = get_web_domains_info(env)
	domains_status = [
		{
			"domain": d["domain"],
			"status": d["ssl_certificate"][0],
			"text": d["ssl_certificate"][1] + (" " + cant_provision[d["domain"]] if d["domain"] in cant_provision else "")
		} for d in domains_status ]

	# Warn the user about domain names not hosted here because of other settings.
	for domain in set(get_web_domains(env, exclude_dns_elsewhere=False)) - set(get_web_domains(env)):
		domains_status.append({
			"domain": domain,
			"status": "not-applicable",
			"text": "The domain's website is hosted elsewhere.",
		})

	return json_response({
		"can_provision": utils.sort_domains(provision, env),
		"status": domains_status,
	})

@bp.route('/csr/<domain>', methods=['POST'])
def ssl_get_csr(domain):
	from services.ssl_certificates import create_csr
	ssl_private_key = os.path.join(os.path.join(env["STORAGE_ROOT"], 'ssl', 'ssl_private_key.pem'))
	return create_csr(domain, ssl_private_key, request.form.get('countrycode', ''), env)

@bp.route('/install', methods=['POST'])
def ssl_install_cert():
	from services.web_update import get_web_domains
	from services.ssl_certificates import install_cert
	domain = request.form.get('domain')
	ssl_cert = request.form.get('cert')
	ssl_chain = request.form.get('chain')
	if domain not in get_web_domains(env):
		return "Invalid domain name."
	return install_cert(domain, ssl_cert, ssl_chain, env)

@bp.route('/provision', methods=['POST'])
def ssl_provision_certs():
	from services.ssl_certificates import provision_certificates
	requests = provision_certificates(env, limit_domains=None)
	return json_response({ "requests": requests })
