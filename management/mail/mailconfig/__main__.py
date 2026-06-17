"""Entry point: python3 management/mail/mailconfig [validate-email <email>|update]"""

import os
import sys

# When run as `python3 management/mail/mailconfig`, __package__ is '' and
# relative imports fail - same situation setup/wizard/__main__.py solves.
if __package__ in (None, ''):
	sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
	from core.utils import load_environment
	from mail.mailconfig.validation import validate_email
	from mail.mailconfig.sync import kick
else:
	from core.utils import load_environment
	from .validation import validate_email
	from .sync import kick

if __name__ == "__main__":
	if len(sys.argv) > 2 and sys.argv[1] == "validate-email":
		# Validate that we can create a Dovecot account for a given string.
		if validate_email(sys.argv[2], mode='user'):
			sys.exit(0)
		else:
			sys.exit(1)

	if len(sys.argv) > 1 and sys.argv[1] == "update":
		print(kick(load_environment()))
