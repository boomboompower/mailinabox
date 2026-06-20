#!/bin/bash
# Install the 'host', 'sed', and and 'nc' tools. This script is run before
# the rest of the system setup so we may not yet have things installed.
apt_get_quiet install bind9-host sed netcat-openbsd

# Stop if the PRIMARY_HOSTNAME is listed in the Spamhaus Domain Block List.
# The user might have chosen a name that was previously in use by a spammer
# and will not be able to reliably send mail. Do this after any automatic
# choices made above.
if host "$PRIMARY_HOSTNAME.dbl.spamhaus.org" > /dev/null; then
	echo
	echo "The hostname you chose '$PRIMARY_HOSTNAME' is listed in the"
	echo "Spamhaus Domain Block List. See http://www.spamhaus.org/dbl/"
	echo "and http://www.spamhaus.org/query/domain/$PRIMARY_HOSTNAME."
	echo
	echo "You will not be able to send mail using this domain name, so"
	echo "setup cannot continue."
	echo
	exit 1
fi

# Warn if the IPv4 address is listed in the ZEN Spamhaus Block List.
# A listed IP affects outbound mail reputation, but can be mitigated by
# configuring an outbound SMTP relay in the admin panel after setup.
REVERSED_IPV4=$(echo "$PUBLIC_IP" | sed "s/\([0-9]*\).\([0-9]*\).\([0-9]*\).\([0-9]*\)/\4.\3.\2.\1/")
if host "$REVERSED_IPV4.zen.spamhaus.org" > /dev/null; then
	echo
	echo "WARNING: The IP address $PUBLIC_IP is listed in the Spamhaus Block List."
	echo "See http://www.spamhaus.org/query/ip/$PUBLIC_IP."
	echo
	echo "Direct mail delivery may be unreliable from this IP. After setup"
	echo "completes, configure an outbound SMTP relay in the admin panel"
	echo "under System -> Outbound Mail Relay to route mail through a"
	echo "reputable provider instead."
	echo
fi

# Warn if we cannot make an outbound connection on port 25. Many residential
# networks and some cloud providers block outbound port 25. This is recoverable
# by configuring an outbound relay after setup.
if ! nc -z -w5 aspmx.l.google.com 25; then
	echo
	echo "WARNING: Outbound port 25 appears to be blocked on this machine."
	echo
	echo "Direct mail delivery will not work. After setup completes,"
	echo "configure an outbound SMTP relay in the admin panel under"
	echo "System -> Outbound Mail Relay to send mail through an external"
	echo "provider (SendGrid, Mailgun, Amazon SES, etc.)."
	echo
fi
