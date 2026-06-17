# duplicity lives in the management venv so system pip is never touched.
DUPLICITY = "/usr/local/lib/mailinabox/env/bin/duplicity"

def get_duplicity_target_url(config):
	target = config["target"]

	from .config import get_target_type
	if get_target_type(config) == "s3":
		from urllib.parse import urlsplit, urlunsplit
		target = list(urlsplit(target))

		# Although we store the S3 hostname in the target URL,
		# duplicity no longer accepts it in the target URL. The hostname in
		# the target URL must be the bucket name. The hostname is passed
		# via get_duplicity_additional_args. Move the first part of the
		# path (the bucket name) into the hostname URL component, and leave
		# the rest for the path. (The S3 region name is also stored in the
		# hostname part of the URL, in the username portion, which we also
		# have to drop here).
		target[1], target[2] = target[2].lstrip('/').split('/', 1)

		target = urlunsplit(target)

	return target

def get_duplicity_additional_args(env):
	from .config import get_backup_config, get_target_type

	config = get_backup_config(env)

	if get_target_type(config) == 'rsync':
		# Extract a port number for the ssh transport.  Duplicity accepts the
		# optional port number syntax in the target, but it doesn't appear to act
		# on it, so we set the ssh port explicitly via the duplicity options.
		from urllib.parse import urlsplit
		try:
			port = urlsplit(config["target"]).port
		except ValueError:
			port = 22
		if port is None:
			port = 22

		return [
			f"--ssh-options='-i /root/.ssh/id_rsa_miab -p {port}'",
			f"--rsync-options='-e \"/usr/bin/ssh -oStrictHostKeyChecking=no -oBatchMode=yes -p {port} -i /root/.ssh/id_rsa_miab\"'",
		]
	if get_target_type(config) == 's3':
		# See note about hostname in get_duplicity_target_url.
		# The region name, which is required by some non-AWS endpoints,
		# is saved inside the username portion of the URL.
		from urllib.parse import urlsplit, urlunsplit
		target = urlsplit(config["target"])
		endpoint_url = urlunsplit(("https", target.hostname, '', '', ''))
		args = ["--s3-endpoint-url", endpoint_url]
		if target.username: # region name is stuffed here
			args += ["--s3-region-name", target.username]
		return args

	return []

def get_duplicity_env_vars(env):
	from .config import get_backup_config, get_target_type, get_passphrase

	config = get_backup_config(env)

	dup_env = { "PASSPHRASE" : get_passphrase(env) }

	if get_target_type(config) == 's3':
		dup_env["AWS_ACCESS_KEY_ID"] = config["target_user"]
		dup_env["AWS_SECRET_ACCESS_KEY"] = config["target_pass"]
		dup_env["AWS_REQUEST_CHECKSUM_CALCULATION"] = "WHEN_REQUIRED"
		dup_env["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "WHEN_REQUIRED"

	return dup_env
