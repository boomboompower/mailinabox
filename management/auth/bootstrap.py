"""
Bootstrap token management and first-admin creation.

The bootstrap endpoint is only active when a token file exists on disk.
Without the file the route returns 404, so the endpoint is invisible during
normal operation. boxctl bootstrap writes the file; the route deletes it on
first successful use or on lockout.
"""

import json
import os
import secrets
import time
import uuid

# Attempt counter keyed by token UUID. Keyed so that a new token written by
# boxctl bootstrap resets the counter automatically - the UUID mismatch is
# detected on the next request and the counter starts fresh.
#
# The counter is intentionally in-memory only (not persisted to disk).
# This is not a security flaw. The real controls are:
#   1. Code entropy: 31^8 ≈ 8.5×10^11 combinations
#   2. 15-minute expiry (timestamp lives on disk, restart-immune)
#   3. Single Flask worker: throughput ceiling ~10^5-10^6 requests in the window
# Against a 10^11.9 keyspace the success probability without any counter is
# already ~10^-6. The counter is defense-in-depth, not the primary control.
#
# On lockout (5 failures) the token file is deleted. Since the endpoint
# returns 404 when no file exists, lockout is atomic and persists across
# restarts. The operator re-runs `boxctl bootstrap` to mint a fresh token,
# which is the correct recovery path regardless.
#
# NOTE: this counter assumes a single daemon process. In a multi-worker setup
# each worker would have its own counter, giving N×5 attempts before any one
# worker triggers the unlink. The keyspace makes this a non-issue in practice,
# but the assumption should be revisited if the daemon is ever multi-process.
_current_uuid: str | None = None
_attempt_count: int = 0

_MAX_ATTEMPTS = 5
# Unambiguous characters - no 0/O, 1/I/L
_CODE_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
_CODE_LENGTH = 8
_TOKEN_TTL = 15 * 60  # 15 minutes


def token_file_path(env) -> str:
    return os.path.join(env['STORAGE_ROOT'], 'bootstrap.token')


def generate_token(env) -> tuple[str, int]:
    """
    Generate and persist a new bootstrap token.
    Returns (code, expires_at) where expires_at is a Unix timestamp.
    Any previous token is overwritten and the attempt counter is reset.
    """
    global _current_uuid, _attempt_count

    token_id = str(uuid.uuid4())
    code = ''.join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LENGTH))
    expires_at = int(time.time()) + _TOKEN_TTL

    data = {'uuid': token_id, 'code': code, 'expires': expires_at}

    path = token_file_path(env)
    tmp = path + '.tmp'
    # Mode 0600: root-only readable. The code is a credential - local unprivileged
    # users (mail accounts, www-data, etc.) must not be able to read it.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)

    _current_uuid = token_id
    _attempt_count = 0

    return code, expires_at


def _load_token(env) -> dict | None:
    try:
        with open(token_file_path(env)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def validate_code(code: str, env) -> tuple[bool, str]:
    """
    Validate a submitted bootstrap code.
    Returns (ok, error) where error is one of:
      ''               - success
      'not_found'      - no token file
      'expired'        - past expiry
      'locked'         - too many failed attempts (token file deleted)
      'invalid:N'      - wrong code, N attempts remaining
    """
    global _current_uuid, _attempt_count

    token = _load_token(env)
    if token is None:
        return False, 'not_found'

    # New token written by boxctl bootstrap - reset counter.
    if token['uuid'] != _current_uuid:
        _current_uuid = token['uuid']
        _attempt_count = 0

    if time.time() > token['expires']:
        return False, 'expired'

    if _attempt_count >= _MAX_ATTEMPTS:
        return False, 'locked'

    if not secrets.compare_digest(code.upper().strip(), token['code']):
        _attempt_count += 1
        if _attempt_count >= _MAX_ATTEMPTS:
            # Delete the token file so lockout persists across daemon restarts.
            # The endpoint returns 404 when no file exists, which is the correct
            # locked response. Operator re-runs `boxctl bootstrap` to recover.
            consume_token(env)
            return False, 'locked'
        remaining = _MAX_ATTEMPTS - _attempt_count
        return False, f'invalid:{remaining}'

    return True, ''


def consume_token(env) -> None:
    """Delete the token file and clear in-memory state."""
    global _current_uuid, _attempt_count
    _current_uuid = None
    _attempt_count = 0
    try:
        os.unlink(token_file_path(env))
    except FileNotFoundError:
        pass


def has_admin_users(env) -> bool:
    from mail.mailconfig.users import get_admins
    return len(get_admins(env)) > 0


def bootstrap_first_admin(email: str, password: str, env) -> str | tuple[str, int]:
    """
    Create the first admin user and the administrator@ alias. DB-only - no
    service sync or kick. Returns 'OK' on success or (message, status_code).
    """
    import sqlite3
    from mail.mailconfig.validation import validate_email, validate_password
    from mail.mailconfig.database import open_database
    from mail.mailconfig.users import hash_password

    if not validate_email(email, mode='user'):
        return ('Invalid email address.', 400)

    try:
        validate_password(password)
    except ValueError as e:
        return (str(e), 400)

    pw_hash = hash_password(password)
    administrator_alias = f"administrator@{env['PRIMARY_HOSTNAME']}"

    conn, c = open_database(env, with_connection=True)
    try:
        c.execute(
            "INSERT INTO users (email, password, privileges, quota) VALUES (?, ?, ?, ?)",
            (email, pw_hash, 'admin', '0'),
        )
        # administrator@ alias so auto-aliases (postmaster@, abuse@, etc.)
        # have a destination when kick() runs on the first config change.
        c.execute(
            "INSERT OR IGNORE INTO aliases (source, destination) VALUES (?, ?)",
            (administrator_alias, email),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return ('An admin user already exists.', 409)
    finally:
        conn.close()

    return 'OK'
