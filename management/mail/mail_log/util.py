import argparse

import dateutil.parser

from . import state

def readline(filename):
    """ A generator that returns the lines of a file
    """
    with open(filename, errors='replace', encoding='utf-8') as file:
        while True:
          line = file.readline()
          if not line:
              break
          yield line


def user_match(user):
    """ Check if the given user matches any of the filters """
    return state.FILTERS is None or any(u in user for u in state.FILTERS)


def email_sort(email):
    """ Split the given email address into a reverse order tuple, for sorting i.e (domain, name) """
    return tuple(reversed(email[0].split('@')))


def valid_date(string):
    """ Validate the given date string fetched from the --enddate argument """
    try:
        date = dateutil.parser.parse(string)
    except ValueError:
        msg = f"Unrecognized date and/or time '{string}'"
        raise argparse.ArgumentTypeError(msg)
    return date
