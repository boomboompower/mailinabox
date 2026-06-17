#!/bin/bash

source setup/functions.sh
source /etc/mailinabox.conf # load global vars

echo "Installing Mail-in-a-Box system management daemon..."

# DEPENDENCIES

# duplicity is used to make backups of user data.
#
# virtualenv is used to isolate the Python 3 packages we
# install via pip from the system-installed packages.
#
# certbot installs EFF's certbot which we use to
# provision free TLS certificates.
apt_install_cached "management" python3-pip virtualenv certbot rsync libxml2-dev libxslt1-dev

# Create a virtualenv for the installation of Python 3 packages
# used by the management daemon.
inst_dir=/usr/local/lib/mailinabox
mkdir -p $inst_dir
venv=$inst_dir/env
if [ ! -d $venv ]; then
	# A bug specific to Ubuntu 22.04 and Python 3.10 requires
	# forcing a virtualenv directory layout option (see #2335
	# and https://github.com/pypa/virtualenv/pull/2415). In
	# our issue, reportedly installing python3-distutils didn't
	# fix the problem.)
	export DEB_PYTHON_INSTALL_LAYOUT='deb'
	hide_output virtualenv -ppython3 $venv
fi

# Which backup tool this box uses is a boxctl-time (or, later, a "mailinabox
# doctor") decision, not something switchable from the web UI - confirmed
# nothing in management/ or frontend/ exposes a runtime switch (only
# backup/actions.py and backup/status.py read BACKUP_TOOL, both purely to
# dispatch which backend's logic to run). So only the currently-selected
# tool's dependencies are installed here - not both - matching the same
# "don't install what isn't enabled" rule the rest of setup/ already follows
# for optional services.
BACKUP_TOOL="${BACKUP_TOOL:-restic}"

# Start pip install in the background if needed - it writes only to the venv and
# is fully independent of the Node.js frontend build that follows. We join before
# starting the daemon so the race window is the config-writing block below.
# BACKUP_TOOL is part of the cache key: switching it via a boxctl rerun must
# re-trigger this block even if setup/management.sh's own content hasn't
# changed, since duplicity's dependencies are only installed in that branch.
_pip_hash="$(hash_files "$PWD/setup/management.sh"):$BACKUP_TOOL"
_pip_pid=""
if needs_build "management-pip" "$_pip_hash"; then
	(
		# Upgrade pip because the Ubuntu-packaged version is out of date.
		hide_output $venv/bin/pip install --upgrade pip

		# Install Python packages used by the management daemon.
		# The first line is the packages that Josh maintains himself!
		# NOTE: email_validator is repeated in setup/questions.sh, so please keep the versions synced.
		hide_output $venv/bin/pip install --upgrade --prefer-binary \
			rtyaml "email_validator>=1.0.0" "exclusiveprocess" \
			flask dnspython python-dateutil expiringdict gunicorn \
			qrcode[pil] pyotp "fido2>=1.0" \
			"idna>=2.0.0" "cryptography>=41.0.0" psutil postfix-mta-sts-resolver \
			"passlib[bcrypt]"

		if [ "$BACKUP_TOOL" = "duplicity" ]; then
			# duplicity lives in the venv so system pip is never touched
			# (Ubuntu 24.04 blocks system pip installs via PEP 668).
			#
			# duplicity's own packaging hard-requires every cloud backend SDK
			# it supports (azure-storage-blob, boxsdk, dropbox, jottalib,
			# megatools, pyrax, python-swiftclient, google-api-python-client,
			# lxml, etc.) - none of these are optional extras, they're
			# unconditional requires_dist, even though we only ever use the
			# file/rsync/s3/b2 target types (see
			# management/services/backup/duplicity_args.py). Two of those
			# unused deps (lxml, and netifaces transitively via pyrax) need a
			# C compiler to build from source when no prebuilt wheel exists
			# yet for the running Python version - rather than install a
			# compiler just to build packages we'll never import, install
			# duplicity with --no-deps and supply only what it actually needs
			# for the backends above: fasteners + python-gettext
			# unconditionally, and boto3/b2sdk only for the s3/b2 status
			# listing code in backup/status.py (confirmed restic's own status
			# code never imports either - restic's Go binary talks to S3/B2
			# natively, no Python SDK involved).
			hide_output $venv/bin/pip install --upgrade --prefer-binary \
				fasteners python-gettext b2sdk boto3
			hide_output $venv/bin/pip install --upgrade --prefer-binary --no-deps "duplicity>=1.0"
		fi
		mark_built "management-pip" "$_pip_hash"
	) &
	_pip_pid=$!
fi

if [ "$BACKUP_TOOL" = "restic" ]; then
	# --keep-within and --json have been stable in restic for years, so any
	# version Ubuntu's apt actually ships is sufficient - no version check
	# beyond "does apt have the package at all."
	if ! command -v restic > /dev/null 2>&1; then
		if apt-cache show restic > /dev/null 2>&1; then
			apt_install_cached "restic" restic
		else
			# Fallback: apt doesn't have restic on this release. Pin a specific
			# upstream release, same pattern as setup/optional/filebrowser.sh.
			# restic publishes sha256 (not sha1) for its release assets, so
			# this uses wget_verify_sha256 rather than wget_verify. Update
			# both together when bumping the version - the hash is GitHub's
			# own computed digest for this asset, cross-checked by directly
			# downloading and re-hashing it when this pin was added, never
			# fetched alongside the binary at install time.
			RESTIC_VERSION="0.19.0"
			RESTIC_SHA256="13176fe6d89d4357947a2cd107218ab2873a5f9d8e1ac2d4cd1c8e07e6839c21"
			wget_verify_sha256 \
				"https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2" \
				"$RESTIC_SHA256" \
				/tmp/restic.bz2
			bzip2 -d -c /tmp/restic.bz2 > /usr/local/bin/restic
			chmod +x /usr/local/bin/restic
			rm -f /tmp/restic.bz2
		fi
	fi
fi

# CONFIGURATION

# Create a backup directory and a random key for encrypting backups. This
# same key doubles as RESTIC_PASSWORD when BACKUP_TOOL=restic (see
# get_passphrase() in management/services/backup/config.py) - it becomes
# that repository's permanent password. Losing or changing this file makes
# either backend's existing backups permanently unreadable.
mkdir -p "$STORAGE_ROOT/backup"
if [ ! -f "$STORAGE_ROOT/backup/secret_key.txt" ]; then
	(umask 077; openssl rand -base64 2048 > "$STORAGE_ROOT/backup/secret_key.txt")
fi


# Create an init script to start the management daemon and keep it
# running after a reboot.
# Set a long timeout since some commands (status checks, TLS provisioning) take a while.
# Note: Authentication currently breaks with more than 1 gunicorn worker.
cat > $inst_dir/start <<EOF;
#!/bin/bash
# Set character encoding flags to ensure that any non-ASCII don't cause problems.
export LANGUAGE=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LC_TYPE=en_US.UTF-8

mkdir -p /var/lib/mailinabox
tr -cd '[:xdigit:]' < /dev/urandom | head -c 32 > /var/lib/mailinabox/api.key
chmod 640 /var/lib/mailinabox/api.key

source $venv/bin/activate
export PYTHONPATH=$PWD/management
exec gunicorn -b 127.0.0.1:10222 -w 1 --timeout 630 core.wsgi:app
EOF
chmod +x $inst_dir/start
cp --remove-destination setup/conf/systemd/mailinabox.service /lib/systemd/system/mailinabox.service
hide_output systemctl daemon-reload
hide_output systemctl enable mailinabox.service

# Perform nightly tasks at 3am in system time: take a backup, run
# status checks and email the administrator any changes.
# In Docker the management container ships its own /etc/cron.d/miab-daily
# (baked into the image); skip this write to avoid double-running tasks.
if [ "${RUNTIME:-baremetal}" = "baremetal" ]; then
	minute=$((RANDOM % 60))  # avoid overloading mailinabox.email
	cat > /etc/cron.d/mailinabox-nightly << EOF;
# Mail-in-a-Box --- Do not edit / will be overwritten on update.
# Run nightly tasks: backup, status checks.
$minute 1 * * *	root	(cd $PWD && management/scripts/daily_tasks.sh)
EOF
fi

# Build the Vue admin frontend.
# Skip entirely if no source file under frontend/ has changed since the last
# build/fetch. The content hash is also the key CI publishes prebuilt builds
# under (see .github/workflows/frontend-release.yml) - it's the same
# hash_files() call in both places, so a box never needs to know which
# commit it's on, only whether frontend/'s contents match something CI has
# already built.
_fe_hash=$(hash_files "$PWD/frontend")
if needs_build "management-frontend" "$_fe_hash"; then
	FE_DIST_DIR="$PWD/frontend/dist"
	FE_TAG="frontend-$_fe_hash"
	FE_URL="https://github.com/boomboompower/mailinabox/releases/download/$FE_TAG/frontend-dist.tar.gz"
	_fe_fetched=0

	# Try the prebuilt artifact first. The sha256 sidecar here is fetched
	# from the same place as the tarball (unlike wget_verify's pinned-hash
	# pattern) - that's fine, because this artifact is published by our own
	# CI from our own source, not a third party. It's verifying transit
	# integrity, not provenance independent of the publisher.
	if curl -fsSL -o /tmp/frontend-dist.tar.gz.sha256 "$FE_URL.sha256" 2>/dev/null; then
		echo "Fetching prebuilt admin frontend ($FE_TAG)..."
		if hide_output wget -O /tmp/frontend-dist.tar.gz "$FE_URL" \
			&& echo "$(cat /tmp/frontend-dist.tar.gz.sha256)  /tmp/frontend-dist.tar.gz" | sha256sum --check --strict > /dev/null 2>&1; then
			rm -rf "$FE_DIST_DIR"
			mkdir -p "$FE_DIST_DIR"
			tar -xzf /tmp/frontend-dist.tar.gz -C "$FE_DIST_DIR"
			_fe_fetched=1
		fi
		rm -f /tmp/frontend-dist.tar.gz /tmp/frontend-dist.tar.gz.sha256
	fi

	if [ "$_fe_fetched" != "1" ]; then
		# No prebuilt build exists for this exact content hash yet (e.g. CI
		# hasn't finished, or this is an unpushed local change) - build it
		# ourselves. Node.js is only needed for this fallback - install it,
		# build, then remove it.
		echo "No prebuilt admin frontend found for this source - building from source..."
		NODE_MAJOR=24
		echo "Installing Node.js $NODE_MAJOR LTS (build-time only)..."
		curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | hide_output bash -
		apt_get_quiet install nodejs

		# Only rerun npm ci when package.json/package-lock.json themselves
		# changed - a pure source edit (the common case) must not pay the
		# cost of wiping and reinstalling node_modules from scratch.
		_fe_deps_hash=$(hash_files "$PWD/frontend/package.json" "$PWD/frontend/package-lock.json")
		if [ ! -d "$PWD/frontend/node_modules" ] || needs_build "management-frontend-deps" "$_fe_deps_hash"; then
			echo "Installing frontend dependencies..."
			(cd "$PWD/frontend" && hide_output npm ci --prefer-offline)
			mark_built "management-frontend-deps" "$_fe_deps_hash"
		fi

		echo "Building admin frontend..."
		(cd "$PWD/frontend" && hide_output npm run build)

		echo "Removing Node.js..."
		apt_get_quiet remove --purge nodejs
		apt_get_quiet autoremove
		rm -f /etc/apt/sources.list.d/nodesource.list
	fi

	mark_built "management-frontend" "$_fe_hash"
fi

# Join the background pip install before starting the daemon.
if [ -n "$_pip_pid" ]; then
	wait "$_pip_pid" || exit 1
fi

# Start the management server.
restart_service mailinabox
