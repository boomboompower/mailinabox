import os

import rtyaml

def get_backup_config(env, for_save=False, for_ui=False):
	backup_root = os.path.join(env["STORAGE_ROOT"], 'backup')

	# Defaults.
	config = {
		"min_age_in_days": 3,
		"target": "local",
	}

	# Merge in anything written to custom.yaml.
	try:
		with open(os.path.join(backup_root, 'custom.yaml'), encoding="utf-8") as f:
			custom_config = rtyaml.load(f)
		if not isinstance(custom_config, dict): raise ValueError # caught below
		config.update(custom_config)
	except:
		pass

	# When updating config.yaml, don't do any further processing on what we find.
	if for_save:
		return config

	# When passing this back to the admin to show the current settings, do not include
	# authentication details. The user will have to re-enter it.
	if for_ui:
		for field in ("target_user", "target_pass"):
			config.pop(field, None)

	# helper fields for the admin
	config["file_target_directory"] = os.path.join(backup_root, 'encrypted')
	config["enc_pw_file"] = os.path.join(backup_root, 'secret_key.txt')
	if config["target"] == "local":
		# Expand to the full URL.
		config["target"] = "file://" + config["file_target_directory"]
	ssh_pub_key = os.path.join('/root', '.ssh', 'id_rsa_miab.pub')
	if os.path.exists(ssh_pub_key):
		with open(ssh_pub_key, encoding="utf-8") as f:
			config["ssh_pub_key"] = f.read()

	return config

def write_backup_config(env, newconfig):
	backup_root = os.path.join(env["STORAGE_ROOT"], 'backup')
	with open(os.path.join(backup_root, 'custom.yaml'), "w", encoding="utf-8") as f:
		f.write(rtyaml.dump(newconfig))

def backup_set_custom(env, target, target_user, target_pass, min_age):
	from .status import list_target_files

	config = get_backup_config(env, for_save=True)

	# min_age must be an int
	if isinstance(min_age, str):
		min_age = int(min_age)

	config["target"] = target
	config["target_user"] = target_user
	config["target_pass"] = target_pass
	config["min_age_in_days"] = min_age

	# Validate.
	try:
		if config["target"] not in {"off", "local"}:
			# these aren't supported by the following function, which expects a full url in the target key,
			# which is what is there except when loading the config prior to saving
			list_target_files(config)
	except ValueError as e:
		return str(e)

	write_backup_config(env, config)

	return "OK"

def get_passphrase(env):
	# Get the encryption passphrase. secret_key.txt is 2048 random
	# bits base64-encoded and with line breaks every 65 characters.
	# gpg will only take the first line of text, so sanity check that
	# that line is long enough to be a reasonable passphrase. It
	# only needs to be 43 base64-characters to match AES256's key
	# length of 32 bytes.
	#
	# This same file is also used as RESTIC_PASSWORD for the restic backend
	# (see restic_args.py) - it becomes that repository's permanent password.
	# Losing or changing this file makes a restic repository permanently
	# unreadable, exactly as it already makes duplicity's GPG-encrypted
	# backups unreadable today.
	backup_root = os.path.join(env["STORAGE_ROOT"], 'backup')
	with open(os.path.join(backup_root, 'secret_key.txt'), encoding="utf-8") as f:
		passphrase = f.readline().strip()
	if len(passphrase) < 43: raise Exception("secret_key.txt's first line is too short!")

	return passphrase

def get_target_type(config):
	return config["target"].split(":")[0]
