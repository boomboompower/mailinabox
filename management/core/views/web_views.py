from flask import Blueprint

from core.app_context import env
from core.auth_decorators import require_admin
from core.web_helpers import json_response

bp = Blueprint("web", __name__, url_prefix="/web")
bp.before_request(require_admin)

@bp.route('/domains')
def web_get_domains():
	from services.web_update import get_web_domains_info
	return json_response(get_web_domains_info(env))

@bp.route('/update', methods=['POST'])
def web_update():
	from services.web_update import do_web_update
	return do_web_update(env)
