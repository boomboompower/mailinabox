#!/bin/bash
# If there aren't any mail users yet, create one.
if [ -z "$(management/core/cli.py user admins)" ]; then
	# The output of "management/core/cli.py user" is a list of mail users. If there
	# aren't any yet, it'll be empty.

	# If we didn't ask for an email address at the start, do so now.
	if [ -z "${EMAIL_ADDR:-}" ]; then
		# In an interactive shell, ask the user for an email address.
		if [ -z "${NONINTERACTIVE:-}" ]; then
			WIZARD_OUTPUT=$(mktemp /tmp/miab-wizard.XXXXXX)
			python3 setup/boxctl \
			    firstuser \
				--output "$WIZARD_OUTPUT" \
				--default-hostname "$(get_default_hostname)" \
				|| { rm -f "$WIZARD_OUTPUT"; exit 1; }
			# shellcheck source=/dev/null
			source "$WIZARD_OUTPUT"
			rm -f "$WIZARD_OUTPUT"

		# But in a non-interactive shell, just make something up.
		# This is normally for testing.
		else
			# Use me@PRIMARY_HOSTNAME
			EMAIL_ADDR=me@$PRIMARY_HOSTNAME
			EMAIL_PW=12345678
			echo
			echo "Creating a new administrative mail account for $EMAIL_ADDR with password $EMAIL_PW."
			echo
		fi
	else
		echo
		echo "Okay. I'm about to set up $EMAIL_ADDR for you. This account will also"
		echo "have access to the box's control panel."
	fi

	# Create the user's mail account. This will ask for a password if none was given above.
	if [ -n "${EMAIL_PW:-}" ]; then
		echo "$EMAIL_PW" | management/core/cli.py user add "$EMAIL_ADDR" --stdin-password
	else
		management/core/cli.py user add "$EMAIL_ADDR"
	fi

	# Make it an admin.
	hide_output management/core/cli.py user make-admin "$EMAIL_ADDR"

	# Create an alias to which we'll direct all automatically-created administrative aliases.
	management/core/cli.py alias add "administrator@$PRIMARY_HOSTNAME" "$EMAIL_ADDR" > /dev/null
fi
