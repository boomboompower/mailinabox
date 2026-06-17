# PUBLIC (pre-login, by necessity - same reason /login is public):
#   /mfa/webauthn/authenticate/begin, /mfa/webauthn/authenticate/complete
# PROTECTED (any authenticated user, not necessarily admin - self-service):
#   everything else in this file

import json
import secrets

from flask import Blueprint, current_app, make_response, request

from core.app_context import env, auth_service
from core.auth_decorators import authorized_user_only
from core.web_helpers import json_response, sanitize_error_message, validate_email, log_failed_login
from mail.mailconfig import get_mail_user_privileges
from auth.mfa import (
	get_public_mfa_state, provision_totp, validate_totp_secret, enable_mfa, disable_mfa,
	webauthn_register_begin, webauthn_register_complete,
	webauthn_authenticate_begin, webauthn_authenticate_complete,
)

bp = Blueprint("mfa", __name__, url_prefix="/mfa")

@bp.route('/status', methods=['POST'])
@authorized_user_only
def mfa_get_status():
	# Admins may pass a 'user' form field to query another user's MFA status.
	# Non-admins are always scoped to their own account.
	is_admin = "admin" in request.user_privs
	try:
		email = validate_email(request.form.get('user', request.user_email)) if is_admin else request.user_email
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)
	try:
		resp = {
			"enabled_mfa": get_public_mfa_state(email, env)
		}
		if email == request.user_email:
			resp.update({
				"new_mfa": {
					"totp": provision_totp(email, env)
				}
			})
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)
	return json_response(resp)

@bp.route('/totp/enable', methods=['POST'])
@authorized_user_only
def totp_post_enable():
	secret = request.form.get('secret')
	token = request.form.get('token')
	label = request.form.get('label')
	if not isinstance(token, str):
		return ("Bad Input", 400)
	try:
		validate_totp_secret(secret)
		enable_mfa(request.user_email, "totp", secret, token, label, env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)
	return "OK"

@bp.route('/disable', methods=['POST'])
@authorized_user_only
def totp_post_disable():
	# Admins may pass a 'user' form field to disable MFA for another user,
	# but cannot disable MFA for other admin accounts. Non-admins are always
	# scoped to their own account.
	is_admin = "admin" in request.user_privs
	try:
		email = validate_email(request.form.get('user', request.user_email) if is_admin else request.user_email)

		# Prevent admins from disabling MFA for other admin accounts.
		# Fail-closed: if privilege lookup fails, deny rather than proceed.
		if email != request.user_email:
			target_privs = get_mail_user_privileges(email, env)
			if not isinstance(target_privs, list):
				return ("Unable to verify target account.", 400)
			if "admin" in target_privs:
				return ("Cannot disable MFA for other administrator accounts", 403)

		result = disable_mfa(email, request.form.get('mfa-id') or None, env) # convert empty string to None
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)
	if result: # success
		return "OK"
	# error
	return ("Invalid user or MFA id.", 400)

@bp.route('/webauthn/register/begin', methods=['POST'])
@authorized_user_only
def webauthn_register_begin_route():
	try:
		options, state = webauthn_register_begin(request.user_email, env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)
	nonce = secrets.token_hex(32)
	auth_service.webauthn_challenges[nonce] = {"state": state, "email": request.user_email, "type": "register"}
	return json_response({"options": options, "nonce": nonce})

@bp.route('/webauthn/register/complete', methods=['POST'])
@authorized_user_only
def webauthn_register_complete_route():
	nonce = request.form.get('nonce', '')
	name = request.form.get('name', 'My Passkey')
	credential_json = request.form.get('credential', '')
	challenge = auth_service.webauthn_challenges.get(nonce)
	if not challenge or challenge.get("type") != "register":
		return ("Invalid or expired challenge.", 400)
	del auth_service.webauthn_challenges[nonce]
	try:
		client_response = json.loads(credential_json)
		webauthn_register_complete(challenge["email"], challenge["state"], client_response, name, env)
	except Exception as e:
		return (sanitize_error_message(str(e)), 400)
	return json_response({"status": "ok"})

@bp.route('/webauthn/authenticate/begin', methods=['POST'])
def webauthn_auth_begin():
	email_raw = request.form.get('email', '')
	try:
		email = validate_email(email_raw)
		options, state = webauthn_authenticate_begin(email, env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)
	nonce = secrets.token_hex(32)
	auth_service.webauthn_challenges[nonce] = {"state": state, "email": email, "type": "authenticate"}
	return json_response({"options": options, "nonce": nonce})

@bp.route('/webauthn/authenticate/complete', methods=['POST'])
def webauthn_auth_complete():
	nonce = request.form.get('nonce', '')
	credential_json = request.form.get('credential', '')
	challenge = auth_service.webauthn_challenges.get(nonce)
	if not challenge or challenge.get("type") != "authenticate":
		return ("Invalid or expired challenge.", 400)
	del auth_service.webauthn_challenges[nonce]
	email = challenge["email"]
	try:
		client_response = json.loads(credential_json)
		webauthn_authenticate_complete(email, challenge["state"], client_response, env)
	except Exception as e:
		log_failed_login(request)
		return json_response({"status": "invalid", "reason": sanitize_error_message(str(e))})
	privs = get_mail_user_privileges(email, env)
	if isinstance(privs, tuple):
		return json_response({"status": "invalid", "reason": "Account error."})
	session_key = auth_service.create_session_key(email, env, session_type='login')
	current_app.logger.info("New passkey login session created for %s", email)
	response = make_response(json_response({"status": "ok", "email": email, "privileges": privs}))
	response.set_cookie(
		'admin_session',
		session_key,
		httponly=True,
		secure=not current_app.debug,
		samesite='Strict',
	)
	return response
