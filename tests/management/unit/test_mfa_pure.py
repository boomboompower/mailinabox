import pytest
from unittest.mock import patch
from auth.mfa import validate_totp_secret, provision_totp


# ---------------------------------------------------------------------------
# validate_totp_secret
# ---------------------------------------------------------------------------


class TestValidateTotpSecret:
	def test_valid_32_char_base32_string(self):
		secret = "JBSWY3DPEHPK3PXP" * 2  # 32 chars of valid base32
		validate_totp_secret(secret)

	def test_31_chars_raises(self):
		secret = "A" * 31
		with pytest.raises(ValueError):
			validate_totp_secret(secret)

	def test_33_chars_raises(self):
		secret = "A" * 33
		with pytest.raises(ValueError):
			validate_totp_secret(secret)

	def test_empty_string_raises(self):
		with pytest.raises(ValueError):
			validate_totp_secret("")

	def test_whitespace_only_raises(self):
		with pytest.raises(ValueError):
			validate_totp_secret("   ")

	def test_non_string_raises(self):
		with pytest.raises((ValueError, TypeError, AttributeError)):
			validate_totp_secret(None)

	def test_exact_32_chars_valid(self):
		# Any 32-char string passes the length check (secret validation is length-only here)
		secret = "B" * 32
		validate_totp_secret(secret)


# ---------------------------------------------------------------------------
# provision_totp
# ---------------------------------------------------------------------------


class TestProvisionTotp:
	def _make_env(self):
		return {"PRIMARY_HOSTNAME": "box.example.com"}

	def test_returns_dict_with_secret(self):
		result = provision_totp("user@example.com", self._make_env())
		assert "secret" in result
		assert isinstance(result["secret"], str)

	def test_secret_is_32_chars(self):
		result = provision_totp("user@example.com", self._make_env())
		assert len(result["secret"]) == 32

	def test_returns_qr_code_base64(self):
		result = provision_totp("user@example.com", self._make_env())
		assert "qr_code_base64" in result
		assert isinstance(result["qr_code_base64"], str)
		assert len(result["qr_code_base64"]) > 0

	def test_type_field_is_totp(self):
		result = provision_totp("user@example.com", self._make_env())
		assert result["type"] == "totp"

	def test_no_database_calls(self):
		# provision_totp must not touch the DB
		with patch('auth.mfa.open_database') as mock_db:
			provision_totp("user@example.com", self._make_env())
			mock_db.assert_not_called()

	def test_secret_passes_validate_totp_secret(self):
		result = provision_totp("user@example.com", self._make_env())
		# Should not raise
		validate_totp_secret(result["secret"])

	def test_each_call_produces_different_secret(self):
		env = self._make_env()
		r1 = provision_totp("user@example.com", env)
		r2 = provision_totp("user@example.com", env)
		assert r1["secret"] != r2["secret"]
