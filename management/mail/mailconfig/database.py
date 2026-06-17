import sqlite3

def initialize_database(env):
	# Create tables if they don't exist. Called once at daemon startup.
	conn = sqlite3.connect(env["STORAGE_ROOT"] + "/mail/users.sqlite")
	conn.executescript("""
		PRAGMA journal_mode=WAL;
		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			email TEXT NOT NULL UNIQUE,
			password TEXT NOT NULL,
			extra,
			privileges TEXT NOT NULL DEFAULT '',
			quota TEXT NOT NULL DEFAULT '0'
		);
		CREATE TABLE IF NOT EXISTS aliases (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			source TEXT NOT NULL UNIQUE,
			destination TEXT NOT NULL,
			permitted_senders TEXT
		);
		CREATE TABLE IF NOT EXISTS mfa (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER NOT NULL,
			type TEXT NOT NULL,
			secret TEXT NOT NULL,
			mru_token TEXT,
			label TEXT,
			FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
		);
		CREATE TABLE IF NOT EXISTS auto_aliases (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			source TEXT NOT NULL UNIQUE,
			destination TEXT NOT NULL,
			permitted_senders TEXT
		);
		CREATE TABLE IF NOT EXISTS webauthn_credentials (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER NOT NULL,
			credential_id BLOB NOT NULL UNIQUE,
			public_key BLOB NOT NULL,
			sign_count INTEGER NOT NULL DEFAULT 0,
			aaguid TEXT,
			name TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			last_used TEXT,
			FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
		);
	""")
	conn.commit()
	conn.close()

def open_database(env, with_connection=False):
	conn = sqlite3.connect(env["STORAGE_ROOT"] + "/mail/users.sqlite")
	if not with_connection:
		return conn.cursor()
	return conn, conn.cursor()
