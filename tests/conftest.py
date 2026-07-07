# Global fixtures - component and management fixtures live in their own conftest.py files.

# passlib 1.7.4 detects the bcrypt "wrap bug" using a >72-byte test password.
# bcrypt 5.x enforces a hard 72-byte limit and raises ValueError instead of
# silently truncating - which causes passlib's backend detection to crash on
# first use. Old bcrypt silently truncated at 72 bytes; we restore that behavior
# for tests only so passlib's detection completes without error.
import bcrypt as _bcrypt_lib

_orig_hashpw = _bcrypt_lib.hashpw


def _compat_hashpw(password: bytes, salt: bytes) -> bytes:
	if isinstance(password, bytes) and len(password) > 72:
		password = password[:72]
	return _orig_hashpw(password, salt)


_bcrypt_lib.hashpw = _compat_hashpw
