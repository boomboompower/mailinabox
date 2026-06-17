# Access control for views. Two ways to apply it:
#
# 1. Per-route decorator (@authorized_personnel_only / @authorized_user_only) -
#    used by auth_views.py and mfa_views.py, which deliberately mix public and
#    protected routes in the same blueprint and need per-route control.
#
# 2. Blueprint-wide guard (require_admin) - registered once via
#    bp.before_request(require_admin) on blueprints where every single route
#    needs the same admin check (mail, dns, ssl, web, system). New routes
#    added to those blueprints are protected automatically; there's no
#    per-route step to forget.
#
# Both forms call the exact same _authenticate_admin/_authenticate_user
# functions below, so there is only one place where the actual auth logic
# lives - the decorator and the blueprint guard cannot drift apart.

import json
from functools import wraps

from flask import Response, request

from core.app_context import env, auth_service
from core.web_helpers import validate_csrf, log_failed_login
from mail.mailconfig import get_mail_user_privileges

def _authenticate_admin(req):
	"""Returns (email, privs, error). error is None only on success."""
	error = None
	privs = []
	email = None

	if 'Authorization' in req.headers:
		# HTTP Basic Auth - for API clients and backward compatibility.
		try:
			email, privs = auth_service.authenticate(req, env)
		except ValueError as e:
			log_failed_login(req)
			error = str(e)
	else:
		# No Authorization header - try the HttpOnly admin session cookie.
		cookie_key = req.cookies.get('admin_session', '')
		session = auth_service.get_session_by_key_only(cookie_key, env) if cookie_key else None
		if session:
			email = session['email']
			privs = get_mail_user_privileges(email, env)
			if isinstance(privs, tuple):
				error = "Account error."
				privs = []
		else:
			error = "No authentication provided."

	if "admin" in privs:
		# CSRF protection only applies to cookie-authenticated requests.
		# Basic Auth callers (curl, API clients) cannot be targeted by CSRF
		# because the attacker cannot inject the credentials cross-origin.
		if 'Authorization' not in req.headers and not validate_csrf():
			return None, [], "Potential CSRF attack detected."
		return email, privs, None

	return email, privs, error or "You are not an administrator."

def _authenticate_user(req):
	"""Like _authenticate_admin but does not require admin privileges - any
	authenticated user passes. Used for self-service routes that operate
	exclusively on request.user_email."""
	error = None
	privs = []
	email = None

	if 'Authorization' in req.headers:
		try:
			email, privs = auth_service.authenticate(req, env)
		except ValueError as e:
			log_failed_login(req)
			error = str(e)
	else:
		cookie_key = req.cookies.get('admin_session', '')
		session = auth_service.get_session_by_key_only(cookie_key, env) if cookie_key else None
		if session:
			email = session['email']
			privs = get_mail_user_privileges(email, env)
			if isinstance(privs, tuple):
				error = "Account error."
				privs = []
		else:
			error = "No authentication provided."

	if email and not error:
		if 'Authorization' not in req.headers and not validate_csrf():
			return None, [], "Potential CSRF attack detected."
		return email, privs, None

	return email, privs, error or "Unauthorized"

def _unauthorized_response(error):
	status = 401
	headers = {
		'WWW-Authenticate': f'Basic realm="{auth_service.auth_realm}"',
		'X-Reason': error,
	}

	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		# Don't issue a 401 to an AJAX request because the user will
		# be prompted for credentials, which is not helpful.
		status = 403
		headers = None

	if request.headers.get('Accept') in {None, "", "*/*"}:
		return Response(error + "\n", status=status, mimetype='text/plain', headers=headers)
	return Response(json.dumps({
		"status": "error",
		"reason": error,
		}) + "\n", status=status, mimetype='application/json', headers=headers)

def authorized_personnel_only(viewfunc):
	"""Decorator form - use only in blueprints that mix public and protected
	routes (auth, mfa). Blueprints that are uniformly admin-only should use
	require_admin as a blueprint-wide before_request guard instead."""
	@wraps(viewfunc)
	def newview(*args, **kwargs):
		email, privs, error = _authenticate_admin(request)
		if error:
			return _unauthorized_response(error)
		request.user_email = email
		request.user_privs = privs
		return viewfunc(*args, **kwargs)
	return newview

def authorized_user_only(viewfunc):
	"""Decorator form requiring any authenticated user (not necessarily admin)."""
	@wraps(viewfunc)
	def newview(*args, **kwargs):
		email, privs, error = _authenticate_user(request)
		if error:
			return _unauthorized_response(error)
		request.user_email = email
		request.user_privs = privs
		return viewfunc(*args, **kwargs)
	return newview

def require_admin():
	"""Blueprint-wide before_request guard - register with bp.before_request(require_admin)
	on blueprints where every route needs admin privileges. Returning a Response here
	short-circuits the request before the view function runs; returning None lets it
	continue. Same check as authorized_personnel_only, just applied to the whole
	blueprint instead of one route at a time."""
	email, privs, error = _authenticate_admin(request)
	if error:
		return _unauthorized_response(error)
	request.user_email = email
	request.user_privs = privs
	return None
