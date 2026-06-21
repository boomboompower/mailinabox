import os
import sqlite3

_DB_SUBPATH = "/mail/db/users.sqlite"

def initialize_database(env):
	# Create tables if they don't exist. Called once at daemon startup and
	# once from users.sh during setup.
	db_path = env["STORAGE_ROOT"] + _DB_SUBPATH
	conn = sqlite3.connect(db_path)
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
		CREATE TABLE IF NOT EXISTS api_tokens (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER NOT NULL,
			name TEXT NOT NULL,
			token_hash TEXT NOT NULL UNIQUE,
			scope TEXT NOT NULL DEFAULT 'read',
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			last_used TEXT,
			FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
		);
	""")
	conn.commit()
	conn.close()
	# SQLite copies the database file's mode when creating -shm, so setting
	# 660 here ensures all future -shm files are group-writable for mail-db
	# members (postfix proxymap, dovecot auth-workers) without any further
	# intervention regardless of which process creates -shm first.
	os.chmod(db_path, 0o660)

def open_database(env, with_connection=False):
	conn = sqlite3.connect(env["STORAGE_ROOT"] + _DB_SUBPATH)
	conn.execute("PRAGMA foreign_keys = ON")
	if not with_connection:
		return conn.cursor()
	return conn, conn.cursor()
