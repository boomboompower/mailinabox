"""
Radicale CardDAV/CalDAV server.

Replaces Z-Push (ActiveSync). Provides contacts and calendar sync to mobile
clients (DAVx5, iOS, Thunderbird) using the same mail credentials.

Steps:
  venv         - create Python venv at /usr/local/lib/radicale (skipped if exists)
  pip-install  - install radicale + passlib[bcrypt] into the venv
  plugin       - write radicale_miab/auth.py and storage.py plugin package
  config       - write /etc/radicale/config
  log          - create log file + logrotate config
  namespace    - detect mount-namespace support; write drop-in if not available
  systemd      - install and enable the systemd unit
"""

import os
import subprocess

from doit.tools import config_changed

from ... import artifacts, SETUP_DIR
from ...component import Component

# ── Component declaration ─────────────────────────────────────────────────────

COMPONENT = Component(
	name="radicale",
	packages=["python3-venv", "python3-pip"],
	services=["radicale"],
	docker_services=["radicale"],
	enabled=lambda env: env.get("ENABLE_RADICALE", "true").lower() != "false",
)

_VENV = "/usr/local/lib/radicale"
_PLUGIN_DIR = "/usr/local/lib/radicale-miab"

_PIP_PACKAGES = ["radicale>=3.1,<4", "passlib[bcrypt]"]

_CONF_DIR = os.path.join(SETUP_DIR, "conf", "systemd")

# ── Auth plugin source (written verbatim to radicale_miab/auth.py) ─────────

_AUTH_PY = '''\
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Radicale auth plugin for Mail-in-a-Box.
Validates credentials via the management daemon\'s /auth/verify endpoint.

management_host is read from the [auth] section of /etc/radicale/config.
The component runner writes the correct value at setup time (127.0.0.1 on
bare metal, the management container service name in Docker).
"""
import logging
import urllib.error
import urllib.parse
import urllib.request

from radicale.auth import BaseAuth

logger = logging.getLogger(__name__)


class Auth(BaseAuth):
    def __init__(self, configuration):
        super().__init__(configuration)
        try:
            self._management_host = configuration.get("auth", "management_host")
        except Exception:
            self._management_host = "127.0.0.1"

    def _login(self, login: str, password: str) -> str:
        try:
            data = urllib.parse.urlencode({"email": login, "password": password}).encode()
            req = urllib.request.Request(
                f"http://{self._management_host}:10222/auth/verify",
                data=data,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return login if resp.status == 200 else ""
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return ""
            logger.warning("Radicale auth error for %s: HTTP %s", login, e.code)
            return ""
        except Exception as e:
            logger.warning("Radicale auth error for %s: %s", login, e)
            return ""
'''

# ── Storage plugin source (written verbatim to radicale_miab/storage.py) ────
#
# Bridges oxi.email per-user SQLite databases to CardDAV/CalDAV:
#   /<email>/contacts/  -> VADDRESSBOOK (contacts table)
#   /<email>/calendar/  -> VCALENDAR (calendar_events table)
#
# Adds vcard_data/ical_data columns on first access so full vCard/iCal payloads
# round-trip without data loss. oxi's structured columns stay in sync for the UI.

_STORAGE_PY = r'''# SPDX-License-Identifier: GPL-3.0-or-later
"""
Radicale 3.7+ storage backend for Mail-in-a-Box.

Bridges oxi.email per-user SQLite databases to CardDAV/CalDAV:
  /<email>/contacts/  -> VADDRESSBOOK (contacts table)
  /<email>/calendar/  -> VCALENDAR (calendar_events table)

Database path: $OXI_DATA_DIR/<sha256(email)>/db.sqlite
"""
import hashlib
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from radicale import storage
from radicale.item import Item

logger = logging.getLogger(__name__)

_CONTACTS = "contacts"
_CALENDAR = "calendar"
_PRODID = "-//MIAB//oxi.email//EN"

_user_locks: Dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_user_lock(user: str) -> threading.Lock:
    with _locks_mutex:
        if user not in _user_locks:
            _user_locks[user] = threading.Lock()
        return _user_locks[user]


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
        pass
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


def _parse_vcard(text: str) -> dict:
    fields = {"name": "", "email": "", "company": "", "notes": ""}
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


class _RootCollection(storage.BaseCollection):
    """Synthetic root collection returned for path '/' to allow client discovery."""

    @property
    def path(self) -> str:
        return ""

    @property
    def tag(self) -> str:
        return ""

    @property
    def etag(self) -> str:
        return '"root"'

    @property
    def last_modified(self) -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def get_meta(self, key=None):
        meta: dict = {"D:displayname": "Radicale"}
        return meta.get(key) if key else meta

    def set_meta(self, props) -> None:
        pass

    def get_all(self) -> Iterator[Item]:
        return iter([])

    def get_multi(self, hrefs) -> Iterable[Tuple[str, Optional[Item]]]:
        return iter([])

    def get_filtered(self, filters) -> Iterable[Tuple[Item, bool]]:
        return iter([])

    def has_uid(self, uid: str) -> bool:
        return False

    def serialize(self, vcf_to_ics: bool = False, **kwargs) -> str:
        return ""

    def sync(self, old_token: str = "") -> Tuple[str, Iterable[str]]:
        return '"root"', []

    def upload(self, href: str, item: Item) -> Tuple[Item, Optional[Item]]:
        raise NotImplementedError

    def delete(self, href: Optional[str] = None) -> None:
        pass


class _OxiCollection(storage.BaseCollection):
    def __init__(self, path: str, data_dir: str, email: str, coll_type: str):
        self._path = path
        self._data_dir = data_dir
        self._email = email
        self._type = coll_type
        self._db = _open_db(data_dir, email)
        if self._db is not None:
            _ensure_columns(self._db)

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
    def is_principal(self) -> bool:
        return False

    @property
    def owner(self) -> str:
        return self._email

    @property
    def etag(self) -> str:
        if self._db is None:
            return '"empty"'
        try:
            table = "contacts" if self._type == _CONTACTS else "calendar_events"
            row = self._db.execute(f"SELECT MAX(updated_at) as ts FROM {table}").fetchone()
            ts = row["ts"] or "empty"
            return f'"{hashlib.md5(ts.encode()).hexdigest()}"'
        except sqlite3.OperationalError:
            return '"empty"'

    @property
    def last_modified(self) -> str:
        if self._db is None:
            return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        try:
            table = "contacts" if self._type == _CONTACTS else "calendar_events"
            row = self._db.execute(f"SELECT MAX(updated_at) as ts FROM {table}").fetchone()
            ts = row["ts"] if row and row["ts"] else _now_sql()
            return _last_modified_rfc1123(ts)
        except sqlite3.OperationalError:
            return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def get_meta(self, key: Optional[str] = None):
        if self._type == _CONTACTS:
            meta = {
                "tag": "VADDRESSBOOK",
                "D:displayname": "Contacts",
                "CR:addressbook-description": "oxi.email contacts",
            }
        else:
            meta = {
                "tag": "VCALENDAR",
                "D:displayname": "Calendar",
                "C:calendar-description": "oxi.email calendar",
            }
        return meta.get(key) if key else meta

    def set_meta(self, props: Mapping) -> None:
        pass

    def get(self, href: str) -> Optional[Item]:
        if self._db is None:
            return None
        uid = href.rsplit(".", 1)[0]
        try:
            if self._type == _CONTACTS:
                row = self._db.execute(
                    "SELECT id, email, name, company, notes, vcard_data, updated_at"
                    " FROM contacts WHERE id=?", (uid,)
                ).fetchone()
                if row is None:
                    return None
                text = _contact_to_vcard(row)
                lm = _last_modified_rfc1123(row["updated_at"])
            else:
                row = self._db.execute(
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

    def get_all(self) -> Iterator[Item]:
        if self._db is None:
            return
        try:
            if self._type == _CONTACTS:
                rows = self._db.execute(
                    "SELECT id, email, name, company, notes, vcard_data, updated_at"
                    " FROM contacts"
                ).fetchall()
                for row in rows:
                    yield Item(collection=self, collection_path=self._path,
                               href=f"{row['id']}.vcf",
                               last_modified=_last_modified_rfc1123(row["updated_at"]),
                               text=_contact_to_vcard(row))
            else:
                rows = self._db.execute(
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

    def get_multi(self, hrefs: Iterable[str]) -> Iterable[Tuple[str, Optional[Item]]]:
        for href in hrefs:
            yield href, self.get(href)

    def get_filtered(self, filters) -> Iterable[Tuple[Item, bool]]:
        for item in self.get_all():
            yield item, True

    def has_uid(self, uid: str) -> bool:
        if self._db is None:
            return False
        try:
            table = "contacts" if self._type == _CONTACTS else "calendar_events"
            row = self._db.execute(f"SELECT id FROM {table} WHERE id=?", (uid,)).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False

    def serialize(self, vcf_to_ics: bool = False, **kwargs) -> str:
        return "".join(item.serialize() for item in self.get_all())

    def sync(self, old_token: str = "") -> Tuple[str, Iterable[str]]:
        token = self.etag
        if self._db is None:
            return token, []
        try:
            table = "contacts" if self._type == _CONTACTS else "calendar_events"
            ext = ".vcf" if self._type == _CONTACTS else ".ics"
            rows = self._db.execute(f"SELECT id FROM {table}").fetchall()
            hrefs = [f"{row['id']}{ext}" for row in rows]
            return token, hrefs
        except sqlite3.OperationalError:
            return token, []

    def upload(self, href: str, item: Item) -> Tuple[Item, Optional[Item]]:
        old_item = self.get(href)
        uid = href.rsplit(".", 1)[0]
        text = item.serialize()
        now = _now_sql()
        if self._db is None:
            raise RuntimeError("No oxi database found for user - log into oxi first")
        if self._type == _CONTACTS:
            f = _parse_vcard(text)
            try:
                self._db.execute("""
                    INSERT INTO contacts
                        (id, email, name, company, notes, vcard_data, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'radicale', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        email=excluded.email, name=excluded.name,
                        company=excluded.company, notes=excluded.notes,
                        vcard_data=excluded.vcard_data, updated_at=excluded.updated_at
                """, (uid, f["email"], f["name"], f["company"], f["notes"], text, now, now))
                self._db.commit()
            except sqlite3.IntegrityError:
                self._db.execute("""
                    UPDATE contacts SET name=?, company=?, notes=?, vcard_data=?, updated_at=?
                    WHERE email=?
                """, (f["name"], f["company"], f["notes"], text, now, f["email"]))
                self._db.commit()
        else:
            f = _parse_ical(text)
            self._db.execute("""
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
            self._db.commit()
        lm = _last_modified_rfc1123(now)
        new_item = Item(collection=self, collection_path=self._path,
                        href=href, last_modified=lm, text=text)
        return new_item, old_item

    def delete(self, href: Optional[str] = None) -> None:
        if href is None or self._db is None:
            return
        uid = href.rsplit(".", 1)[0]
        try:
            if self._type == _CONTACTS:
                self._db.execute("DELETE FROM contacts WHERE id=?", (uid,))
            else:
                self._db.execute("DELETE FROM calendar_events WHERE id=?", (uid,))
            self._db.commit()
        except sqlite3.OperationalError:
            pass


class _PrincipalCollection(storage.BaseCollection):
    """Per-user principal collection."""

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
    def is_principal(self) -> bool:
        return True

    @property
    def owner(self) -> str:
        return self._email

    @property
    def etag(self) -> str:
        return f'"{hashlib.md5(self._email.encode()).hexdigest()}"'

    @property
    def last_modified(self) -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def get_meta(self, key: Optional[str] = None):
        meta = {"D:displayname": self._email}
        return meta.get(key) if key else meta

    def set_meta(self, props: Mapping) -> None:
        pass

    def get(self, href: str) -> Optional[Item]:
        return None

    def get_all(self) -> Iterator[Item]:
        return iter([])

    def get_multi(self, hrefs: Iterable[str]) -> Iterable[Tuple[str, Optional[Item]]]:
        for href in hrefs:
            yield href, None

    def get_filtered(self, filters) -> Iterable[Tuple[Item, bool]]:
        return iter([])

    def has_uid(self, uid: str) -> bool:
        return False

    def serialize(self, vcf_to_ics: bool = False, **kwargs) -> str:
        return ""

    def sync(self, old_token: str = "") -> Tuple[str, Iterable[str]]:
        return self.etag, []

    def upload(self, href: str, item: Item) -> Tuple[Item, Optional[Item]]:
        raise NotImplementedError

    def delete(self, href: Optional[str] = None) -> None:
        pass


class Storage(storage.BaseStorage):
    def __init__(self, configuration):
        super().__init__(configuration)
        self._data_dir = os.environ.get("OXI_DATA_DIR", "")
        if not self._data_dir:
            raise RuntimeError("OXI_DATA_DIR environment variable is not set")

    @contextmanager
    def acquire_lock(self, mode: str, user: str = "", *args, **kwargs):
        lock = _get_user_lock(user or "")
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _parse_path(self, path: str):
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
        return _OxiCollection(f"{email}/{coll_type}", self._data_dir, email, coll_type)

    def discover(self, path: str, depth: str = "0",
                 child_context_manager=None, user_groups=None) -> Iterable:
        email, coll_type, href = self._parse_path(path)
        if email is None:
            yield _RootCollection()
            return
        if coll_type is None:
            yield _PrincipalCollection(email, email)
            if depth != "0":
                yield self._collection(email, _CONTACTS)
                yield self._collection(email, _CALENDAR)
            return
        coll = self._collection(email, coll_type)
        yield coll
        if depth != "0" and href is None:
            yield from coll.get_all()

    def move(self, item: Item, to_collection, to_href: str) -> None:
        to_collection.upload(to_href, item)
        item.collection.delete(item.href)

    def create_collection(self, href: str, items=None,
                          props=None) -> Tuple[storage.BaseCollection, Dict, List]:
        email, coll_type, _ = self._parse_path(href)
        sane = href.strip("/")
        if coll_type:
            coll = _OxiCollection(sane, self._data_dir, email, coll_type)
        else:
            coll = _PrincipalCollection(sane, email)
        return coll, {}, []

    def get_collection(self, path: str) -> Optional[storage.BaseCollection]:
        email, coll_type, _ = self._parse_path(path)
        if email is None:
            return None
        if coll_type is None:
            return _PrincipalCollection(email, email)
        return self._collection(email, coll_type)

    def verify(self) -> bool:
        return True
'''


# ── Tasks ─────────────────────────────────────────────────────────────────────


def make_tasks(env: dict, runtime: str) -> list[dict]:
	storage_root = env["STORAGE_ROOT"]
	webmail = env.get("WEBMAIL_CLIENT", "oxi")
	management_host = env.get("MANAGEMENT_HOST", "127.0.0.1")
	bind_host = "0.0.0.0" if runtime == "docker" else "127.0.0.1"

	return [
		{
			"name": "venv",
			"build": True,  # no env needed - safe to run at Docker build time
			# Only run if the venv directory is missing.
			"targets": [_VENV],
			"actions": [(_venv,)],
		},
		{
			"name": "pip-install",
			"build": True,  # no env needed - safe to run at Docker build time
			# Stamp on package list; re-runs when packages change.
			"uptodate": [config_changed(":".join(_PIP_PACKAGES))],
			"task_dep": ["radicale:venv"],
			"actions": [(_pip_install,)],
		},
		{
			"name": "plugin-auth",
			"uptodate": [config_changed(artifacts.fn_stamp(_write_plugin_auth))],
			"task_dep": ["radicale:pip-install"],
			"actions": [(_write_plugin_auth, [])],
		},
		# Storage plugin bridges oxi per-user SQLite to CardDAV/CalDAV.
		# Only needed when oxi is the active webmail client.
		*(
			[
				{
					"name": "plugin-storage",
					"uptodate": [config_changed(artifacts.fn_stamp(_write_plugin_storage))],
					"task_dep": ["radicale:pip-install"],
					"actions": [(_write_plugin_storage, [])],
				}
			]
			if webmail == "oxi"
			else []
		),
		{
			"name": "config",
			# Stamp includes all values that affect the config output.
			"uptodate": [config_changed(f"{storage_root}:{webmail}:{management_host}:{bind_host}:{artifacts.fn_stamp(_write_config)}")],
			"task_dep": ["radicale:plugin-auth"],
			"actions": [(_write_config, [storage_root, webmail, management_host, bind_host])],
		},
		{
			"name": "log",
			"uptodate": [config_changed(artifacts.fn_stamp(_log))],
			"actions": [(_log,)],
		},
		{
			"name": "namespace",
			# Re-run whenever the function body changes (new directives, etc).
			"uptodate": [config_changed(artifacts.fn_stamp(_namespace_dropin))],
			"actions": [(_namespace_dropin,)],
		},
		{
			"name": "systemd",
			"targets": ["/lib/systemd/system/radicale.service"],
			"uptodate": [config_changed(f"{storage_root}:{_VENV}:{artifacts.fn_stamp(_systemd)}")],
			"task_dep": ["radicale:config"],
			"actions": [(_systemd, [storage_root])],
		},
	]


# ── Action functions ──────────────────────────────────────────────────────────


def _venv() -> None:
	"""Create the Radicale Python virtual environment."""
	subprocess.run(
		["python3", "-m", "venv", _VENV],
		check=True,
		capture_output=True,
	)
	# Ensure pip is present in the venv regardless of how the system Python
	# was installed (some distros omit ensurepip from the base package).
	subprocess.run(
		[f"{_VENV}/bin/python3", "-m", "ensurepip", "--upgrade"],
		check=True,
		capture_output=True,
	)
	subprocess.run(
		[f"{_VENV}/bin/pip", "install", "--upgrade", "pip"],
		check=True,
		capture_output=True,
	)


def _pip_install() -> None:
	"""Install Radicale and passlib into the venv."""
	subprocess.run(
		[f"{_VENV}/bin/pip", "install"] + _PIP_PACKAGES,
		check=True,
		capture_output=True,
	)


def _write_plugin_auth() -> None:
	"""Write the radicale_miab auth plugin."""
	os.makedirs(f"{_PLUGIN_DIR}/radicale_miab", exist_ok=True)
	open(f"{_PLUGIN_DIR}/radicale_miab/__init__.py", "a").close()
	artifacts.write_file(f"{_PLUGIN_DIR}/radicale_miab/auth.py", _AUTH_PY, mode=0o644)
	subprocess.run(["chown", "-R", "root:root", _PLUGIN_DIR], check=True)


def _write_plugin_storage() -> None:
	"""Write the radicale_miab oxi-SQLite storage plugin."""
	os.makedirs(f"{_PLUGIN_DIR}/radicale_miab", exist_ok=True)
	artifacts.write_file(f"{_PLUGIN_DIR}/radicale_miab/storage.py", _STORAGE_PY, mode=0o644)
	subprocess.run(["chown", "-R", "root:root", _PLUGIN_DIR], check=True)


def _write_config(storage_root: str, webmail: str, management_host: str = "127.0.0.1", bind_host: str = "127.0.0.1") -> None:
	"""Write /etc/radicale/config.

	When WEBMAIL=oxi the custom plugin bridges per-user SQLite databases so
	contacts/calendar show up in both the web UI and DAV clients.
	For all other clients, Radicale's standard multifilesystem storage is used
	so contacts saved via DAV clients (DAVx5, iOS, Thunderbird) are persisted
	independently.

	/var/lib/radicale is used (not /home) so the path is outside home and
	compatible with ProtectHome=true in the systemd sandbox.
	"""
	os.makedirs("/etc/radicale", exist_ok=True)
	os.makedirs("/var/lib/radicale", exist_ok=True)

	if webmail == "oxi":
		storage_block = "type = radicale_miab.storage"
	else:
		# /var/lib/radicale: outside /home, compatible with ProtectHome=true.
		collections_path = "/var/lib/radicale/collections"
		os.makedirs(collections_path, exist_ok=True)
		subprocess.run(["chown", "www-data:www-data", collections_path], check=True)
		storage_block = f"type = multifilesystem\nfilesystem_folder = {collections_path}"

	artifacts.write_file(
		"/etc/radicale/config",
		"[server]\n"
		f"hosts = {bind_host}:5232\n"
		"max_connections = 20\n"
		"max_content_length = 10000000\n"
		"timeout = 30\n"
		"\n"
		"[auth]\n"
		"type = radicale_miab.auth\n"
		"# management_host: address of the management daemon used to validate credentials.\n"
		f"management_host = {management_host}\n"
		"delay = 1\n"
		"cache_logins = True\n"
		"cache_successful_logins_expiry = 300\n"
		"cache_failed_logins_expiry = 90\n"
		"urldecode_username = True\n"
		"\n"
		"[rights]\n"
		"type = owner_only\n"
		"permit_delete_collection = False\n"
		"permit_overwrite_collection = False\n"
		"\n"
		"[storage]\n"
		f"{storage_block}\n"
		"\n"
		"[web]\n"
		"type = none\n"
		"\n"
		"[logging]\n"
		"level = warning\n"
		"mask_passwords = True\n"
		"\n"
		"[headers]\n"
		"X-Frame-Options = DENY\n"
		"Content-Security-Policy = frame-ancestors 'none'\n",
		mode=0o644,
	)


def _log() -> None:
	"""Create log file and write logrotate config."""
	log = "/var/log/radicale.log"
	if not os.path.exists(log):
		open(log, "a").close()
	subprocess.run(["chown", "www-data:www-data", log], check=True)

	artifacts.write_file(
		"/etc/logrotate.d/radicale",
		"/var/log/radicale.log {\n    daily\n    missingok\n    rotate 14\n    compress\n    delaycompress\n    notifempty\n    copytruncate\n    su www-data www-data\n}\n",
	)


def _namespace_dropin() -> None:
	"""Write a sandbox drop-in for kernels that lack mount namespace support.

	Some VPS kernels (OpenVZ, LXC) don't support mount namespaces, causing
	PrivateTmp=true and ProtectSystem=strict to fail with 226/NAMESPACE.
	Detect this at install time and write a drop-in disabling only those directives.
	"""
	dropin_dir = "/etc/systemd/system/radicale.service.d"
	dropin = os.path.join(dropin_dir, "no-namespace.conf")
	os.makedirs(dropin_dir, exist_ok=True)

	result = subprocess.run(["unshare", "-m", "true"], check=False, capture_output=True)
	if result.returncode == 0:
		# Namespaces supported - remove any previously applied drop-in.
		if os.path.exists(dropin):
			os.unlink(dropin)
	else:
		print("  Note: kernel lacks mount namespace support - applying reduced sandbox configuration")
		artifacts.write_file(
			dropin,
			"[Service]\nPrivateTmp=false\nProtectSystem=false\nBindPaths=\nReadWritePaths=\n",
		)


def _systemd(storage_root: str) -> None:
	"""Install and enable the Radicale systemd unit."""
	unit_src = os.path.join(_CONF_DIR, "radicale.service")
	if os.path.exists(unit_src):
		with open(unit_src) as fh:
			unit_content = fh.read().replace("${RADICALE_VENV}", _VENV).replace("${STORAGE_ROOT}", storage_root)
		artifacts.write_file("/lib/systemd/system/radicale.service", unit_content)

	subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
	subprocess.run(["systemctl", "enable", "radicale"], check=True, capture_output=True)
