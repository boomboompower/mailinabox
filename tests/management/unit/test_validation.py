import pytest
from mail.mailconfig.validation import (
	validate_email,
	sanitize_idn_email_address,
	prettify_idn_email_address,
	is_dcv_address,
	get_domain,
	validate_password,
	validate_quota,
	parse_privs,
	validate_privilege,
)


# ---------------------------------------------------------------------------
# validate_email
# ---------------------------------------------------------------------------


class TestValidateEmail:
	def test_valid_ascii_email_no_mode(self):
		assert validate_email("user@example.com") is True

	def test_valid_ascii_email_user_mode(self):
		assert validate_email("user@example.com", mode='user') is True

	def test_valid_numbers_and_dash_user_mode(self):
		assert validate_email("user-123@example.com", mode='user') is True

	def test_valid_underscore_user_mode(self):
		assert validate_email("user_name@example.com", mode='user') is True

	def test_user_mode_rejects_uppercase_local(self):
		assert validate_email("User@example.com", mode='user') is False

	def test_user_mode_rejects_all_uppercase(self):
		assert validate_email("USER@EXAMPLE.COM", mode='user') is False

	def test_user_mode_rejects_mixed_case_local(self):
		assert validate_email("testUser@example.com", mode='user') is False

	def test_alias_mode_allows_catch_all(self):
		assert validate_email("@example.com", mode='alias') is True

	def test_alias_mode_allows_normal_address(self):
		assert validate_email("user@example.com", mode='alias') is True

	def test_rejects_missing_at(self):
		assert validate_email("userexample.com") is False

	def test_rejects_empty_string(self):
		assert validate_email("") is False

	def test_rejects_over_255_chars_user_mode(self):
		local = "a" * 244
		addr = f"{local}@example.com"
		assert len(addr) > 255
		assert validate_email(addr, mode='user') is False

	def test_valid_subdomain(self):
		assert validate_email("user@mail.example.com", mode='user') is True

	def test_rejects_slash_in_local_user_mode(self):
		assert validate_email("user/name@example.com", mode='user') is False


# ---------------------------------------------------------------------------
# sanitize_idn_email_address / prettify_idn_email_address
# ---------------------------------------------------------------------------


class TestIdnEmailRoundtrip:
	def test_unicode_domain_sanitized_to_ascii(self):
		result = sanitize_idn_email_address("user@例え.jp")
		assert "@" in result
		localpart, domain = result.split("@")
		assert localpart == "user"
		assert domain == domain.encode("ascii").decode("ascii")

	def test_ascii_domain_unchanged(self):
		assert sanitize_idn_email_address("user@example.com") == "user@example.com"

	def test_non_email_string_returns_unchanged(self):
		assert sanitize_idn_email_address("notanemail") == "notanemail"

	def test_prettify_ascii_domain_unchanged(self):
		assert prettify_idn_email_address("user@example.com") == "user@example.com"

	def test_prettify_non_email_returns_unchanged(self):
		assert prettify_idn_email_address("notanemail") == "notanemail"

	def test_sanitize_then_prettify_roundtrip(self):
		original = "user@例え.jp"
		sanitized = sanitize_idn_email_address(original)
		prettified = prettify_idn_email_address(sanitized)
		assert prettified == original


# ---------------------------------------------------------------------------
# is_dcv_address
# ---------------------------------------------------------------------------


class TestIsDcvAddress:
	def test_admin_is_dcv(self):
		assert is_dcv_address("admin@example.com") is True

	def test_postmaster_is_dcv(self):
		assert is_dcv_address("postmaster@example.com") is True

	def test_abuse_is_dcv(self):
		assert is_dcv_address("abuse@example.com") is True

	def test_hostmaster_is_dcv(self):
		assert is_dcv_address("hostmaster@example.com") is True

	def test_webmaster_is_dcv(self):
		assert is_dcv_address("webmaster@example.com") is True

	def test_administrator_is_dcv(self):
		assert is_dcv_address("administrator@example.com") is True

	def test_admin_uppercase_is_dcv(self):
		assert is_dcv_address("ADMIN@example.com") is True

	def test_postmaster_mixed_case_is_dcv(self):
		assert is_dcv_address("Postmaster@example.com") is True

	def test_admin_tagged_is_dcv(self):
		# is_dcv_address checks startswith(localpart + "+"), so admin+ matches
		assert is_dcv_address("admin+tagged@example.com") is True

	def test_regular_user_not_dcv(self):
		assert is_dcv_address("user@example.com") is False

	def test_partial_match_not_dcv(self):
		assert is_dcv_address("adminfoo@example.com") is False


# ---------------------------------------------------------------------------
# get_domain
# ---------------------------------------------------------------------------


class TestGetDomain:
	def test_extracts_plain_domain(self):
		assert get_domain("user@example.com") == "example.com"

	def test_extracts_subdomain(self):
		assert get_domain("user@mail.example.com") == "mail.example.com"

	def test_prettifies_idna_by_default(self):
		sanitized = sanitize_idn_email_address("user@例え.jp")
		domain = get_domain(sanitized, as_unicode=True)
		assert domain == "例え.jp"

	def test_returns_ascii_when_as_unicode_false(self):
		sanitized = sanitize_idn_email_address("user@例え.jp")
		domain = get_domain(sanitized, as_unicode=False)
		assert domain == domain.encode("ascii").decode("ascii")


# ---------------------------------------------------------------------------
# validate_password
# ---------------------------------------------------------------------------


class TestValidatePassword:
	def test_empty_string_raises(self):
		with pytest.raises(ValueError):
			validate_password("")

	def test_whitespace_only_raises(self):
		with pytest.raises(ValueError):
			validate_password("   ")

	def test_seven_chars_raises(self):
		with pytest.raises(ValueError):
			validate_password("1234567")

	def test_eight_chars_valid(self):
		validate_password("12345678")

	def test_longer_password_valid(self):
		validate_password("a-very-long-password-that-is-definitely-valid")


# ---------------------------------------------------------------------------
# validate_quota
# ---------------------------------------------------------------------------


class TestValidateQuota:
	def test_megabyte_quota_valid(self):
		assert validate_quota("100M") == "100M"

	def test_gigabyte_quota_valid(self):
		assert validate_quota("1G") == "1G"

	def test_zero_quota_valid(self):
		assert validate_quota("0") == "0"

	def test_lowercase_m_uppercased(self):
		# validate_quota does .upper() before checking, so "100m" becomes "100M"
		assert validate_quota("100m") == "100M"

	def test_comma_in_quota_raises(self):
		with pytest.raises(ValueError):
			validate_quota("1,000M")

	def test_decimal_in_quota_raises(self):
		with pytest.raises(ValueError):
			validate_quota("1.5G")

	def test_empty_quota_raises(self):
		with pytest.raises(ValueError):
			validate_quota("")

	def test_space_in_quota_raises(self):
		with pytest.raises(ValueError):
			validate_quota("100 M")

	def test_plain_number_valid(self):
		assert validate_quota("512") == "512"


# ---------------------------------------------------------------------------
# parse_privs / validate_privilege
# ---------------------------------------------------------------------------


class TestParsePrivs:
	def test_splits_on_newlines(self):
		assert parse_privs("admin\nread") == ["admin", "read"]

	def test_filters_empty_lines(self):
		assert parse_privs("admin\n\nread\n") == ["admin", "read"]

	def test_empty_string_returns_empty_list(self):
		assert parse_privs("") == []

	def test_single_priv(self):
		assert parse_privs("admin") == ["admin"]

	def test_whitespace_only_lines_filtered(self):
		result = parse_privs("admin\n   \nread")
		assert result == ["admin", "read"]


class TestValidatePrivilege:
	def test_valid_privilege_returns_none(self):
		assert validate_privilege("admin") is None

	def test_newline_in_privilege_returns_error(self):
		result = validate_privilege("admin\nwrite")
		assert result is not None
		assert result[1] == 400

	def test_empty_privilege_returns_error(self):
		result = validate_privilege("")
		assert result is not None
		assert result[1] == 400

	def test_whitespace_only_privilege_returns_error(self):
		result = validate_privilege("   ")
		assert result is not None
		assert result[1] == 400
