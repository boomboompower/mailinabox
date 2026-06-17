#!/bin/bash
if [ -z "${NONINTERACTIVE:-}" ]; then
	# Install packages needed for the wizard. Python is needed for the questionary
	# TUI and email validation; dialog is no longer required.
	if [ ! -f /usr/bin/python3 ] || [ ! -f /usr/bin/pip3 ]; then
		echo "Installing packages needed for setup..."
		apt-get -q -q update
		apt_get_quiet install python3 python3-venv python3-pip || exit 1
	fi

    if [ ! -d "$BOOT_VENV" ]; then
    	hide_output python3 -m venv "$BOOT_VENV"
    fi
	hide_output "$BOOT_VENV/bin/pip" install "email_validator>=1.0.0" || exit 1
fi

# Auto-detect public IPv4 before the wizard so we can skip asking when the
# detected value is unambiguous. Runs even in NONINTERACTIVE mode so automated
# installs that omit PUBLIC_IP still get a value from the web service.
_ASK_IPV4=0
if [ -z "${PUBLIC_IP:-}" ]; then
	_GUESSED_IPV4=$(get_publicip_from_web_service 4 || true)
	if [[ -z "${DEFAULT_PUBLIC_IP:-}" && -n "$_GUESSED_IPV4" ]]; then
		# First install, auto-detected — use without asking.
		PUBLIC_IP=$_GUESSED_IPV4
	elif [[ "${DEFAULT_PUBLIC_IP:-}" == "${_GUESSED_IPV4:-}" && -n "${_GUESSED_IPV4:-}" ]]; then
		# Re-run and detected IP matches stored value — use without asking.
		PUBLIC_IP=$_GUESSED_IPV4
	else
		_ASK_IPV4=1
	fi
fi

# Same for IPv6. When both guessed and stored are empty the machine has no IPv6;
# set PUBLIC_IPV6 to empty string so later scripts don't hit an unset-variable error.
_ASK_IPV6=0
if [ -z "${PUBLIC_IPV6:-}" ]; then
	_GUESSED_IPV6=$(get_publicip_from_web_service 6 || true)
	if [[ -z "${DEFAULT_PUBLIC_IPV6:-}" && -n "$_GUESSED_IPV6" ]]; then
		PUBLIC_IPV6=$_GUESSED_IPV6
	elif [[ "${DEFAULT_PUBLIC_IPV6:-}" == "${_GUESSED_IPV6:-}" ]]; then
		# Includes the case where both are empty (no IPv6 available).
		PUBLIC_IPV6=${_GUESSED_IPV6:-}
	else
		_ASK_IPV6=1
	fi
fi

# In interactive mode, ask for any values that couldn't be auto-detected.
if [ -z "${NONINTERACTIVE:-}" ]; then
	WIZARD_ARGS=()

	# Email address (to derive hostname suggestion) and hostname.
	if [ -z "${PRIMARY_HOSTNAME:-}" ]; then
		WIZARD_ARGS+=(--ask-hostname)
		if [ -z "${DEFAULT_PRIMARY_HOSTNAME:-}" ]; then
			# First install: ask for email so we can suggest box.DOMAIN as hostname.
			WIZARD_ARGS+=(--ask-email)
			DEFAULT_DOMAIN_GUESS=$(get_default_hostname | sed -e 's/^box\.//')
			WIZARD_ARGS+=(--default-hostname "box.$DEFAULT_DOMAIN_GUESS")
		else
			WIZARD_ARGS+=(--default-hostname "${DEFAULT_PRIMARY_HOSTNAME}")
		fi
	fi

	# IPv4: ask only if still unset after auto-detection.
	if [ "$_ASK_IPV4" -eq 1 ]; then
		WIZARD_ARGS+=(--ask-ipv4
			--guessed-ipv4 "${_GUESSED_IPV4:-}"
			--default-ipv4 "${DEFAULT_PUBLIC_IP:-$(get_default_privateip 4)}")
	fi

	# IPv6: ask only if there is a mismatch between stored and detected.
	if [ "$_ASK_IPV6" -eq 1 ]; then
		WIZARD_ARGS+=(--ask-ipv6
			--guessed-ipv6 "${_GUESSED_IPV6:-}"
			--default-ipv6 "${DEFAULT_PUBLIC_IPV6:-}")
	fi

	# FileBrowser: only on first install; re-runs preserve the value from mailinabox.conf.
	if [ -z "${DEFAULT_ENABLE_FILEBROWSER:-}" ]; then
		WIZARD_ARGS+=(--ask-filebrowser)
	fi

	# Optional features (Radicale, ClamAV): ask if any optional toggle is unset.
	# Also fires on upgrades when a new optional is added to the list.
	if [ -z "${DEFAULT_ENABLE_RADICALE:-}" ] || [ -z "${DEFAULT_ENABLE_CLAMAV:-}" ]; then
		WIZARD_ARGS+=(--ask-optionals)
	fi

	# Spam filter: only on first install; re-runs preserve the value from mailinabox.conf.
	if [ -z "${DEFAULT_SPAM_FILTER:-}" ]; then
		WIZARD_ARGS+=(--ask-spam-filter)
	fi

	# Webmail client: only on first install; re-runs preserve the value from mailinabox.conf.
	if [ -z "${DEFAULT_WEBMAIL_CLIENT:-}" ]; then
		WIZARD_ARGS+=(--ask-webmail)
	fi

	# DNS mode: only on first install; re-runs preserve the value from mailinabox.conf.
	if [ -z "${DEFAULT_DNS_MODE:-}" ]; then
		WIZARD_ARGS+=(--ask-dns-mode)
	fi

	# Backup tool: only on first install; re-runs preserve the value from mailinabox.conf.
	if [ -z "${DEFAULT_BACKUP_TOOL:-}" ]; then
		WIZARD_ARGS+=(--ask-backup-tool)
	fi

	# Timezone: ask on first install (no /etc/timezone yet) or if not saved in conf.
	if [ ! -f /etc/timezone ] || [ -z "${DEFAULT_TIMEZONE:-}" ]; then
		WIZARD_ARGS+=(--ask-timezone)
	fi

	if [ ${#WIZARD_ARGS[@]} -gt 0 ]; then
		WIZARD_OUTPUT=$(mktemp /tmp/miab-wizard.XXXXXX)
		"$BOOT_VENV/bin/python3" setup/boxctl questions --output "$WIZARD_OUTPUT" "${WIZARD_ARGS[@]}" \
			|| { rm -f "$WIZARD_OUTPUT"; exit 1; }
		# shellcheck source=/dev/null
		source "$WIZARD_OUTPUT"
		rm -f "$WIZARD_OUTPUT"
	fi
fi

# Get the IP addresses of the local network interface(s) that are connected
# to the Internet. We need these when we want to have services bind only to
# the public network interfaces (not loopback, not tunnel interfaces).
if [ -z "${PRIVATE_IP:-}" ]; then
	PRIVATE_IP=$(get_default_privateip 4)
fi
if [ -z "${PRIVATE_IPV6:-}" ]; then
	PRIVATE_IPV6=$(get_default_privateip 6)
fi
if [[ -z "$PRIVATE_IP" && -z "$PRIVATE_IPV6" ]]; then
	echo
	echo "I could not determine the IP or IPv6 address of the network interface"
	echo "for connecting to the Internet. Setup must stop."
	echo
	hostname -I
	route
	echo
	exit
fi

# Automatic configuration, e.g. as used in our Vagrant configuration.
if [ "${PUBLIC_IP:-}" = "auto" ]; then
	# Use a public API to get our public IP address, or fall back to local network configuration.
	PUBLIC_IP=$(get_publicip_from_web_service 4 || get_default_privateip 4)
fi
if [ "${PUBLIC_IPV6:-}" = "auto" ]; then
	# Use a public API to get our public IPv6 address, or fall back to local network configuration.
	PUBLIC_IPV6=$(get_publicip_from_web_service 6 || get_default_privateip 6)
fi
if [ "${PRIMARY_HOSTNAME:-}" = "auto" ]; then
	PRIMARY_HOSTNAME=$(get_default_hostname)
fi

# Set STORAGE_USER and STORAGE_ROOT to default values (user-data and /home/user-data), unless
# we've already got those values from a previous run.
if [ -z "${STORAGE_USER:-}" ]; then
	STORAGE_USER=$([[ -z "${DEFAULT_STORAGE_USER:-}" ]] && echo "user-data" || echo "$DEFAULT_STORAGE_USER")
fi
if [ -z "${STORAGE_ROOT:-}" ]; then
	STORAGE_ROOT=$([[ -z "${DEFAULT_STORAGE_ROOT:-}" ]] && echo "/home/$STORAGE_USER" || echo "$DEFAULT_STORAGE_ROOT")
fi

# Show the configuration, since the user may have not entered it manually.
echo
echo "Primary Hostname: $PRIMARY_HOSTNAME"
echo "Public IP Address: $PUBLIC_IP"
if [ -n "${PUBLIC_IPV6:-}" ]; then
	echo "Public IPv6 Address: $PUBLIC_IPV6"
fi
if [ "$PRIVATE_IP" != "$PUBLIC_IP" ]; then
	echo "Private IP Address: $PRIVATE_IP"
fi
if [ "${PRIVATE_IPV6:-}" != "${PUBLIC_IPV6:-}" ]; then
	echo "Private IPv6 Address: $PRIVATE_IPV6"
fi
if [ -f /usr/bin/git ] && [ -d .git ]; then
	echo "Mail-in-a-Box Version: $(git describe --always)"
fi
echo
