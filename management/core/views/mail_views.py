from flask import Blueprint, request

from core.app_context import env
from core.auth_decorators import require_admin
from core.web_helpers import json_response, sanitize_error_message, validate_email
from mail.mailconfig import (
	get_mail_users, get_mail_users_ex, add_mail_user, set_mail_password, remove_mail_user,
	get_mail_user_privileges, add_remove_mail_user_privilege,
	get_mail_aliases, get_mail_aliases_ex, get_mail_domains, add_mail_alias, remove_mail_alias,
	get_mail_quota, set_mail_quota,
)

bp = Blueprint("mail", __name__, url_prefix="/mail")
bp.before_request(require_admin)

@bp.route('/users')
def mail_users():
	if request.args.get("format", "") == "json":
		return json_response(get_mail_users_ex(env, with_archived=True))
	return "".join(x + "\n" for x in get_mail_users(env))

@bp.route('/users/add', methods=['POST'])
def mail_users_add():
	quota = request.form.get('quota', '0')
	try:
		email = validate_email(request.form.get('email', ''))
		return add_mail_user(email, request.form.get('password', ''), request.form.get('privileges', ''), quota, env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/quota', methods=['GET'])
def get_mail_users_quota():
	try:
		email = validate_email(request.values.get('email', ''))
		quota = get_mail_quota(email, env)

		if request.values.get('text'):
			return quota

		return json_response({
			"email": email,
			"quota": quota
		})
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/quota', methods=['POST'])
def mail_users_quota():
	try:
		email = validate_email(request.form.get('email', ''))
		return set_mail_quota(email, request.form.get('quota'), env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/password', methods=['POST'])
def mail_users_password():
	try:
		email = validate_email(request.form.get('email', ''))
		return set_mail_password(email, request.form.get('password', ''), env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/remove', methods=['POST'])
def mail_users_remove():
	try:
		email = validate_email(request.form.get('email', ''))
		return remove_mail_user(email, env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/privileges')
def mail_user_privs():
	try:
		email = validate_email(request.args.get('email', ''))
		privs = get_mail_user_privileges(email, env)
		if isinstance(privs, tuple): return privs # error
		return "\n".join(privs)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/privileges/add', methods=['POST'])
def mail_user_privs_add():
	try:
		email = validate_email(request.form.get('email', ''))
		return add_remove_mail_user_privilege(email, request.form.get('privilege', ''), "add", env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/users/privileges/remove', methods=['POST'])
def mail_user_privs_remove():
	try:
		email = validate_email(request.form.get('email', ''))
		return add_remove_mail_user_privilege(email, request.form.get('privilege', ''), "remove", env)
	except ValueError as e:
		return (sanitize_error_message(str(e)), 400)

@bp.route('/aliases')
def mail_aliases():
	if request.args.get("format", "") == "json":
		return json_response(get_mail_aliases_ex(env))
	return "".join(address + "\t" + receivers + "\t" + (senders or "") + "\n" for address, receivers, senders, auto in get_mail_aliases(env))

@bp.route('/aliases/add', methods=['POST'])
def mail_aliases_add():
	return add_mail_alias(
		request.form.get('address', ''),
		request.form.get('forwards_to', ''),
		request.form.get('permitted_senders', ''),
		env,
		update_if_exists=(request.form.get('update_if_exists', '') == '1')
		)

@bp.route('/aliases/remove', methods=['POST'])
def mail_aliases_remove():
	return remove_mail_alias(request.form.get('address', ''), env)

@bp.route('/domains')
def mail_domains():
	return "".join(x + "\n" for x in get_mail_domains(env))
