import pytest


@pytest.fixture
def test_db(tmp_path):
	env = {"STORAGE_ROOT": str(tmp_path)}
	from mail.mailconfig.database import initialize_database

	initialize_database(env)
	return env
