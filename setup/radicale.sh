#!/bin/bash
# Radicale CardDAV/CalDAV server for Mail-in-a-Box.
#
# Replaces Z-Push (ActiveSync). Provides contacts and calendar sync to
# mobile clients (DAVx5, iOS, Thunderbird) using the same mail credentials.
# Storage backend reads/writes the oxi.email per-user SQLite databases at
# $STORAGE_ROOT/oxi/<sha256(email)>/db.sqlite.

source setup/functions.sh
source /etc/mailinabox.conf

echo "Installing Radicale (CardDAV/CalDAV)..."

# Install Radicale into a dedicated venv.
RADICALE_VENV=/usr/local/lib/radicale

if [ ! -d "$RADICALE_VENV" ]; then
	python3 -m venv "$RADICALE_VENV"
fi
hide_output "$RADICALE_VENV/bin/pip" install --upgrade pip
hide_output "$RADICALE_VENV/bin/pip" install "radicale>=3.1,<4" "passlib[bcrypt]"

# Plugin package directory.
PLUGIN_DIR=/usr/local/lib/radicale-miab
mkdir -p "$PLUGIN_DIR/radicale_miab"
touch "$PLUGIN_DIR/radicale_miab/__init__.py"

# Auth plugin: validates credentials against Dovecot on 127.0.0.1:143.
# Uses the same plaintext-loopback IMAP listener that oxi.email uses.
cat > "$PLUGIN_DIR/radicale_miab/auth.py" << 'PYEOF'
"""
Radicale auth plugin for Mail-in-a-Box.
Validates credentials against Dovecot on 127.0.0.1:143 (loopback IMAP).
"""
import imaplib
import logging

from radicale.auth import BaseAuth

logger = logging.getLogger(__name__)


class Auth(BaseAuth):
    def login(self, login: str, password: str) -> str:
        try:
            conn = imaplib.IMAP4("127.0.0.1", 143)
            conn.login(login, password)
            conn.logout()
            return login
        except imaplib.IMAP4.error:
            return ""
        except Exception as e:
            logger.warning("Radicale auth error for %s: %s", login, e)
            return ""
PYEOF

# Storage plugin: bridges oxi.email per-user SQLite to CardDAV/CalDAV.
cat > "$PLUGIN_DIR/radicale_miab/storage.py" << 'PYEOF'
"""
Radicale storage backend for Mail-in-a-Box.

Bridges oxi.email per-user SQLite databases to CardDAV/CalDAV:
  /<email>/contacts/  → VADDRESSBOOK (contacts + contact_groups tables)
  /<email>/calendar/  → VCALENDAR (calendar_events table)

Database path: $OXI_DATA_DIR/<sha256(email)>/db.sqlite

Adds vcard_data/ical_data columns on first access so full vCard/iCal payloads
round-trip without data loss. oxi's structured columns (name, email, company,
notes, title, etc.) are also kept in sync so the oxi UI continues to work.
"""

import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Mapping, Optional

from radicale import storage
from radicale.item import Item

logger = logging.getLogger(__name__)

_CONTACTS = "contacts"
_CALENDAR = "calendar"
_PRODID = "-//MIAB//oxi.email//EN"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_email(email: str) -> str:
    """Match oxi's hash_email: SHA-256 of raw email bytes, lowercase hex."""
    return hashlib.sha256(email.encode()).hexdigest()


def _db_path(data_dir: str, email: str) -> str:
    return os.path.join(data_dir, _hash_email(email), "db.sqlite")


def _open_db(data_dir: str, email: str) -> Optional[sqlite3.Connection]:
    path = _db_path(data_dir, email)
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add Radicale storage columns to oxi's tables if not present yet."""
    try:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
        if "vcard_data" not in existing:
            conn.execute("ALTER TABLE contacts ADD COLUMN vcard_data TEXT")
            conn.commit()
    except sqlite3.OperationalError:
        pass  # Table may not exist yet (user never logged into oxi)
    try:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(calendar_events)")}
        if "ical_data" not in existing:
            conn.execute("ALTER TABLE calendar_events ADD COLUMN ical_data TEXT")
            conn.commit()
    except sqlite3.OperationalError:
        pass


def _vcard_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ical_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold a vCard/iCal line at 75 characters per RFC 5545/6350."""
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    rest = line[75:]
    while rest:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(parts)


def _now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _last_modified_rfc1123(updated_at: str) -> str:
    try:
        s = updated_at.replace("T", " ").rstrip("Z")
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _dt_to_ical(dt_str: str, all_day: bool = False) -> str:
    try:
        s = dt_str.replace("T", " ").rstrip("Z")
        if all_day:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y%m%d")
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%dT%H%M%SZ")
    except (ValueError, AttributeError):
        return ""


def _parse_ical_dt(val: str) -> str:
    val = val.strip().rstrip("Z")
    try:
        if "T" in val:
            return datetime.strptime(val[:15], "%Y%m%dT%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        return datetime.strptime(val[:8], "%Y%m%d").strftime("%Y-%m-%d 00:00:00")
    except ValueError:
        return val


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _contact_to_vcard(row: sqlite3.Row) -> str:
    if row["vcard_data"]:
        return row["vcard_data"]
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{row['id']}"]
    name = _vcard_escape(row["name"] or "")
    email = row["email"] or ""
    if name:
        lines.append(_fold(f"FN:{name}"))
        parts = name.split(" ", 1)
        last = _vcard_escape(parts[-1]) if len(parts) > 1 else ""
        first = _vcard_escape(parts[0]) if len(parts) > 1 else _vcard_escape(name)
        lines.append(f"N:{last};{first};;;")
    else:
        lines.append(f"FN:{email}")
        lines.append("N:;;;;")
    if email:
        lines.append(f"EMAIL;TYPE=INTERNET:{_vcard_escape(email)}")
    if row["company"]:
        lines.append(_fold(f"ORG:{_vcard_escape(row['company'])}"))
    if row["notes"]:
        lines.append(_fold(f"NOTE:{_vcard_escape(row['notes'])}"))
    rev = (row["updated_at"] or "").replace(" ", "T").rstrip("Z") + "Z"
    lines.append(f"REV:{rev}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def _event_to_ical(row: sqlite3.Row) -> str:
    if row["ical_data"]:
        return row["ical_data"]
    all_day = bool(row["all_day"])
    start = _dt_to_ical(row["start_time"], all_day)
    end = _dt_to_ical(row["end_time"], all_day)
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        f"PRODID:{_PRODID}", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT", f"UID:{row['id']}", f"DTSTAMP:{dtstamp}",
    ]
    if all_day:
        lines += [f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}"]
    else:
        lines += [f"DTSTART:{start}", f"DTEND:{end}"]
    if row["title"]:
        lines.append(_fold(f"SUMMARY:{_ical_escape(row['title'])}"))
    if row["description"]:
        lines.append(_fold(f"DESCRIPTION:{_ical_escape(row['description'])}"))
    if row["location"]:
        lines.append(_fold(f"LOCATION:{_ical_escape(row['location'])}"))
    if row["recurrence_rule"]:
        lines.append(f"RRULE:{row['recurrence_rule']}")
    if row["status"]:
        lines.append(f"STATUS:{row['status'].upper()}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_vcard(text: str) -> dict:
    fields = {"name": "", "email": "", "company": "", "notes": ""}
    # Unfold continuation lines
    unfolded = text.replace("\r\n ", "").replace("\r\n\t", "")
    for line in unfolded.splitlines():
        key, _, value = line.partition(":")
        key_base = key.upper().split(";")[0]
        value = (value.replace("\\n", "\n").replace("\\,", ",")
                 .replace("\\;", ";").replace("\\\\", "\\"))
        if key_base == "FN":
            fields["name"] = value
        elif key_base == "EMAIL" and not fields["email"]:
            fields["email"] = value
        elif key_base == "ORG":
            fields["company"] = value.split(";")[0]
        elif key_base == "NOTE":
            fields["notes"] = value
    return fields


def _parse_ical(text: str) -> dict:
    fields = {
        "title": "", "description": "", "location": "",
        "start_time": "", "end_time": "", "all_day": 0,
        "recurrence_rule": None, "status": "confirmed",
    }
    in_vevent = False
    unfolded = text.replace("\r\n ", "").replace("\r\n\t", "")
    for line in unfolded.splitlines():
        if line == "BEGIN:VEVENT":
            in_vevent = True
            continue
        if line == "END:VEVENT":
            break
        if not in_vevent:
            continue
        key, _, value = line.partition(":")
        key_base = key.upper().split(";")[0]
        value = (value.replace("\\n", "\n").replace("\\,", ",")
                 .replace("\\;", ";").replace("\\\\", "\\"))
        if key_base == "SUMMARY":
            fields["title"] = value
        elif key_base == "DESCRIPTION":
            fields["description"] = value
        elif key_base == "LOCATION":
            fields["location"] = value
        elif key_base == "RRULE":
            fields["recurrence_rule"] = value
        elif key_base == "STATUS":
            fields["status"] = value.lower()
        elif key_base in ("DTSTART", "DTEND"):
            if "VALUE=DATE" in key.upper() and "VALUE=DATE-TIME" not in key.upper():
                fields["all_day"] = 1
            parsed = _parse_ical_dt(value)
            if key_base == "DTSTART":
                fields["start_time"] = parsed
            else:
                fields["end_time"] = parsed
    return fields


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

class _OxiCollection(storage.BaseCollection):
    def __init__(self, path: str, data_dir: str, email: str, coll_type: str):
        self._path = path
        self._data_dir = data_dir
        self._email = email
        self._type = coll_type  # _CONTACTS or _CALENDAR

    @property
    def path(self) -> str:
        return self._path

    @property
    def tag(self) -> str:
        return "VADDRESSBOOK" if self._type == _CONTACTS else "VCALENDAR"

    @property
    def color(self) -> str:
        return ""

    @property
    def etag(self) -> str:
        conn = _open_db(self._data_dir, self._email)
        if conn is None:
            return '"empty"'
        try:
            _ensure_columns(conn)
            table = "contacts" if self._type == _CONTACTS else "calendar_events"
            row = conn.execute(f"SELECT MAX(updated_at) as ts FROM {table}").fetchone()
            ts = row["ts"] or "empty"
            return f'"{hashlib.md5(ts.encode()).hexdigest()}"'
        finally:
            conn.close()

    @property
    def last_modified(self) -> str:
        conn = _open_db(self._data_dir, self._email)
        if conn is None:
            return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        try:
            table = "contacts" if self._type == _CONTACTS else "calendar_events"
            row = conn.execute(f"SELECT MAX(updated_at) as ts FROM {table}").fetchone()
            ts = row["ts"] if row and row["ts"] else _now_sql()
            return _last_modified_rfc1123(ts)
        except sqlite3.OperationalError:
            return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        finally:
            conn.close()

    def get_meta(self, key: Optional[str] = None):
        if self._type == _CONTACTS:
            meta = {
                "tag": "VADDRESSBOOK",
                "{DAV:}displayname": "Contacts",
                "{urn:ietf:params:xml:ns:carddav}addressbook-description": "oxi.email contacts",
            }
        else:
            meta = {
                "tag": "VCALENDAR",
                "{DAV:}displayname": "Calendar",
                "{urn:ietf:params:xml:ns:caldav}calendar-description": "oxi.email calendar",
            }
        return meta.get(key) if key else meta

    def set_meta(self, props: Mapping) -> None:
        pass

    def get(self, href: str) -> Optional[Item]:
        uid = href.rsplit(".", 1)[0]
        conn = _open_db(self._data_dir, self._email)
        if conn is None:
            return None
        try:
            _ensure_columns(conn)
            if self._type == _CONTACTS:
                row = conn.execute(
                    "SELECT id, email, name, company, notes, vcard_data, updated_at"
                    " FROM contacts WHERE id=?", (uid,)
                ).fetchone()
                if row is None:
                    return None
                text = _contact_to_vcard(row)
                lm = _last_modified_rfc1123(row["updated_at"])
            else:
                row = conn.execute(
                    "SELECT id, title, description, location, start_time, end_time,"
                    " all_day, recurrence_rule, status, ical_data, updated_at"
                    " FROM calendar_events WHERE id=?", (uid,)
                ).fetchone()
                if row is None:
                    return None
                text = _event_to_ical(row)
                lm = _last_modified_rfc1123(row["updated_at"])
            return Item(collection=self, collection_path=self._path,
                        href=href, last_modified=lm, text=text)
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

    def get_all(self) -> Iterator[Item]:
        conn = _open_db(self._data_dir, self._email)
        if conn is None:
            return
        try:
            _ensure_columns(conn)
            if self._type == _CONTACTS:
                rows = conn.execute(
                    "SELECT id, email, name, company, notes, vcard_data, updated_at FROM contacts"
                ).fetchall()
                for row in rows:
                    yield Item(collection=self, collection_path=self._path,
                               href=f"{row['id']}.vcf",
                               last_modified=_last_modified_rfc1123(row["updated_at"]),
                               text=_contact_to_vcard(row))
            else:
                rows = conn.execute(
                    "SELECT id, title, description, location, start_time, end_time,"
                    " all_day, recurrence_rule, status, ical_data, updated_at"
                    " FROM calendar_events"
                ).fetchall()
                for row in rows:
                    yield Item(collection=self, collection_path=self._path,
                               href=f"{row['id']}.ics",
                               last_modified=_last_modified_rfc1123(row["updated_at"]),
                               text=_event_to_ical(row))
        except sqlite3.OperationalError:
            return
        finally:
            conn.close()

    def upload(self, href: str, item: Item) -> Item:
        uid = href.rsplit(".", 1)[0]
        text = item.serialize()
        now = _now_sql()
        conn = _open_db(self._data_dir, self._email)
        if conn is None:
            raise RuntimeError(f"No oxi database found for user - log into oxi first")
        try:
            _ensure_columns(conn)
            if self._type == _CONTACTS:
                f = _parse_vcard(text)
                try:
                    conn.execute("""
                        INSERT INTO contacts
                            (id, email, name, company, notes, vcard_data, source, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'radicale', ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            email=excluded.email, name=excluded.name,
                            company=excluded.company, notes=excluded.notes,
                            vcard_data=excluded.vcard_data, updated_at=excluded.updated_at
                    """, (uid, f["email"], f["name"], f["company"], f["notes"], text, now, now))
                    conn.commit()
                except sqlite3.IntegrityError:
                    # Email unique constraint conflict - update the existing row by email
                    conn.execute("""
                        UPDATE contacts SET name=?, company=?, notes=?, vcard_data=?, updated_at=?
                        WHERE email=?
                    """, (f["name"], f["company"], f["notes"], text, now, f["email"]))
                    conn.commit()
            else:
                f = _parse_ical(text)
                conn.execute("""
                    INSERT INTO calendar_events
                        (id, title, description, location, start_time, end_time,
                         all_day, recurrence_rule, status, ical_data, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'radicale', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, description=excluded.description,
                        location=excluded.location, start_time=excluded.start_time,
                        end_time=excluded.end_time, all_day=excluded.all_day,
                        recurrence_rule=excluded.recurrence_rule, status=excluded.status,
                        ical_data=excluded.ical_data, updated_at=excluded.updated_at
                """, (uid, f["title"], f["description"], f["location"],
                      f["start_time"], f["end_time"], f["all_day"],
                      f["recurrence_rule"], f["status"], text, now, now))
                conn.commit()
        finally:
            conn.close()
        # Return a fresh Item with current timestamp
        lm = _last_modified_rfc1123(now)
        return Item(collection=self, collection_path=self._path,
                    href=href, last_modified=lm, text=text)

    def delete(self, href: Optional[str] = None) -> None:
        if href is None:
            return  # Never delete the collection itself
        uid = href.rsplit(".", 1)[0]
        conn = _open_db(self._data_dir, self._email)
        if conn is None:
            return
        try:
            if self._type == _CONTACTS:
                conn.execute("DELETE FROM contacts WHERE id=?", (uid,))
            else:
                conn.execute("DELETE FROM calendar_events WHERE id=?", (uid,))
            conn.commit()
        finally:
            conn.close()


class _PrincipalCollection(storage.BaseCollection):
    """Per-user principal collection (/<email>/)."""

    def __init__(self, path: str, email: str):
        self._path = path
        self._email = email

    @property
    def path(self) -> str:
        return self._path

    @property
    def tag(self) -> str:
        return ""

    @property
    def etag(self) -> str:
        return f'"{hashlib.md5(self._email.encode()).hexdigest()}"'

    @property
    def last_modified(self) -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def get_meta(self, key=None):
        meta = {"{DAV:}displayname": self._email}
        return meta.get(key) if key else meta

    def set_meta(self, props):
        pass

    def get(self, href):
        return None

    def get_all(self):
        return iter([])

    def upload(self, href, item):
        raise NotImplementedError

    def delete(self, href=None):
        pass


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class Storage(storage.BaseStorage):
    def __init__(self, configuration):
        super().__init__(configuration)
        self._data_dir = os.environ.get("OXI_DATA_DIR", "")
        if not self._data_dir:
            raise RuntimeError("OXI_DATA_DIR environment variable is not set")

    @contextmanager
    def acquire_lock(self, mode, user=None):
        yield  # SQLite handles its own locking

    def _parse_path(self, path: str):
        """Return (email, collection_type, href) for a normalised Radicale path."""
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            return None, None, None
        email = parts[0]
        if len(parts) == 1:
            return email, None, None
        coll = parts[1]
        href = parts[2] if len(parts) > 2 else None
        if coll == _CONTACTS:
            return email, _CONTACTS, href
        if coll == _CALENDAR:
            return email, _CALENDAR, href
        return email, None, None

    def _collection(self, email: str, coll_type: str) -> _OxiCollection:
        return _OxiCollection(f"/{email}/{coll_type}/", self._data_dir, email, coll_type)

    def discover(self, path: str, depth: str = "0") -> Iterator:
        email, coll_type, href = self._parse_path(path)
        if email is None:
            return

        if coll_type is None:
            # Principal level
            yield _PrincipalCollection(f"/{email}/", email)
            if depth != "0":
                yield self._collection(email, _CONTACTS)
                yield self._collection(email, _CALENDAR)
            return

        coll = self._collection(email, coll_type)
        yield coll
        if depth != "0" and href is None:
            yield from coll.get_all()

    def move(self, item: Item, to_collection, to_href: str) -> None:
        text = item.serialize()
        to_collection.upload(to_href, item)
        item.collection.delete(item.href)

    def create_collection(self, path: str, collection=None, props=None):
        email, coll_type, _ = self._parse_path(path)
        norm = path if path.endswith("/") else path + "/"
        if coll_type:
            return _OxiCollection(norm, self._data_dir, email, coll_type)
        return _PrincipalCollection(norm, email)

    def get_collection(self, path: str) -> Optional[storage.BaseCollection]:
        email, coll_type, _ = self._parse_path(path)
        if email is None:
            return None
        if coll_type is None:
            return _PrincipalCollection(f"/{email}/", email)
        return self._collection(email, coll_type)
PYEOF

chmod 644 "$PLUGIN_DIR/radicale_miab/auth.py"
chmod 644 "$PLUGIN_DIR/radicale_miab/storage.py"
chown -R root:root "$PLUGIN_DIR"

# Radicale configuration.
mkdir -p /etc/radicale
cat > /etc/radicale/config << EOF
[server]
hosts = 127.0.0.1:5232
max_connections = 20
max_content_length = 10000000
timeout = 30

[auth]
type = radicale_miab.auth
delay = 1

[storage]
type = radicale_miab.storage

[logging]
level = warning
mask_passwords = True

[headers]
X-Frame-Options = DENY
Content-Security-Policy = frame-ancestors 'none'
EOF
chmod 644 /etc/radicale/config

# Log file.
touch /var/log/radicale.log
chown www-data:www-data /var/log/radicale.log

# Logrotate.
cat > /etc/logrotate.d/radicale << 'LOGROTATEOF'
/var/log/radicale.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
    su www-data www-data
}
LOGROTATEOF

# Systemd unit.
cat > /lib/systemd/system/radicale.service << EOF
[Unit]
Description=Radicale CardDAV/CalDAV server
After=network.target dovecot.service

[Service]
ExecStart=$RADICALE_VENV/bin/python -m radicale --config /etc/radicale/config
User=www-data
Group=www-data
Environment=PYTHONPATH=/usr/local/lib/radicale-miab
Environment=OXI_DATA_DIR=$STORAGE_ROOT/oxi
StandardOutput=append:/var/log/radicale.log
StandardError=append:/var/log/radicale.log
Restart=on-failure
RestartSec=5

# Sandboxing
CapabilityBoundingSet=
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictNamespaces=true
LockPersonality=true
RestrictRealtime=true
RestrictSUIDSGID=true
NoNewPrivileges=true
ReadWritePaths=$STORAGE_ROOT/oxi /var/log/radicale.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable radicale
restart_service radicale
