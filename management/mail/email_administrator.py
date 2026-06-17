#!/usr/local/lib/mailinabox/env/bin/python

# Reads in STDIN. If the stream is not empty, mail it to the system administrator.

import os
import sys

import html
import smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# In Python 3.6:
#from email.message import Message

# Allow running this file directly as well as importing it as part of the
# management package - both need management/ on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import load_environment

# Load system environment info.
env = load_environment()

# Sanity check command line args.
if len(sys.argv) < 2:
    sys.exit("Missing subject argument")

# Process command line args.
subject = sys.argv[1]

# Administrator's email address.
admin_addr = "administrator@" + env['PRIMARY_HOSTNAME']

# Read in STDIN.
content = sys.stdin.read().strip()

# If there's nothing coming in, just exit.
if content == "":
    sys.exit(0)

# create MIME message
msg = MIMEMultipart('alternative')

# In Python 3.6:
#msg = Message()

msg['From'] = '"{}" <{}>'.format(env['PRIMARY_HOSTNAME'], admin_addr)
msg['To'] = admin_addr
msg['Subject'] = "[{}] {}".format(env['PRIMARY_HOSTNAME'], subject)

content_html = f"""
<div style="font-family: sans-serif; max-width:720px; margin:0 auto; padding:20px 12px;">

  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
    style="border-collapse:separate; border:1px solid #E7E0EC; border-radius:24px; overflow:hidden;
           background:#F6F3F9; box-shadow:0 1px 2px rgba(0,0,0,0.06), 0 3px 10px rgba(0,0,0,0.04);">

    <!-- Header -->
    <tr>
      <td style="background:#E8DEF8; padding:20px 24px; border-bottom:1px solid #D0C4E3;">
        <div style="font-size:22px; font-weight:700; color:#21005D; line-height:1.2;">
          {html.escape(subject)}
        </div>
        <div style="margin-top:6px; font-size:13px; color:#4A4458; line-height:1.45;">
          {html.escape(env['PRIMARY_HOSTNAME'])} - Automated Report
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding:22px 24px 24px;">
        <pre style="
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          font-size:12.5px;
          line-height:1.55;
          white-space:pre-wrap;
          word-break:break-word;
          overflow-wrap:anywhere;
          color:#1C1B1F;
          margin:0;
        ">{html.escape(content)}</pre>
      </td>
    </tr>
  </table>
</div>"""

msg.attach(MIMEText(content, 'plain'))
msg.attach(MIMEText(content_html, 'html'))

# In Python 3.6:
#msg.set_content(content)
#msg.add_alternative(content_html, "html")

# send
smtpclient = smtplib.SMTP('127.0.0.1', 25)
smtpclient.ehlo()
smtpclient.sendmail(
        admin_addr, # MAIL FROM
        admin_addr, # RCPT TO
        msg.as_string())
smtpclient.quit()
