"""Integration tests for auth/mfa.py.

Covers TOTP enable/disable, replay protection, get_mfa_state, and
validate_auth_mfa with both no-MFA and TOTP-enrolled users.
"""

import base64
import secrets

import pyotp
import pytest

from unittest.mock import patch, MagicMock

_KICK_USERS = "mail.mailconfig.sync.kick"
_DOVEADM = "mail.mailconfig.users.dovecot_quota_recalc"


def _make_totp_secret() -> str:
	"""Return a valid 32-char base32 TOTP secret."""
	raw = secrets.token_bytes(20)
	encoded = base64.b32encode(raw).decode().rstrip("=")
	# Pad to exactly 32 characters (validation requires len == 32).
	return encoded.ljust(32, "A")[:32]


def _current_totp_code(secret: str) -> str:
	return pyotp.TOTP(secret).now()


def _add_user(email, env, pw="Password123!"):
	with patch(_KICK_USERS, return_value="ok"), patch(_DOVEADM):
		from mail.mailconfig.users import add_mail_user

		return add_mail_user(email, pw, "", "0", env)


def _enable_mfa(email, env):
	"""Helper that enables TOTP for a user. Returns (secret, mfa_id)."""
	secret = _make_totp_secret()
	code = _current_totp_code(secret)
	from auth.mfa import enable_mfa, get_mfa_state

	enable_mfa(email, "totp", secret, code, "test-label", env)
	state = get_mfa_state(email, env)
	return secret, state[0]["id"]


# ---------------------------------------------------------------------------
# enable_mfa
# ---------------------------------------------------------------------------


def test_enable_mfa_totp_succeeds(test_db):
	_add_user("mfauser@example.com", test_db)
	secret = _make_totp_secret()
	code = _current_totp_code(secret)
	from auth.mfa import enable_mfa

	# Should not raise.
	enable_mfa("mfauser@example.com", "totp", secret, code, "label", test_db)


def test_enable_mfa_wrong_code_raises(test_db):
	_add_user("wrongcode@example.com", test_db)
	secret = _make_totp_secret()
	from auth.mfa import enable_mfa

	with pytest.raises(ValueError, match="Invalid token"):
		enable_mfa("wrongcode@example.com", "totp", secret, "000000", "label", test_db)


def test_enable_mfa_short_secret_raises(test_db):
	_add_user("shortsec@example.com", test_db)
	from auth.mfa import enable_mfa

	with pytest.raises(ValueError):
		enable_mfa("shortsec@example.com", "totp", "tooshort", "000000", "label", test_db)


def test_enable_mfa_invalid_type_raises(test_db):
	_add_user("badtype@example.com", test_db)
	secret = _make_totp_secret()
	from auth.mfa import enable_mfa

	with pytest.raises(ValueError, match="Invalid MFA type"):
		enable_mfa("badtype@example.com", "sms", secret, "000000", "label", test_db)


# ---------------------------------------------------------------------------
# get_mfa_state
# ---------------------------------------------------------------------------


def test_get_mfa_state_returns_enrolled_row(test_db):
	_add_user("getstate@example.com", test_db)
	secret, mfa_id = _enable_mfa("getstate@example.com", test_db)
	from auth.mfa import get_mfa_state

	state = get_mfa_state("getstate@example.com", test_db)
	assert len(state) == 1
	row = state[0]
	assert row["id"] == mfa_id
	assert row["type"] == "totp"
	assert row["secret"] == secret
	assert row["label"] == "test-label"


def test_get_mfa_state_empty_when_no_mfa(test_db):
	_add_user("nomfa@example.com", test_db)
	from auth.mfa import get_mfa_state

	state = get_mfa_state("nomfa@example.com", test_db)
	assert state == []


# ---------------------------------------------------------------------------
# consume_totp_step - replay protection
# ---------------------------------------------------------------------------


def test_consume_totp_step_returns_true_for_current_step(test_db):
	_add_user("consume@example.com", test_db)
	_, mfa_id = _enable_mfa("consume@example.com", test_db)
	from auth.mfa import consume_totp_step

	result = consume_totp_step("consume@example.com", mfa_id, test_db)
	assert result is True


def test_consume_totp_step_returns_false_on_replay(test_db):
	_add_user("replay@example.com", test_db)
	_, mfa_id = _enable_mfa("replay@example.com", test_db)
	from auth.mfa import consume_totp_step

	# First consumption should succeed.
	assert consume_totp_step("replay@example.com", mfa_id, test_db) is True
	# Second call in the same step - replay.
	assert consume_totp_step("replay@example.com", mfa_id, test_db) is False


# ---------------------------------------------------------------------------
# validate_auth_mfa
# ---------------------------------------------------------------------------


def _make_request(totp_code=None):
	req = MagicMock()
	if totp_code is not None:
		req.headers = {"x-auth-token": totp_code}
	else:
		req.headers = {}
	return req


def test_validate_auth_mfa_no_mfa_enrolled_returns_true(test_db):
	_add_user("nomfaauth@example.com", test_db)
	from auth.mfa import validate_auth_mfa

	ok, hints = validate_auth_mfa("nomfaauth@example.com", _make_request(), test_db)
	assert ok is True
	assert hints == []


def test_validate_auth_mfa_totp_enrolled_no_token_returns_false_with_hint(test_db):
	_add_user("enrolled@example.com", test_db)
	_enable_mfa("enrolled@example.com", test_db)
	from auth.mfa import validate_auth_mfa

	ok, hints = validate_auth_mfa("enrolled@example.com", _make_request(totp_code=None), test_db)
	assert ok is False
	assert "missing-totp-token" in hints


def test_validate_auth_mfa_totp_enrolled_valid_token_returns_true(test_db):
	_add_user("validtotp@example.com", test_db)
	secret, _ = _enable_mfa("validtotp@example.com", test_db)
	code = _current_totp_code(secret)
	from auth.mfa import validate_auth_mfa

	ok, hints = validate_auth_mfa("validtotp@example.com", _make_request(totp_code=code), test_db)
	assert ok is True
	assert hints == []


# ---------------------------------------------------------------------------
# disable_mfa
# ---------------------------------------------------------------------------


def test_disable_mfa_none_removes_all_mfa(test_db):
	_add_user("disableall@example.com", test_db)
	_enable_mfa("disableall@example.com", test_db)

	from auth.mfa import disable_mfa, get_mfa_state

	disable_mfa("disableall@example.com", None, test_db)
	state = get_mfa_state("disableall@example.com", test_db)
	assert state == []


def test_disable_mfa_specific_id_removes_only_that_entry(test_db):
	_add_user("disableone@example.com", test_db)
	secret1, id1 = _enable_mfa("disableone@example.com", test_db)
	# Add a second TOTP entry.
	secret2 = _make_totp_secret()
	code2 = _current_totp_code(secret2)
	from auth.mfa import enable_mfa, disable_mfa, get_mfa_state

	enable_mfa("disableone@example.com", "totp", secret2, code2, "second", test_db)

	disable_mfa("disableone@example.com", id1, test_db)
	state = get_mfa_state("disableone@example.com", test_db)
	assert len(state) == 1
	assert state[0]["secret"] == secret2
