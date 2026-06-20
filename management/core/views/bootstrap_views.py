# Bootstrap endpoint. All routes here are intentionally unauthenticated.
#
# /bootstrap/status  - always available; tells the frontend whether onboarding is needed
# /bootstrap/setup   - only active while a token file exists on disk; returns 404 otherwise

from flask import Blueprint, current_app, request

from core.app_context import env
from core.web_helpers import json_response

bp = Blueprint('bootstrap', __name__)


@bp.route('/bootstrap/status')
def bootstrap_status():
    from auth.bootstrap import has_admin_users
    return json_response({'needs_bootstrap': not has_admin_users(env)})


@bp.route('/bootstrap/setup', methods=['POST'])
def bootstrap_setup():
    from auth.bootstrap import (
        has_admin_users, validate_code, consume_token, bootstrap_first_admin,
        _load_token,
    )

    # Require the XHR header consistent with all other state-changing routes.
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return ('Not found.', 404)

    # Hard gate: if admins already exist this endpoint does not exist.
    if has_admin_users(env):
        return ('Not found.', 404)

    # Token file must be present - without it the endpoint is invisible.
    if _load_token(env) is None:
        return ('No bootstrap session active. Run: boxctl bootstrap', 404)

    code = request.form.get('code', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    if not code:
        return ('Bootstrap code is required.', 400)
    if not email:
        return ('Email is required.', 400)
    if not password:
        return ('Password is required.', 400)

    ok, error = validate_code(code, env)
    if not ok:
        if error == 'expired':
            return (json_response({'error': 'expired'}), 410)
        if error in ('not_found', 'locked'):
            return (json_response({'error': error}), 429 if error == 'locked' else 404)
        remaining = int(error.split(':')[1])
        return (json_response({'error': 'invalid_code', 'attempts_remaining': remaining}), 400)

    result = bootstrap_first_admin(email, password, env)
    if isinstance(result, tuple):
        return result

    consume_token(env)
    current_app.logger.info("Bootstrap complete: first admin account created for %s", email)
    return json_response({'status': 'ok'})
