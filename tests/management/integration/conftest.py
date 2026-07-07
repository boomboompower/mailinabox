import os
import pytest


@pytest.fixture
def test_db(tmp_path):
	# The DB lives at STORAGE_ROOT/mail/db/users.sqlite - create the parent dirs
	# before initialize_database tries to open the file.
	os.makedirs(str(tmp_path / "mail" / "db"), exist_ok=True)
	env = {"STORAGE_ROOT": str(tmp_path), "PRIMARY_HOSTNAME": "box.example.com"}
	from mail.mailconfig.database import initialize_database

	initialize_database(env)
	return env
