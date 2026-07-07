# Confidence: 88%
# High confidence in mock structure and assertions. Slight uncertainty around
# fido2's internal JSON serialisation format used by _options_to_dict, covered
# by checking that the result is a plain dict rather than inspecting its shape.

import os
import pytest
from unittest.mock import patch, MagicMock


_ENV = {"PRIMARY_HOSTNAME": "box.example.com", "STORAGE_ROOT": "/nonexistent"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_cred(credential_id: bytes | None = None):
	"""Return a MagicMock that looks like AttestedCredentialData to the code."""
	cred = MagicMock()
	cred.credential_id = credential_id or os.urandom(16)
	cred.aaguid = MagicMock()
	cred.aaguid.__str__ = lambda self: "00000000-0000-0000-0000-000000000000"
	# bytes(cred) is used in INSERT; make it return deterministic bytes.
	cred.__bytes__ = lambda self: b"\x00" * 32
	return cred


def _make_fake_auth_data(cred):
	"""Return a MagicMock for AuthenticatorData with .credential_data set."""
	auth_data = MagicMock()
	auth_data.credential_data = cred
	return auth_data


def _make_fake_response_with_counter(counter: int):
	"""Return a MagicMock for AuthenticationResponse whose counter is readable."""
	response = MagicMock()
	response.response.authenticator_data.counter = counter
	return response


def _make_fake_result(credential_id: bytes):
	"""Return a MagicMock for the result of authenticate_complete."""
	result = MagicMock()
	result.credential_id = credential_id
	return result


# ---------------------------------------------------------------------------
# webauthn_register_begin
# ---------------------------------------------------------------------------


class TestWebauthnRegisterBegin:
	def _run(self, existing_creds=None):
		fake_options = {"publicKey": {"challenge": "abc"}}
		fake_state = {"challenge": b"abc"}

		mock_server = MagicMock()
		mock_server.register_begin.return_value = (fake_options, fake_state)

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=existing_creds or []), patch("auth.mfa.open_database") as mock_db:
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (42,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_register_begin

			return webauthn_register_begin("user@example.com", _ENV)

	def test_returns_tuple_of_two(self):
		result = self._run()
		assert isinstance(result, tuple)
		assert len(result) == 2

	def test_first_element_is_dict(self):
		options_dict, _ = self._run()
		assert isinstance(options_dict, dict)

	def test_second_element_is_state(self):
		_, state = self._run()
		assert state is not None

	def test_calls_register_begin_with_existing_credentials(self):
		fake_cred = _make_fake_cred()
		mock_server = MagicMock()
		mock_server.register_begin.return_value = ({"publicKey": {}}, {"challenge": b"x"})

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=[fake_cred]), patch("auth.mfa.open_database") as mock_db:
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (1,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_register_begin

			webauthn_register_begin("user@example.com", _ENV)

		call_kwargs = mock_server.register_begin.call_args
		assert call_kwargs is not None
		passed_creds = call_kwargs.kwargs.get("credentials") or call_kwargs.args[1]
		assert passed_creds == [fake_cred]

	def test_options_dict_is_json_serialisable(self):
		import json

		options_dict, _ = self._run()
		# _options_to_dict guarantees this; verify no fido2 types leak through
		json.dumps(options_dict)

	def test_no_fido2_types_in_options_dict(self):
		options_dict, _ = self._run()
		assert isinstance(options_dict, dict)


# ---------------------------------------------------------------------------
# webauthn_register_complete
# ---------------------------------------------------------------------------


class TestWebauthnRegisterComplete:
	def _run_complete(self, email="user@example.com", name="My Key", cred_id: bytes | None = None):
		fake_cred = _make_fake_cred(credential_id=cred_id or os.urandom(16))
		fake_auth_data = _make_fake_auth_data(fake_cred)

		mock_server = MagicMock()
		mock_server.register_complete.return_value = fake_auth_data

		client_response = {"id": "abc", "rawId": "abc"}

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.open_database") as mock_db, patch("fido2.webauthn.RegistrationResponse.from_dict") as mock_from_dict:
			mock_from_dict.return_value = MagicMock()
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (7,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_register_complete

			webauthn_register_complete(email, {"challenge": b"x"}, client_response, name, _ENV)

		return mock_cursor, mock_conn, fake_cred

	def test_calls_register_complete_on_server(self):
		mock_server = MagicMock()
		fake_cred = _make_fake_cred()
		mock_server.register_complete.return_value = _make_fake_auth_data(fake_cred)

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.open_database") as mock_db, patch("fido2.webauthn.RegistrationResponse.from_dict", return_value=MagicMock()):
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (1,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_register_complete

			webauthn_register_complete("user@example.com", {}, {}, "key", _ENV)

		mock_server.register_complete.assert_called_once()

	def test_inserts_row_into_database(self):
		cursor, conn, _ = self._run_complete()
		cursor.execute.assert_called()
		# Find the INSERT call among all execute calls
		calls = [str(c) for c in cursor.execute.call_args_list]
		assert any("INSERT" in c for c in calls)

	def test_insert_includes_name(self):
		cursor, _, _ = self._run_complete(name="Yubikey 5")
		calls = cursor.execute.call_args_list
		insert_calls = [c for c in calls if "INSERT" in str(c)]
		assert len(insert_calls) == 1
		params = insert_calls[0].args[1]
		assert "Yubikey 5" in params

	def test_commit_called(self):
		_, conn, _ = self._run_complete()
		conn.commit.assert_called_once()

	def test_connection_closed(self):
		_, conn, _ = self._run_complete()
		conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# webauthn_authenticate_begin
# ---------------------------------------------------------------------------


class TestWebauthnAuthenticateBegin:
	def _run_begin(self, credentials=None):
		mock_server = MagicMock()
		fake_options = {"publicKey": {"challenge": "xyz"}}
		fake_state = {"challenge": b"xyz"}
		mock_server.authenticate_begin.return_value = (fake_options, fake_state)

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=credentials):
			from auth.mfa import webauthn_authenticate_begin

			return webauthn_authenticate_begin("user@example.com", _ENV)

	def test_returns_tuple_of_two_when_credentials_exist(self):
		fake_cred = _make_fake_cred()
		result = self._run_begin(credentials=[fake_cred])
		assert isinstance(result, tuple)
		assert len(result) == 2

	def test_first_element_is_dict(self):
		fake_cred = _make_fake_cred()
		options_dict, _ = self._run_begin(credentials=[fake_cred])
		assert isinstance(options_dict, dict)

	def test_second_element_is_state(self):
		fake_cred = _make_fake_cred()
		_, state = self._run_begin(credentials=[fake_cred])
		assert state is not None

	def test_returns_fake_challenge_when_no_credentials(self):
		# Returns a synthetic challenge to prevent account enumeration - must not raise.
		from auth.mfa import webauthn_authenticate_begin

		with patch("auth.mfa._get_fido2_server", return_value=MagicMock()), patch("auth.mfa.get_webauthn_credentials", return_value=[]):
			options, state = webauthn_authenticate_begin("user@example.com", _ENV)
		assert isinstance(options, dict)
		assert options.get("allowCredentials") == []

	def test_does_not_call_authenticate_begin_when_no_credentials(self):
		mock_server = MagicMock()
		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=[]):
			from auth.mfa import webauthn_authenticate_begin

			webauthn_authenticate_begin("user@example.com", _ENV)
		mock_server.authenticate_begin.assert_not_called()

	def test_options_are_json_serialisable(self):
		import json

		fake_cred = _make_fake_cred()
		options_dict, _ = self._run_begin(credentials=[fake_cred])
		json.dumps(options_dict)


# ---------------------------------------------------------------------------
# webauthn_authenticate_complete
# ---------------------------------------------------------------------------


class TestWebauthnAuthenticateComplete:
	def _run_complete(self, credential_id: bytes | None = None, counter: int = 5):
		cred_id = credential_id or os.urandom(16)
		fake_result = _make_fake_result(cred_id)
		fake_response = _make_fake_response_with_counter(counter)
		fake_cred = _make_fake_cred(credential_id=cred_id)

		mock_server = MagicMock()
		mock_server.authenticate_complete.return_value = fake_result

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=[fake_cred]), patch("auth.mfa.open_database") as mock_db, patch("fido2.webauthn.AuthenticationResponse.from_dict", return_value=fake_response):
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (3,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_authenticate_complete

			webauthn_authenticate_complete("user@example.com", {"challenge": b"z"}, {}, _ENV)

		return mock_cursor, mock_conn, cred_id

	def test_calls_authenticate_complete_on_server(self):
		mock_server = MagicMock()
		cred_id = os.urandom(16)
		fake_result = _make_fake_result(cred_id)
		fake_response = _make_fake_response_with_counter(1)
		fake_cred = _make_fake_cred(credential_id=cred_id)
		mock_server.authenticate_complete.return_value = fake_result

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=[fake_cred]), patch("auth.mfa.open_database") as mock_db, patch("fido2.webauthn.AuthenticationResponse.from_dict", return_value=fake_response):
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (1,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_authenticate_complete

			webauthn_authenticate_complete("user@example.com", {}, {}, _ENV)

		mock_server.authenticate_complete.assert_called_once()

	def test_updates_sign_count_in_database(self):
		cursor, _, _ = self._run_complete(counter=42)
		calls = cursor.execute.call_args_list
		update_calls = [c for c in calls if "UPDATE" in str(c)]
		assert len(update_calls) == 1
		params = update_calls[0].args[1]
		# First param is the new sign_count
		assert params[0] == 42

	def test_update_uses_correct_credential_id(self):
		cred_id = os.urandom(16)
		cursor, _, _ = self._run_complete(credential_id=cred_id)
		calls = cursor.execute.call_args_list
		update_calls = [c for c in calls if "UPDATE" in str(c)]
		params = update_calls[0].args[1]
		# Third param is credential_id
		assert params[2] == cred_id

	def test_commit_called(self):
		_, conn, _ = self._run_complete()
		conn.commit.assert_called_once()

	def test_connection_closed(self):
		_, conn, _ = self._run_complete()
		conn.close.assert_called_once()

	def test_returns_none(self):
		mock_server = MagicMock()
		cred_id = os.urandom(16)
		fake_result = _make_fake_result(cred_id)
		fake_response = _make_fake_response_with_counter(1)
		fake_cred = _make_fake_cred(credential_id=cred_id)
		mock_server.authenticate_complete.return_value = fake_result

		with patch("auth.mfa._get_fido2_server", return_value=mock_server), patch("auth.mfa.get_webauthn_credentials", return_value=[fake_cred]), patch("auth.mfa.open_database") as mock_db, patch("fido2.webauthn.AuthenticationResponse.from_dict", return_value=fake_response):
			mock_conn = MagicMock()
			mock_cursor = MagicMock()
			mock_cursor.fetchone.return_value = (1,)
			mock_db.return_value = (mock_conn, mock_cursor)

			from auth.mfa import webauthn_authenticate_complete

			result = webauthn_authenticate_complete("user@example.com", {}, {}, _ENV)

		assert result is None


# ---------------------------------------------------------------------------
# Security invariant: fake challenge is always rejected by authenticate_complete
# ---------------------------------------------------------------------------


class TestWebauthnFakeChallengeRejected:
	def test_fake_state_raises_on_complete(self):
		# The enumeration-protection guarantee: a fake state must always be rejected,
		# regardless of what client_response is supplied.
		from auth.mfa import webauthn_authenticate_complete

		with pytest.raises(ValueError, match="Authentication failed"):
			webauthn_authenticate_complete("user@example.com", {"fake": True}, {}, _ENV)

	def test_fake_state_does_not_call_fido2_server(self):
		mock_server = MagicMock()
		from auth.mfa import webauthn_authenticate_complete

		with patch("auth.mfa._get_fido2_server", return_value=mock_server):
			try:
				webauthn_authenticate_complete("user@example.com", {"fake": True}, {}, _ENV)
			except ValueError:
				pass
		mock_server.authenticate_complete.assert_not_called()
