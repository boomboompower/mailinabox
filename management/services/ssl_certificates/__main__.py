"""Entry point: python3 management/services/ssl_certificates [-q] [domain...]"""

import os
import sys

# When run as `python3 management/services/ssl_certificates`, __package__ is ''
# and relative imports fail - same situation setup/wizard/__main__.py solves.
if __package__ in (None, ''):
	sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
	from services.ssl_certificates.provisioning import provision_certificates_cmdline
else:
	from .provisioning import provision_certificates_cmdline

if __name__ == "__main__":
	provision_certificates_cmdline()
