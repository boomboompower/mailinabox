"""Entry point: python3 management/services/dns_update [--lint|--update]"""

import os
import sys

# When run as `python3 management/services/dns_update`, __package__ is ''
# and relative imports fail - same situation setup/wizard/__main__.py solves.
if __package__ in (None, ''):
	sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
	from core.utils import load_environment
	from services.dns_update.zones import do_dns_update
	from services.dns_update.custom_records import get_custom_dns_config, write_custom_dns_config
	from services.dns_update.recommended import build_external_dns_records
else:
	from core.utils import load_environment
	from .zones import do_dns_update
	from .custom_records import get_custom_dns_config, write_custom_dns_config
	from .recommended import build_external_dns_records

if __name__ == "__main__":
	env = load_environment()
	if sys.argv[-1] == "--lint":
		write_custom_dns_config(get_custom_dns_config(env), env)
	elif sys.argv[-1] == "--update":
		do_dns_update(env, force=True)
	else:
		for _zone, records in build_external_dns_records(env):
			for record in records:
				print(record['qname'], record['rtype'], record['value'], f"[{record['category']}]", sep="\t")
