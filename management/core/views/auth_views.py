# This blueprint deliberately mixes public and protected routes - you can't
# require a login to use the login route. Routes with no decorator below are
# intentionally public; everything else uses authorized_personnel_only.
#
# PUBLIC: /login, /auth/methods, /logout, /auth/verify
# PROTECTED (admin): /whoami

from flask import Blueprint, Response, current_app, make_response, request

from core.app_context import env, auth_service
from core.auth_decorators import authorized_personnel_only
from core.web_helpers import json_response, validate_csrf, validate_email, log_failed_login

bp = Blueprint("auth", __name__)

# Create a session key by checking the username/password in the Authorization header.
@bp.route('/login', methods=["POST"])
def login():
	# Is the caller authorized?
	try:
		email, privs = auth_service.authenticate(request, env, login_only=True)
	except ValueError as e:
		if "missing-totp-token" in str(e):
			# Log this too - a correct password with missing TOTP confirms valid credentials
			# to an attacker and must be rate-limited by fail2ban the same as any bad login.
			log_failed_login(request)
			return json_response({
				"status": "missing-totp-token",
				"reason": str(e),
			})
		# Log the failed login
		log_failed_login(request)
		return json_response({
			"status": "invalid",
			"reason": str(e),
		})

	# Create a session and deliver it as an HttpOnly cookie so the key is
	# never accessible to JavaScript.
	session_key = auth_service.create_session_key(email, env, session_type='login')
	current_app.logger.info("New login session created for %s", email)

	response = make_response(json_response({
		"status": "ok",
		"email": email,
		"privileges": privs,
	}))
	response.set_cookie(
		'admin_session',
		session_key,
		httponly=True,
		secure=not current_app.debug,
		samesite='Strict',
	)
	return response

@bp.route('/auth/methods')
def auth_methods():
	# Returns the available login paths for an email address.
	# Unknown emails return the password path to avoid account enumeration.
	from auth.mfa import get_public_mfa_state, get_public_webauthn_credentials
	email_raw = request.args.get('email', '')
	try:
		email = validate_email(email_raw)
		mfa_state = get_public_mfa_state(email, env)
		webauthn_creds = get_public_webauthn_credentials(email, env)
	except ValueError:
		return json_response({"paths": ["password"]})

	has_totp = any(m["type"] == "totp" for m in mfa_state)
	has_webauthn = len(webauthn_creds) > 0

	paths = []
	if has_webauthn:
		paths.append("passkey")
	if has_totp:
		paths.append("password+totp")
	if not has_webauthn:
		paths.append("password")

	return json_response({"paths": paths})

@bp.route('/logout', methods=["POST"])
def logout():
	if 'Authorization' not in request.headers and not validate_csrf():
		return Response("Forbidden\n", status=403, mimetype='text/plain')

	if 'Authorization' in request.headers:
		try:
			email, _ = auth_service.authenticate(request, env, logout=True)
			current_app.logger.info("%s logged out", email)
		except ValueError:
			pass
	else:
		cookie_key = request.cookies.get('admin_session', '')
		if cookie_key and cookie_key in auth_service.login_sessions:
			session = auth_service.login_sessions[cookie_key]
			current_app.logger.info("%s logged out (cookie)", session.get('email', 'unknown'))
			del auth_service.login_sessions[cookie_key]

	response = make_response(json_response({"status": "ok"}))
	response.delete_cookie('admin_session', httponly=True, secure=not current_app.debug, samesite='Strict')
	return response

@bp.route('/auth/verify', methods=['POST'])
def auth_verify():
	# Internal credential verification endpoint used by Radicale, FileBrowser,
	# and any other service that needs to authenticate a mail user without going
	# through Dovecot. Not proxied by nginx - only reachable on the internal
	# network (Docker) or localhost (bare metal). No admin session is involved
	# here, by design - that's the whole point of this endpoint.
	from passlib.hash import sha512_crypt
	from mail.mailconfig import get_mail_password, get_mail_user_privileges

	email = request.form.get('email', '').strip()
	password = request.form.get('password', '')

	if not email or not password:
		return Response("Missing credentials.\n", status=400, mimetype='text/plain')

	# Constant-time: always run verify even for unknown users.
	try:
		pw_hash = get_mail_password(email, env)
		user_exists = True
	except ValueError:
		pw_hash = "{SHA512-CRYPT}$6$rounds=5000$invalidsaltvalue$" + "x" * 86
		user_exists = False

	raw_hash = pw_hash.split("}", 1)[-1] if pw_hash.startswith("{") else pw_hash
	try:
		pw_ok = sha512_crypt.verify(password, raw_hash)
	except Exception:
		pw_ok = False

	if not pw_ok or not user_exists:
		current_app.logger.warning("auth/verify failed for %s", email)
		return Response("Invalid credentials.\n", status=401, mimetype='text/plain')

	privs = get_mail_user_privileges(email, env)
	return json_response({
		"email": email,
		"privileges": privs if not isinstance(privs, tuple) else [],
	})

@bp.route('/whoami')
@authorized_personnel_only
def whoami():
	return json_response({
        "email": request.user_email,
        "privileges": request.user_privs,
    })
