#!/usr/local/lib/mailinabox/env/bin/python3
#
# The API can be accessed on the command line, e.g. use `curl` like so:
#    curl --user $(</var/lib/mailinabox/api.key): http://localhost:10222/mail/users
#
# During development, you can start the Mail-in-a-Box control panel
# by running this script, e.g.:
#
# service mailinabox stop # stop the system process
# DEBUG=1 management/core/daemon.py
# service mailinabox start # when done debugging, start it up again
#
# This file just assembles the app and registers each resource's routes
# (see core/views/). The actual route handlers live in core/views/*.py,
# shared auth logic in core/auth_decorators.py, and the env/auth_service
# singletons in core/app_context.py.

import contextlib
import os, os.path, sys

from flask import Flask, abort, request

# Allow running this file directly as well as importing it as part of the
# management package - both need management/ on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import utils
from core.app_context import env, auth_service

# ---------------------------------------------------------------------------
# We may deploy via a symbolic link, which confuses flask's template finding.
me = __file__
with contextlib.suppress(OSError):
	me = os.readlink(__file__)

# me is management/core/daemon.py - go up two more levels (core -> management ->
# repo root) to reach frontend/, which lives as management's sibling, not its child.
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(me)))
static_dir = os.path.abspath(os.path.join(repo_root, "frontend", "dist"))

app = Flask(__name__, static_folder=static_dir)

# Super simple CSRF protection: require a custom header on state-changing requests.
# In the future, it may be worth implementing proper CSRF tokens, or at least checking the
# Origin/Referer headers, as well as Sec-Fetch-Site (however these are only sent by modern browsers).
@app.before_request
def check_origin():
	if request.method in ('GET', 'HEAD', 'OPTIONS'):
		return
	origin = request.headers.get('Origin', '')
	# Requests with no Origin header are allowed (curl, server-to-server, local API calls).
	# Only reject requests that explicitly send a mismatched Origin header.
	if origin and origin != f'https://{env["PRIMARY_HOSTNAME"]}':
		abort(403)

@app.errorhandler(401)
def unauthorized(error):
	return auth_service.make_unauthorized_response()

# Register each resource's routes. Order matters only for the spa blueprint,
# which has to be last - see the comment in core/views/spa_views.py.
from core.views import auth_views, mail_views, dns_views, ssl_views, mfa_views, web_views, system_views, munin_views, spa_views

app.register_blueprint(auth_views.bp)
app.register_blueprint(mail_views.bp)
app.register_blueprint(dns_views.bp)
app.register_blueprint(ssl_views.bp)
app.register_blueprint(mfa_views.bp)
app.register_blueprint(web_views.bp)
app.register_blueprint(system_views.bp)
app.register_blueprint(munin_views.bp)
app.register_blueprint(spa_views.bp)

if __name__ == '__main__':
	if "DEBUG" in os.environ:
		# Turn on Flask debugging.
		app.debug = True

	if not app.debug:
		app.logger.addHandler(utils.create_syslog_handler())

	# Start the application server. Listens on 127.0.0.1 (IPv4 only).
	app.run(port=10222)
