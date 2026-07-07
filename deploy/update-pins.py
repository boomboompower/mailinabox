#!/usr/bin/env python3
"""
Check and update pinned dependency versions.

Run from anywhere in the repo:
    python3 tools/update-pins.py

Requires no third-party packages. Hits the GitHub API (60 req/hr unauthenticated).
Set GITHUB_TOKEN env var to raise the limit.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── ANSI ──────────────────────────────────────────────────────────────────────

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(s):
	return f"{GREEN}{s}{RESET}"


def _warn(s):
	return f"{YELLOW}{s}{RESET}"


def _err(s):
	return f"{RED}{s}{RESET}"


def _bold(s):
	return f"{BOLD}{s}{RESET}"


def _dim(s):
	return f"{DIM}{s}{RESET}"


# ── GitHub helpers ────────────────────────────────────────────────────────────


def _gh(path: str) -> dict:
	url = f"https://api.github.com/{path}"
	req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
	token = os.environ.get("GITHUB_TOKEN")
	if token:
		req.add_header("Authorization", f"Bearer {token}")
	with urllib.request.urlopen(req, timeout=15) as r:
		return json.load(r)


def _latest_release(owner: str, repo: str) -> str:
	return _gh(f"repos/{owner}/{repo}/releases/latest")["tag_name"]


def _latest_commit(owner: str, repo: str, branch: str = "master") -> str:
	return _gh(f"repos/{owner}/{repo}/commits/{branch}")["sha"]


# ── File helpers ──────────────────────────────────────────────────────────────


def _read_var(rel_path: str, var: str) -> str:
	path = os.path.join(REPO_ROOT, rel_path)
	with open(path) as f:
		content = f.read()
	m = re.search(rf'^{re.escape(var)}\s*=\s*"([^"]*)"', content, re.MULTILINE)
	if not m:
		raise ValueError(f"{var} not found in {rel_path}")
	return m.group(1)


def _update_var(rel_path: str, var: str, value: str) -> None:
	path = os.path.join(REPO_ROOT, rel_path)
	with open(path) as f:
		content = f.read()
	new = re.sub(
		rf'^({re.escape(var)}\s*=\s*")[^"]*(")',
		rf'\g<1>{value}\2',
		content,
		flags=re.MULTILINE,
	)
	if new == content:
		raise ValueError(f"No substitution made for {var} in {rel_path}")
	with open(path, "w") as f:
		f.write(new)


# ── Download + hash ───────────────────────────────────────────────────────────


def _sha256(path: str) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(65536), b""):
			h.update(chunk)
	return h.hexdigest()


def _download_sha256(url: str) -> str:
	"""Download url to a temp file, return its SHA256."""
	print(f"    {_dim('fetching')} {os.path.basename(url)} ...", end=" ", flush=True)
	suffix = "_" + os.path.basename(url.split("?")[0])
	fd, tmp = tempfile.mkstemp(suffix=suffix)
	os.close(fd)
	try:
		urllib.request.urlretrieve(url, tmp)
		digest = _sha256(tmp)
		print(_ok("done"))
		return digest
	finally:
		os.unlink(tmp)


# ── Pin registry ──────────────────────────────────────────────────────────────


@dataclass
class Asset:
	"""One downloadable artifact: which constant holds its SHA256, and how to build its URL."""

	sha_var: str
	url: str  # use {version} as placeholder - replaced at update time


@dataclass
class Pin:
	name: str
	file: str  # path relative to repo root
	version_var: str  # constant name for the version/commit
	assets: list  # list[Asset]
	# Returns the canonical version string to write to the file.
	# For release-pinned deps: latest tag (normalised to match stored format).
	# For commit-pinned deps: full commit SHA.
	get_latest: object  # callable () -> str


PINS = [
	Pin(
		name="Beszel",
		file="setup/components/defs/optional/beszel.py",
		version_var="_BESZEL_VERSION",
		assets=[
			Asset("_BESZEL_HUB_SHA256", "https://github.com/henrygd/beszel/releases/download/v{version}/beszel_linux_amd64.tar.gz"),
			Asset("_BESZEL_AGENT_SHA256", "https://github.com/henrygd/beszel/releases/download/v{version}/beszel-agent_linux_amd64.tar.gz"),
		],
		get_latest=lambda: _latest_release("henrygd", "beszel").lstrip("v"),
	),
	Pin(
		name="Cypht",
		file="setup/components/defs/webmail/cypht.py",
		version_var="CYPHT_COMMIT",
		assets=[
			Asset("CYPHT_SHA256", "https://github.com/cypht-org/cypht/archive/{version}.tar.gz"),
		],
		get_latest=lambda: _latest_commit("cypht-org", "cypht"),
	),
	Pin(
		name="Roundcube",
		file="setup/components/defs/webmail/roundcube.py",
		version_var="ROUNDCUBE_VERSION",
		assets=[
			Asset("ROUNDCUBE_SHA256", "https://github.com/roundcube/roundcubemail/releases/download/{version}/roundcubemail-{version}-complete.tar.gz"),
		],
		get_latest=lambda: _latest_release("roundcube", "roundcubemail"),
	),
	Pin(
		name="rcmcarddav",
		file="setup/components/defs/webmail/roundcube.py",
		version_var="RCMCARDDAV_VERSION",
		assets=[
			Asset("RCMCARDDAV_SHA256", "https://github.com/mstilkerich/rcmcarddav/releases/download/v{version}/carddav-v{version}.tar.gz"),
		],
		get_latest=lambda: _latest_release("mstilkerich", "rcmcarddav").lstrip("v"),
	),
	Pin(
		name="FileBrowser",
		file="setup/components/defs/optional/filebrowser.py",
		version_var="FB_VERSION",
		assets=[
			Asset("FB_SHA256", "https://github.com/filebrowser/filebrowser/releases/download/{version}/linux-amd64-filebrowser.tar.gz"),
		],
		get_latest=lambda: _latest_release("filebrowser", "filebrowser"),
	),
	Pin(
		name="restic",
		file="setup/components/defs/backup/restic.py",
		version_var="_RESTIC_VERSION",
		assets=[
			Asset("_RESTIC_SHA256", "https://github.com/restic/restic/releases/download/v{version}/restic_{version}_linux_amd64.bz2"),
		],
		get_latest=lambda: _latest_release("restic", "restic").lstrip("v"),
	),
	Pin(
		name="Oxi",
		file="setup/components/defs/webmail/oxi.py",
		version_var="OXI_VERSION",
		assets=[
			Asset("OXI_SHA256", "https://github.com/boomboompower/oxi-miab/releases/download/{version}/oxi-email-server-linux-x86_64.tar.gz"),
		],
		get_latest=lambda: _latest_release("boomboompower", "oxi-miab"),
	)
]


# ── Core logic ────────────────────────────────────────────────────────────────


def _display(v: str, max_len: int = 12) -> str:
	"""Truncate long commit hashes for display."""
	return v[:max_len] if len(v) > max_len else v


def check_all() -> list[tuple]:
	"""Return list of (pin, current, latest, is_outdated) for all pins."""
	results = []
	for pin in PINS:
		current = _read_var(pin.file, pin.version_var)
		print(f"  checking {pin.name} ...", end=" ", flush=True)
		try:
			latest = pin.get_latest()
			outdated = current != latest
			print(_warn("UPDATE AVAILABLE") if outdated else _ok("ok"))
		except Exception as e:
			latest = None
			outdated = False
			print(_err(f"error: {e}"))
		results.append((pin, current, latest, outdated))
	return results


def print_table(results: list[tuple]) -> None:
	col = [18, 14, 14, 16]
	header = ["Dependency", "Pinned", "Latest", "Status"]
	sep = "  " + "-" * (sum(col) + len(col) * 2)
	print()
	print("  " + "  ".join(h.ljust(col[i]) for i, h in enumerate(header)))
	print(sep)
	for i, (pin, current, latest, outdated) in enumerate(results):
		status = _warn("! UPDATE") if outdated else (_err("? error") if latest is None else _ok("+ ok"))
		row = [
			f"{i + 1}. {pin.name}",
			_display(current),
			_display(latest) if latest else _err("failed"),
			status,
		]
		print("  " + "  ".join(str(v).ljust(col[j]) for j, v in enumerate(row)))
	print()


def do_update(pin: Pin, latest: str) -> None:
	print(f"\n  {_bold('Updating')} {pin.name} to {latest}")
	hashes = {}
	for asset in pin.assets:
		url = asset.url.replace("{version}", latest)
		hashes[asset.sha_var] = _download_sha256(url)

	_update_var(pin.file, pin.version_var, latest)
	for sha_var, digest in hashes.items():
		_update_var(pin.file, sha_var, digest)

	print(f"  {_ok('Updated')} {pin.file}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
	print(f"\n{_bold('Dependency pin checker')}")
	print(_dim(f"repo: {REPO_ROOT}\n"))

	print("Checking latest versions...")
	results = check_all()
	print_table(results)

	outdated = [(i, pin, current, latest) for i, (pin, current, latest, out) in enumerate(results) if out]

	if not outdated:
		print(_ok("All pins are current."))
		return

	print(f"{_warn(str(len(outdated)))} update(s) available.")
	indices = ", ".join(str(i + 1) for i, *_ in outdated)
	raw = input(f"\nUpdate which? (numbers e.g. {indices}, 'all', or Enter to skip): ").strip()

	if not raw:
		print("Skipped.")
		return

	if raw.lower() == "all":
		selected = [i for i, *_ in outdated]
	else:
		try:
			selected = [int(x.strip()) - 1 for x in raw.replace(",", " ").split()]
		except ValueError:
			print(_err("Invalid input."))
			sys.exit(1)

	for idx in selected:
		pin, _, latest, _ = results[idx][0], results[idx][1], results[idx][2], results[idx][3]
		do_update(pin, latest)

	print(f"\n{_ok('Done.')} Review the changes with git diff before committing.\n")


if __name__ == "__main__":
	main()
