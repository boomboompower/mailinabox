"""
Cypht webmail.

Steps:
  fetch     - download, apply patches, run composer install, deploy to target
  dirs      - create STORAGE_ROOT/cypht/{users,attachments}
  auth-log  - create /var/log/cypht-auth.log with correct ownership for fail2ban
  logrotate - write logrotate config for auth log
  config    - write .env and run config_gen.php (every run)
"""

import os
import subprocess

from doit.tools import config_changed

from ... import artifacts
from ...component import Component

# ── Component declaration ─────────────────────────────────────────────────────

COMPONENT = Component(
	name="cypht",
	packages=[
		"php-cli",
		"php-fpm",
		"php-curl",
		"php-mbstring",
		"php-zip",
		"php-json",
		"php-intl",
		"php-xml",
		"php-soap",
		"php-gd",
		"ca-certificates",
		"composer",
		"unzip",
	],
	services=[],  # runs under PHP-FPM, no own service
	docker_services=[],
	enabled=lambda env: env.get("WEBMAIL_CLIENT", "oxi") == "cypht",
)

# Pinned to a commit rather than a release tag so merged upstream fixes land
# without waiting for a release. Update CYPHT_COMMIT + CYPHT_SHA256 together.
CYPHT_COMMIT = "17115f4cb27ef990fb517cce7fd6798f6a4f805d"
CYPHT_SHA256 = "fc69f09da8bf3c46363648b0144d8f0bfa5b3ded74432a78e979ec4907c97c89"
CYPHT_URL = f"https://github.com/cypht-org/cypht/archive/{CYPHT_COMMIT}.tar.gz"

_CYPHT_SRC = "/usr/local/src/cypht"
_CYPHT_TARGET = "/usr/local/share/cypht"
_CYPHT_STAMP = "/usr/local/share/cypht.version"

_BASE_MODULES = "core,contacts,local_contacts,feeds,imap,smtp,account,idle_timer,desktop_notifications,themes,nux,profiles,imap_folders,sievefilters,tags,history,scheduled_sends"


# ── Tasks ─────────────────────────────────────────────────────────────────────


def make_tasks(env: dict, runtime: str) -> list[dict]:
	storage_root = env["STORAGE_ROOT"]
	enable_radicale = env.get("ENABLE_RADICALE", "true").lower() != "false"

	return [
		{
			"name": "fetch",
			# Stamp includes fn_stamp of _fetch so patch changes force redeploy
			# even when the commit pin hasn't changed.
			"targets": [_CYPHT_STAMP],
			"uptodate": [config_changed(f"{CYPHT_COMMIT}:{artifacts.fn_stamp(_fetch)}")],
			"actions": [(_fetch,)],
		},
		{
			"name": "dirs",
			"uptodate": [config_changed(f"{storage_root}:{artifacts.fn_stamp(_dirs)}")],
			"actions": [(_dirs, [storage_root])],
		},
		{
			"name": "auth-log",
			"uptodate": [config_changed(artifacts.fn_stamp(_auth_log))],
			"actions": [(_auth_log,)],
		},
		{
			"name": "logrotate",
			"uptodate": [config_changed(artifacts.fn_stamp(_logrotate))],
			"actions": [(_logrotate,)],
		},
		{
			"name": "config",
			"targets": [f"{_CYPHT_TARGET}/.env"],
			# Re-runs when env vars or module list changes - config_gen.php re-reads .env.
			"uptodate": [config_changed(f"{storage_root}:{enable_radicale}:{artifacts.fn_stamp(_config)}")],
			"task_dep": ["cypht:fetch", "cypht:dirs"],
			"actions": [(_config, [storage_root, enable_radicale])],
		},
	]


# ── Action functions ──────────────────────────────────────────────────────────


def _fetch() -> None:
	"""Download, verify, patch, composer install, and deploy Cypht.

	Patches applied (all idempotent guards so re-runs are safe):
	- index.php APP_PATH: blank -> absolute path (fixes .env loading under PHP-FPM)
	- carddav_contacts: auto-populate CardDAV creds on login (modules.php + setup.php)
	- carddav_contacts: hide credentials form in SINGLE_SERVER_MODE
	- core/imap/smtp/nux: hide server-adding wizard in SINGLE_SERVER_MODE
	- imap: hide EWS server config in SINGLE_SERVER_MODE
	- carddav_contacts: rename 'Add Carddav' button to 'Add Contact'
	- lib/environment.php: fall back to $_ENV for Symfony Dotenv 6.x compat
	- core: log failed logins with real client IP for fail2ban (handler_modules + setup)
	"""
	import re
	import shutil

	tmp = "/tmp/cypht.tar.gz"
	try:
		subprocess.run(["wget", "-q", "-O", tmp, CYPHT_URL], check=True)
		result = subprocess.run(
			["sha256sum", "--check", "--strict"],
			input=f"{CYPHT_SHA256}  {tmp}",
			text=True,
			capture_output=True,
			check=False,
		)
		if result.returncode != 0:
			raise RuntimeError(f"Cypht SHA256 mismatch: {result.stderr.strip()}")

		shutil.rmtree(_CYPHT_SRC, ignore_errors=True)
		os.makedirs(_CYPHT_SRC, exist_ok=True)
		subprocess.run(["tar", "-xzf", tmp, "--strip-components=1", "-C", _CYPHT_SRC], check=True)
	finally:
		if os.path.exists(tmp):
			os.unlink(tmp)

	# Install vendor dependencies.
	env_copy = os.environ.copy()
	env_copy["COMPOSER_ALLOW_SUPERUSER"] = "1"
	subprocess.run(
		["composer", "install", "--no-dev", "--working-dir", _CYPHT_SRC],
		check=True,
		env=env_copy,
		capture_output=True,
	)

	os.makedirs(_CYPHT_TARGET, exist_ok=True)
	subprocess.run(
		["rsync", "-a", "--delete", _CYPHT_SRC + "/", _CYPHT_TARGET + "/"],
		check=True,
		capture_output=True,
	)

	# Patch index.php: fix APP_PATH so PHP-FPM can find .env regardless of CWD.
	_patch_file(
		f"{_CYPHT_TARGET}/index.php",
		"define('APP_PATH', '');",
		"define('APP_PATH', dirname(__FILE__).'/');",
	)

	# Patch carddav_contacts: auto-populate credentials on login.
	_patch_carddav_autofill(
		f"{_CYPHT_TARGET}/modules/carddav_contacts/modules.php",
		f"{_CYPHT_TARGET}/modules/carddav_contacts/setup.php",
	)

	# Patch carddav_contacts: hide credentials form in single-server mode.
	_patch_single_server_carddav(f"{_CYPHT_TARGET}/modules/carddav_contacts/modules.php")

	# Patch server-adding wizard modules to check single_server_mode.
	_patch_single_server_wizard(_CYPHT_TARGET, re)

	# Patch EWS output module.
	_patch_single_server_ews(f"{_CYPHT_TARGET}/modules/imap/output_modules.php")

	# Rename 'Add Carddav' to 'Add Contact'.
	_patch_file(
		f"{_CYPHT_TARGET}/modules/carddav_contacts/modules.php",
		"trans('Add Carddav')",
		"trans('Add Contact')",
	)

	# Fix env() for Symfony Dotenv 6.x: fall back to $_ENV if getenv returns false.
	_patch_env_function(f"{_CYPHT_TARGET}/lib/environment.php", re)

	# Add failed-login logging handler for fail2ban (writes real client IP).
	_patch_failed_login_logger(
		f"{_CYPHT_TARGET}/modules/core/handler_modules.php",
		f"{_CYPHT_TARGET}/modules/core/setup.php",
	)

	subprocess.run(["chown", "-R", "root:root", _CYPHT_TARGET], check=True)

	with open(_CYPHT_STAMP, "w") as fh:
		fh.write(CYPHT_COMMIT)


def _patch_file(path: str, old: str, new: str) -> None:
	"""Replace old with new in path (once, idempotent)."""
	with open(path, encoding="utf-8") as fh:
		content = fh.read()
	if new in content:
		return
	if old not in content:
		return
	with open(path, "w", encoding="utf-8") as fh:
		fh.write(content.replace(old, new, 1))


def _patch_carddav_autofill(modules_php: str, setup_php: str) -> None:
	"""Inject handler that auto-populates CardDAV credentials from login credentials."""
	handler = r"""
class Hm_Handler_auto_populate_carddav_credentials extends Hm_Handler_Module {
    public function process() {
        list($success, $form) = $this->process_form(array("username", "password"));
        if (!$success || !$this->session->is_active()) {
            return;
        }
        $existing = $this->user_config->get("carddav_contacts_auth_setting", array());
        $servers  = config("carddav");
        $changed  = false;
        foreach ($servers as $name => $details) {
            if (!isset($existing[$name]["user"]) || empty($existing[$name]["user"])) {
                $existing[$name] = array("user" => rtrim($form["username"]), "pass" => $form["password"]);
                $changed = true;
            }
        }
        if ($changed) {
            $this->user_config->set("carddav_contacts_auth_setting", $existing);
            $this->user_config->save(rtrim($form["username"]), $form["password"]);
        }
    }
}
"""
	hook = "add_handler('home', 'auto_populate_carddav_credentials', true, 'carddav_contacts', 'load_user_data', 'after');"
	with open(modules_php, encoding="utf-8") as fh:
		c = fh.read()
	if "auto_populate_carddav_credentials" not in c:
		with open(modules_php, "w", encoding="utf-8") as fh:
			fh.write(c.rstrip() + "\n" + handler + "\n")

	with open(setup_php, encoding="utf-8") as fh:
		c = fh.read()
	if "auto_populate_carddav_credentials" not in c:
		with open(setup_php, "w", encoding="utf-8") as fh:
			fh.write(c.replace("handler_source(", hook + "\n" + "handler_source(", 1))


def _patch_single_server_carddav(modules_php: str) -> None:
	"""Hide CardDAV credentials form when SINGLE_SERVER_MODE is active."""
	needle = "protected function output() {\n        $settings = $this->get('carddav_settings'"
	guard = "protected function output() {\n        if (filter_var(env('SINGLE_SERVER_MODE', 'false'), FILTER_VALIDATE_BOOLEAN)) { return ''; }\n        $settings = $this->get('carddav_settings'"
	with open(modules_php, encoding="utf-8") as fh:
		c = fh.read()
	if needle in c and guard not in c:
		with open(modules_php, "w", encoding="utf-8") as fh:
			fh.write(c.replace(needle, guard, 1))


def _patch_single_server_wizard(target: str, re) -> None:
	"""Inject single_server_mode guard into server-adding wizard output modules.

	The server-adding wizard (stepper) is split across many output modules: the
	container, form steps, end-parts, and the NUX 'Add a new server' button.
	Each module must independently check single_server_mode because the module
	system concatenates HTML strings - returning '' from the container but not
	the children leaves the child HTML orphaned on the page.
	"""
	guard_php = "if ($this->get('single_server_mode')) { return ''; }"
	patches = [
		(
			f"{target}/modules/core/output_modules.php",
			[
				"Hm_Output_server_config_stepper",
				"Hm_Output_server_config_stepper_end_part",
				"Hm_Output_server_config_stepper_accordion_end_part",
			],
		),
		(
			f"{target}/modules/imap/output_modules.php",
			[
				"Hm_Output_stepper_setup_server_jmap",
				"Hm_Output_stepper_setup_server_imap",
				"Hm_Output_stepper_setup_server_jmap_imap_common",
			],
		),
		(
			f"{target}/modules/smtp/modules.php",
			[
				"Hm_Output_stepper_setup_server_smtp",
			],
		),
		(
			f"{target}/modules/nux/modules.php",
			[
				"Hm_Output_quick_add_multiple_section",
			],
		),
	]
	for fpath, classes in patches:
		with open(fpath, encoding="utf-8") as fh:
			c = fh.read()
		for cls in classes:
			if guard_php not in c:
				pat = (
					r"(class " + re.escape(cls) + r"\s+extends\s+Hm_Output_Module\s*\{.*?"
					r"protected\s+function\s+output\s*\(\s*\)\s*\{)"
				)
				c = re.sub(
					pat,
					lambda m: m.group(0) + "\n        " + guard_php,
					c,
					flags=re.DOTALL,
					count=1,
				)
		with open(fpath, "w", encoding="utf-8") as fh:
			fh.write(c)


def _patch_single_server_ews(output_modules_php: str) -> None:
	"""Hide EWS server config in single-server mode (upstream omits the check)."""
	needle = "class Hm_Output_server_config_ews extends Hm_Output_Module {\n    protected function output() {\n        $hasEWSActivated"
	guard = "class Hm_Output_server_config_ews extends Hm_Output_Module {\n    protected function output() {\n        if ($this->get('single_server_mode')) { return ''; }\n        $hasEWSActivated"
	with open(output_modules_php, encoding="utf-8") as fh:
		c = fh.read()
	if needle in c and guard not in c:
		with open(output_modules_php, "w", encoding="utf-8") as fh:
			fh.write(c.replace(needle, guard, 1))


def _patch_env_function(environment_php: str, re) -> None:
	"""Make env() fall back to $_ENV for Symfony Dotenv 6.x compatibility.

	Dotenv 6.x deprecated putenv() - values land in $_ENV only. Cypht's env()
	uses getenv() which reads the process env and sees nothing without this fix.
	"""
	with open(environment_php, encoding="utf-8") as fh:
		c = fh.read()
	if "$_ENV" in c:
		return
	fixed = "    function env($key, $default = null) {\n        $v = getenv($key);\n        if ($v !== false) return $v;\n        return isset($_ENV[$key]) ? $_ENV[$key] : $default;\n    }"
	c = re.sub(
		r"function env\(\$key,\s*\$default\s*=\s*null\)\s*\{[^}]+\}",
		fixed.lstrip(),
		c,
	)
	with open(environment_php, "w", encoding="utf-8") as fh:
		fh.write(c)


def _patch_failed_login_logger(handler_modules_php: str, setup_php: str) -> None:
	"""Add handler that logs failed logins with real client IP for fail2ban.

	Without this, Cypht's IMAP auth makes Dovecot see 127.0.0.1 as the source,
	which is whitelisted and never banned.
	"""
	handler = r"""
class Hm_Handler_log_failed_login extends Hm_Handler_Module {
    public function process() {
        list($success, $form) = $this->process_form(array('username', 'password'));
        if (!$success) { return; }
        if ($this->session->is_active()) { return; }
        $ip = isset($this->request->server['REMOTE_ADDR']) ? $this->request->server['REMOTE_ADDR'] : 'unknown';
        $raw = isset($form['username']) ? rtrim($form['username']) : 'unknown';
        $user = substr(preg_replace('/[^\x20-\x7E]/', '', $raw), 0, 254);
        $line = '[' . date('Y-m-d H:i:s') . '] Failed login for ' . $user . ' from ' . $ip . PHP_EOL;
        @file_put_contents('/var/log/cypht-auth.log', $line, FILE_APPEND | LOCK_EX);
    }
}
"""
	hook = "add_handler('home', 'log_failed_login', false, 'core', 'login', 'after');"
	anchor = "add_handler('home', 'check_missing_passwords'"

	with open(handler_modules_php, encoding="utf-8") as fh:
		c = fh.read()
	if "log_failed_login" not in c:
		with open(handler_modules_php, "w", encoding="utf-8") as fh:
			fh.write(c.rstrip() + "\n" + handler + "\n")

	with open(setup_php, encoding="utf-8") as fh:
		c = fh.read()
	if "log_failed_login" not in c:
		with open(setup_php, "w", encoding="utf-8") as fh:
			fh.write(c.replace(anchor, hook + "\n" + anchor, 1))


def _dirs(storage_root: str) -> None:
	"""Create Cypht data directories. chown -R only on first creation."""
	data_dir = os.path.join(storage_root, "cypht")
	if not os.path.isdir(data_dir):
		os.makedirs(os.path.join(data_dir, "users"), exist_ok=True)
		os.makedirs(os.path.join(data_dir, "attachments"), exist_ok=True)
		subprocess.run(["chown", "-R", "www-data:www-data", data_dir], check=True)
		subprocess.run(["chmod", "750", data_dir], check=True)
	else:
		os.makedirs(os.path.join(data_dir, "users"), exist_ok=True)
		os.makedirs(os.path.join(data_dir, "attachments"), exist_ok=True)


def _auth_log() -> None:
	"""Create /var/log/cypht-auth.log with www-data:adm ownership for fail2ban."""
	log = "/var/log/cypht-auth.log"
	if not os.path.exists(log):
		open(log, "a").close()
	subprocess.run(["chown", "www-data:adm", log], check=True)
	subprocess.run(["chmod", "640", log], check=True)


def _logrotate() -> None:
	"""Write logrotate config for the Cypht auth log."""
	artifacts.write_file(
		"/etc/logrotate.d/cypht-auth",
		"/var/log/cypht-auth.log {\n    daily\n    rotate 14\n    compress\n    delaycompress\n    missingok\n    notifempty\n    create 640 www-data adm\n}\n",
	)


def _config(storage_root: str, enable_radicale: bool) -> None:
	"""Write .env and run config_gen.php to produce config/dynamic.php.

	AUTH_TYPE=IMAP authenticates directly against Dovecot on 127.0.0.1:143 -
	no separate user database needed.
	SINGLE_SERVER_MODE prevents users from adding external accounts.
	The carddav_contacts module is included only when ENABLE_RADICALE=true;
	local_contacts is dropped to avoid two contact stores in that case.

	config_gen.php must run after every deploy and after .env changes since it
	reads .env and encodes the active module list into config/dynamic.php.
	"""
	data_dir = os.path.join(storage_root, "cypht")

	modules = _BASE_MODULES
	if enable_radicale:
		# Drop local_contacts (avoid two contact stores), add carddav_contacts.
		modules = modules.replace("local_contacts,", "")
		modules += ",carddav_contacts"

	artifacts.write_file(
		f"{_CYPHT_TARGET}/.env",
		"APP_NAME=Cypht\n"
		"\n"
		"SESSION_TYPE=PHP\n"
		"AUTH_TYPE=IMAP\n"
		"\n"
		"IMAP_AUTH_NAME=MIAB\n"
		"IMAP_AUTH_SERVER=127.0.0.1\n"
		"IMAP_AUTH_PORT=143\n"
		"IMAP_AUTH_TLS=false\n"
		"\n"
		"DEFAULT_SMTP_SERVER=127.0.0.1\n"
		"DEFAULT_SMTP_PORT=587\n"
		"DEFAULT_SMTP_TLS=STARTTLS\n"
		"\n"
		"USER_CONFIG_TYPE=file\n"
		f"USER_SETTINGS_DIR={data_dir}/users\n"
		f"ATTACHMENT_DIR={data_dir}/attachments\n"
		"\n"
		"SINGLE_SERVER_MODE=true\n"
		"DYNAMIC_HOST=false\n"
		"DYNAMIC_USER=false\n"
		"\n"
		"DEFAULT_EMAIL_DOMAIN=\n"
		"ALLOW_EXTERNAL_IMAGE_SOURCES=false\n"
		"ALLOW_LONG_SESSION=false\n"
		"\n"
		"ENABLE_DEBUG=false\n"
		"LOG_LEVEL=WARNING\n"
		"LOG_FILE=\n"
		"\n"
		"CARD_DAV_SERVER=http://127.0.0.1:5232\n"
		"\n"
		f"CYPHT_MODULES={modules}\n",
		mode=0o640,
	)
	subprocess.run(["chown", "root:www-data", f"{_CYPHT_TARGET}/.env"], check=True)

	result = subprocess.run(
		["php", f"{_CYPHT_TARGET}/scripts/config_gen.php"],
		check=False,
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		raise RuntimeError(f"Cypht config_gen.php failed:\n{result.stdout}{result.stderr}")

	subprocess.run(["chown", "-R", "root:root", _CYPHT_TARGET], check=True)
	subprocess.run(
		["chown", "-R", "root:www-data", f"{_CYPHT_TARGET}/.env", f"{_CYPHT_TARGET}/config"],
		check=True,
	)
	subprocess.run(
		["chown", "-R", "www-data:www-data", f"{_CYPHT_TARGET}/assets"],
		check=True,
	)
	subprocess.run(["chmod", "-R", "755", _CYPHT_TARGET], check=True)
	subprocess.run(["chmod", "640", f"{_CYPHT_TARGET}/.env"], check=True)
	dynamic_php = f"{_CYPHT_TARGET}/config/dynamic.php"
	if os.path.exists(dynamic_php):
		subprocess.run(["chmod", "644", dynamic_php], check=True)
