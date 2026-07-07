"""
Shared Dovecot imapsieve spam-learning setup.

Used by both rspamd and spamassassin (Dovecot 2.4 path). Each filter
provides its own pipe scripts; this writes the Dovecot config and sieve
scripts that call them.
"""

import os

from ... import artifacts


def setup_dovecot_imapsieve(spam_script: str, ham_script: str) -> None:
    """Write Dovecot imapsieve config and sieve scripts for spam learning.

    Configures imap_sieve + sieve_extprograms so that moving mail into
    the Spam folder calls spam_script, and moving mail out calls ham_script.
    Both script names must be executables in /usr/local/bin.

    The mail_plugins/key=yes BOOLLIST syntax appends to the existing plugin
    list without replacing it - this is the Dovecot 2.4 way to extend lists.

    Do NOT pre-compile the sieve scripts with sievec - the imapsieve and
    vnd.dovecot.pipe extensions are registered by plugins that are not
    loaded until Dovecot starts; lazy compilation avoids startup-time failures.
    """
    artifacts.write_file(
        "/etc/dovecot/conf.d/99-local-spam-learning.conf",
        "protocol imap {\n"
        "  mail_plugins/imap_sieve = yes\n"
        "}\n"
        "\n"
        "# sieve_imapsieve: registers the imapsieve extension and imap.* env vars.\n"
        "# sieve_extprograms: provides the vnd.dovecot.pipe sieve command.\n"
        "sieve_plugins/sieve_imapsieve = yes\n"
        "sieve_plugins/sieve_extprograms = yes\n"
        "sieve_global_extensions/imapsieve = yes\n"
        "sieve_global_extensions/vnd.dovecot.pipe = yes\n"
        "sieve_pipe_bin_dir = /usr/local/bin\n"
        "\n"
        "# When mail is moved FROM Spam: learn as ham.\n"
        "imapsieve_from spam_to_ham {\n"
        "  imapsieve_from_name = Spam\n"
        "\n"
        "  sieve_script learn_ham {\n"
        "    sieve_script_type = before\n"
        "    sieve_script_cause = COPY\n"
        "    sieve_script_driver = file\n"
        "    sieve_script_path = /etc/dovecot/sieve/learn-ham.sieve\n"
        "  }\n"
        "}\n"
        "\n"
        "# Runs on all COPY events; the script checks destination is Spam.\n"
        "sieve_script learn_spam {\n"
        "  sieve_script_type = before\n"
        "  sieve_script_cause = COPY\n"
        "  sieve_script_driver = file\n"
        "  sieve_script_path = /etc/dovecot/sieve/learn-spam.sieve\n"
        "}\n",
    )

    os.makedirs("/etc/dovecot/sieve", exist_ok=True)
    artifacts.write_file(
        "/etc/dovecot/sieve/learn-spam.sieve",
        'require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];\n'
        'if environment :matches "imap.mailbox" "Spam" {\n'
        f'    pipe :copy "{spam_script}";\n'
        "}\n",
    )
    artifacts.write_file(
        "/etc/dovecot/sieve/learn-ham.sieve",
        'require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];\n'
        f'pipe :copy "{ham_script}";\n',
    )
