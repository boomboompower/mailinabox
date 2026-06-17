# Shared, mutable CLI configuration. Set once in __main__.py from argparse,
# read everywhere else in this package.
#
# IMPORTANT: other modules must `from . import state` and reference
# `state.VERBOSE` etc, NOT `from .state import VERBOSE`. The latter copies
# the value at import time and will never see the update __main__.py makes
# after parsing CLI args - the same pitfall as caching a mutable global by
# value across modules in any language.

import datetime
from collections import OrderedDict

LOG_FILES = (
    '/var/log/mail.log.6.gz',
    '/var/log/mail.log.5.gz',
    '/var/log/mail.log.4.gz',
    '/var/log/mail.log.3.gz',
    '/var/log/mail.log.2.gz',
    '/var/log/mail.log.1',
    '/var/log/mail.log',
)

TIME_DELTAS = OrderedDict([
    ('all', datetime.timedelta(weeks=52)),
    ('month', datetime.timedelta(weeks=4)),
    ('2weeks', datetime.timedelta(days=14)),
    ('week', datetime.timedelta(days=7)),
    ('2days', datetime.timedelta(days=2)),
    ('day', datetime.timedelta(days=1)),
    ('12hours', datetime.timedelta(hours=12)),
    ('6hours', datetime.timedelta(hours=6)),
    ('hour', datetime.timedelta(hours=1)),
    ('30min', datetime.timedelta(minutes=30)),
    ('10min', datetime.timedelta(minutes=10)),
    ('5min', datetime.timedelta(minutes=5)),
    ('min', datetime.timedelta(minutes=1)),
    ('today', datetime.datetime.now() - datetime.datetime.now().replace(hour=0, minute=0, second=0))
])

# NOW is set once at import and never reassigned - safe to treat as a constant.
NOW = datetime.datetime.now()

# Mutable - reassigned by __main__.py after parsing CLI args.
END_DATE = NOW
START_DATE = None

VERBOSE = False

# List of strings to filter users with
FILTERS = None

# What to show (with defaults)
SCAN_OUT = True  # Outgoing email
SCAN_IN = True  # Incoming email
SCAN_DOVECOT_LOGIN = True  # Dovecot Logins
SCAN_GREY = False  # Greylisted email
SCAN_BLOCKED = False  # Rejected email
