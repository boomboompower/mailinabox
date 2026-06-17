# Static file serving and the SPA catch-all. Registered last in daemon.py so
# Flask's specificity-based routing always tries every other blueprint's
# routes first - this file's '/<path:path>' is the least specific possible
# rule and must never shadow a real API route.

import json
import os

from flask import Blueprint, make_response, request

from core.app_context import env, auth_service
from mail.mailconfig import get_mail_users, get_admins, get_mail_user_privileges

bp = Blueprint("spa", __name__)

# Outlook autodiscover - must handle POST (Outlook POSTs an XML body).
# Served at both casings since clients vary.
@bp.route('/autodiscover/autodiscover.xml', methods=['GET', 'POST'])
@bp.route('/Autodiscover/Autodiscover.xml', methods=['GET', 'POST'])
def autodiscover():
    from flask import Response
    autodiscover_path = '/var/lib/mailinabox/autodiscover.xml'
    if not os.path.exists(autodiscover_path):
        return ('Autodiscover not configured.', 404)
    with open(autodiscover_path) as f:
        xml = f.read()
    return Response(xml, mimetype='application/xml')

# The Vue SPA's assets live under /static/app/assets/.
@bp.route('/static/<path:filename>')
def static_files(filename):
	from flask import current_app, send_from_directory
	return send_from_directory(current_app.static_folder, filename)

@bp.route('/', defaults={'path': ''})
@bp.route('/<path:path>')
def spa_fallback(path):
	from flask import current_app
	static_dir = current_app.static_folder
	spa_index = os.path.join(static_dir, 'app', 'index.html')
	if not os.path.exists(spa_index):
		return (
			"Admin panel not built. Run: cd frontend && npm ci && npm run build",
			503,
		)

	# Check the HttpOnly admin session cookie to determine how much to inject.
	cookie_key = request.cookies.get('admin_session', '')
	session = auth_service.get_session_by_key_only(cookie_key, env) if cookie_key else None

	if session:
		email = session['email']
		privs = get_mail_user_privileges(email, env)
		if isinstance(privs, tuple):
			privs = []

		import boto3.s3
		backup_s3_hosts = [(r, f"s3.{r}.amazonaws.com") for r in boto3.session.Session().get_available_regions('s3')]

		init_data = {
			"hostname": env['PRIMARY_HOSTNAME'],
			"authenticated": True,
			"email": email,
			"privileges": privs,
			"noUsersExist": len(get_mail_users(env)) == 0,
			"noAdminsExist": len(get_admins(env)) == 0,
			"backupS3Hosts": backup_s3_hosts,
		}
	else:
		init_data = {
			"hostname": env['PRIMARY_HOSTNAME'],
			"authenticated": False,
		}

	with open(spa_index, encoding='utf-8') as f:
		html = f.read()

	# Escape HTML-special chars so a value containing </script> can never break
	# out of the script tag. This produces valid JSON (unicode escapes are legal).
	config_json = (
		json.dumps(init_data)
		.replace('&', '\\u0026')
		.replace('<', '\\u003c')
		.replace('>', '\\u003e')
	)
	html = html.replace(
		'<script type="application/json" id="__INIT__"></script>',
		f'<script type="application/json" id="__INIT__">{config_json}</script>',
		1,
	)
	response = make_response(html)
	response.headers['Cache-Control'] = 'no-store'
	response.headers['Vary'] = 'Cookie'
	return response
