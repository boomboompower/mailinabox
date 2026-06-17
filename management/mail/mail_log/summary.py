import textwrap
import time
from collections import defaultdict, OrderedDict

from . import state
from .util import email_sort
from .report import print_header, print_user_table, print_time_table
from .scanning import scan_files

def scan_mail_log(env):
    """ Scan the system's mail log files and collect interesting data

    This function scans the 2 most recent mail log files in /var/log/.

    Args:
        env (dict): Dictionary containing MiaB settings

    """

    collector = {
        "scan_count": 0,  # Number of lines scanned
        "parse_count": 0,  # Number of lines parsed (i.e. that had their contents examined)
        "scan_time": time.time(),  # The time in seconds the scan took
        "sent_mail": OrderedDict(),  # Data about email sent by users
        "received_mail": OrderedDict(),  # Data about email received by users
        "logins": OrderedDict(),  # Data about login activity
        "postgrey": {},  # Data about greylisting of email addresses
        "rejected": OrderedDict(),  # Emails that were blocked
        "known_addresses": None,  # Addresses handled by the Miab installation
        "other-services": set(),
    }

    try:
        from mail import mailconfig
        collector["known_addresses"] = (set(mailconfig.get_mail_users(env)) |
                                        {alias[0] for alias in mailconfig.get_mail_aliases(env)})
    except ImportError:
        pass

    print(f"Scanning logs from {state.START_DATE:%Y-%m-%d %H:%M:%S} to {state.END_DATE:%Y-%m-%d %H:%M:%S}"
    )

    # Scan the lines in the log files until the date goes out of range
    scan_files(collector)

    if not collector["scan_count"]:
        print("No log lines scanned...")
        return

    collector["scan_time"] = time.time() - collector["scan_time"]

    print("{scan_count} Log lines scanned, {parse_count} lines parsed in {scan_time:.2f} "
          "seconds\n".format(**collector))

    # Print Sent Mail report

    if collector["sent_mail"]:
        msg = "Sent email"
        print_header(msg)

        data = OrderedDict(sorted(collector["sent_mail"].items(), key=email_sort))

        print_user_table(
            data.keys(),
            data=[
                ("sent", [u["sent_count"] for u in data.values()]),
                ("hosts", [len(u["hosts"]) for u in data.values()]),
            ],
            sub_data=[
                ("sending hosts", [u["hosts"] for u in data.values()]),
            ],
            activity=[
                ("sent", [u["activity-by-hour"] for u in data.values()]),
            ],
            earliest=[u["earliest"] for u in data.values()],
            latest=[u["latest"] for u in data.values()],
        )

        accum = defaultdict(int)
        data = collector["sent_mail"].values()

        for h in range(24):
            accum[h] = sum(d["activity-by-hour"][h] for d in data)

        print_time_table(
            ["sent"],
            [accum]
        )

    # Print Received Mail report

    if collector["received_mail"]:
        msg = "Received email"
        print_header(msg)

        data = OrderedDict(sorted(collector["received_mail"].items(), key=email_sort))

        print_user_table(
            data.keys(),
            data=[
                ("received", [u["received_count"] for u in data.values()]),
            ],
            activity=[
                ("sent", [u["activity-by-hour"] for u in data.values()]),
            ],
            earliest=[u["earliest"] for u in data.values()],
            latest=[u["latest"] for u in data.values()],
        )

        accum = defaultdict(int)
        for h in range(24):
            accum[h] = sum(d["activity-by-hour"][h] for d in data.values())

        print_time_table(
            ["received"],
            [accum]
        )

    # Print login report

    if collector["logins"]:
        msg = "User logins per hour"
        print_header(msg)

        data = OrderedDict(sorted(collector["logins"].items(), key=email_sort))

        # Get a list of all of the protocols seen in the logs in reverse count order.
        all_protocols = defaultdict(int)
        for u in data.values():
            for protocol_name, count in u["totals_by_protocol"].items():
                all_protocols[protocol_name] += count
        all_protocols = [k for k, v in sorted(all_protocols.items(), key=lambda kv : -kv[1])]

        print_user_table(
            data.keys(),
            data=[
                (protocol_name, [
                    round(u["totals_by_protocol"][protocol_name] / (u["latest"]-u["earliest"]).total_seconds() * 60*60, 1)
                    if (u["latest"]-u["earliest"]).total_seconds() > 0
                    else 0 # prevent division by zero
                  for u in data.values()])
                for protocol_name in all_protocols
            ],
            sub_data=[
                ("Protocol and Source", [[
                    f"{protocol_name} {host}: {count} times"
                    for (protocol_name, host), count
                    in sorted(u["totals_by_protocol_and_host"].items(), key=lambda kv:-kv[1])
                  ] for u in data.values()])
            ],
            activity=[
                (protocol_name, [u["activity-by-hour"][protocol_name] for u in data.values()])
                for protocol_name in all_protocols
            ],
            earliest=[u["earliest"] for u in data.values()],
            latest=[u["latest"] for u in data.values()],
            numstr=lambda n : str(round(n, 1)),
        )

        accum = { protocol_name: defaultdict(int) for protocol_name in all_protocols }
        for h in range(24):
            for protocol_name in all_protocols:
              accum[protocol_name][h] = sum(d["activity-by-hour"][protocol_name][h] for d in data.values())

        print_time_table(
            all_protocols,
            [accum[protocol_name] for protocol_name in all_protocols]
        )

    if collector["postgrey"]:
        msg = "Greylisted Email {:%Y-%m-%d %H:%M:%S} and {:%Y-%m-%d %H:%M:%S}"
        print_header(msg.format(state.START_DATE, state.END_DATE))

        print(textwrap.fill(
            "The following mail was greylisted, meaning the emails were temporarily rejected. "
            "Legitimate senders must try again after three minutes.",
            width=80, initial_indent=" ", subsequent_indent=" "
        ), end='\n\n')

        data = OrderedDict(sorted(collector["postgrey"].items(), key=email_sort))
        users = []
        received = []
        senders = []
        sender_clients = []
        delivered_dates = []

        for recipient in data:
            sorted_recipients = sorted(data[recipient].items(), key=lambda kv: kv[1][0] or kv[1][1])
            for (client_address, sender), (first_date, delivered_date) in sorted_recipients:
                if first_date:
                    users.append(recipient)
                    received.append(first_date)
                    senders.append(sender)
                    delivered_dates.append(delivered_date)
                    sender_clients.append(client_address)

        print_user_table(
            users,
            data=[
                ("received", received),
                ("sender", senders),
                ("delivered", [str(d) or "no retry yet" for d in delivered_dates]),
                ("sending host", sender_clients)
            ],
            delimit=True,
        )

    if collector["rejected"]:
        msg = "Blocked Email {:%Y-%m-%d %H:%M:%S} and {:%Y-%m-%d %H:%M:%S}"
        print_header(msg.format(state.START_DATE, state.END_DATE))

        data = OrderedDict(sorted(collector["rejected"].items(), key=email_sort))

        rejects = []

        if state.VERBOSE:
            for user_data in data.values():
                user_rejects = []
                for date, sender, message in user_data["blocked"]:
                    if len(sender) > 64:
                        sender = sender[:32] + "…" + sender[-32:]
                    user_rejects.extend((f'{date} - {sender} ', f'  {message}'))
                rejects.append(user_rejects)

        print_user_table(
            data.keys(),
            data=[
                ("blocked", [len(u["blocked"]) for u in data.values()]),
            ],
            sub_data=[
                ("blocked emails", rejects),
            ],
            earliest=[u["earliest"] for u in data.values()],
            latest=[u["latest"] for u in data.values()],
        )

    if collector["other-services"] and state.VERBOSE and False:
        print_header("Other services")
        print("The following unknown services were found in the log file.")
        print(" ", *sorted(collector["other-services"]), sep='\n│ ')
