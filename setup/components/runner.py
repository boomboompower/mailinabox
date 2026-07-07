"""
Component runner. Discovers all modules under defs/ (including subdirectories),
installs packages, runs doit for build steps, then restarts services.

Each defs module must expose:
  COMPONENT: Component
  make_tasks(env: dict, runtime: str) -> list[dict]  # doit task dicts

Modules without both attributes (e.g. shared __init__.py helpers) are silently
skipped - they are not components.

Task names within make_tasks() should be short step names ('keys', 'configure').
The runner groups them under the component name so doit sees 'dns:keys' etc.

uptodate conventions:
  [config_changed(VERSION)]  - versioned artifact (re-run when version changes)
  [run_once]                 - generate once, never re-run (e.g. DNSSEC keys)
  targets=['/path']          - re-run if output file is missing
  [False]                    - always run (configure steps)
"""

import importlib
import logging
import os
import pkgutil
import sqlite3
import subprocess
import sys
import types
from collections import defaultdict
from typing import Callable

import fcntl

from .component import Component, BAREMETAL, DOCKER
from . import packages as pkg

log = logging.getLogger(__name__)

STATE_DB = "/usr/local/lib/mailinabox/setup-state.db"

# Keys doit recognises in task dicts. Used to strip our own metadata (e.g.
# "build") before passing tasks to doit, which rejects unknown fields.
_DOIT_KEYS = frozenset([
	"name",
	"actions",
	"file_dep",
	"task_dep",
	"targets",
	"uptodate",
	"verbosity",
	"title",
	"doc",
	"clean",
	"teardown",
	"setup",
	"calc_dep",
	"getargs",
	"watch",
	"pos_arg",
])


# ── Discovery ─────────────────────────────────────────────────────────────────


def _discover() -> list[tuple[Component, Callable]]:
	"""Import every module under defs/ (recursive) and collect (COMPONENT, make_tasks) pairs.

	Modules missing COMPONENT or make_tasks are silently skipped - they are
	shared helpers, not components (e.g. backup/__init__.py).
	Raises on any import error.
	"""
	from . import defs as defs_pkg

	result = []
	errors = []
	for _, modname, ispkg in pkgutil.walk_packages(defs_pkg.__path__, defs_pkg.__name__ + "."):
		if ispkg:
			# Sub-packages (webmail/, filter/, etc.) are namespace containers,
			# not components themselves - skip and let walk_packages descend into them.
			continue
		try:
			mod = importlib.import_module(modname)
		except Exception as e:
			errors.append(f"{modname}: {e}")
			continue
		if not hasattr(mod, "COMPONENT") or not hasattr(mod, "make_tasks"):
			# Shared helper module (e.g. backup/__init__.py) - not a component.
			continue
		result.append((mod.COMPONENT, mod.make_tasks))
	if errors:
		raise ImportError("Component modules failed to load:\n" + "\n".join(errors))
	result.sort(key=lambda pair: (pair[0].port_order, pair[0].name))
	return result


# ── Doit integration ──────────────────────────────────────────────────────────


def _make_reporter_class(ran: set[str]) -> type:
	"""Return a ConsoleReporter subclass that records which components ran tasks."""
	from doit.reporter import ConsoleReporter

	class _Reporter(ConsoleReporter):
		def add_success(self, task):
			super().add_success(task)
			# Only subtasks have ":" in their name. The parent group task (the
			# generator itself) always calls add_success once all subtasks finish,
			# even when every subtask was up-to-date. Tracking only subtasks gives
			# the correct semantics: "component had at least one task actually run".
			if ":" in task.name:
				ran.add(task.name.split(":")[0])

		def skip_uptodate(self, task):
			super().skip_uptodate(task)

	return _Reporter


def _run_doit(component_tasks: dict[str, list[dict]], force: bool = False) -> set[str]:
	"""Run doit with the given component→tasks mapping.
	Returns set of component names that had at least one task execute.

	force: if True, use --always-execute to skip cache checks.
	"""
	from doit.doit_cmd import DoitMain
	from doit.cmd_base import ModuleTaskLoader

	ran: set[str] = set()

	mod = types.ModuleType("_miab_tasks")
	mod.DOIT_CONFIG = {  # type: ignore[attr-defined]
		"backend": "sqlite3",
		"dep_file": STATE_DB,
		"reporter": _make_reporter_class(ran),
		"verbosity": 2,
	}

	def _strip(task: dict) -> dict:
		return {k: v for k, v in task.items() if k in _DOIT_KEYS}

	for comp_name, task_list in component_tasks.items():
		# doit discovers task_* generator functions; yield creates comp:step subtasks.
		def _make_gen(tasks: list[dict]) -> Callable:
			def _gen():
				yield from (_strip(t) for t in tasks)

			return _gen

		gen = _make_gen(task_list)
		gen.__name__ = f"task_{comp_name}"
		setattr(mod, f"task_{comp_name}", gen)

	os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
	if os.path.exists(STATE_DB):
		try:
			with sqlite3.connect(STATE_DB) as con:
				ok = con.execute("PRAGMA integrity_check").fetchone()[0]
			if ok != "ok":
				raise sqlite3.DatabaseError(f"integrity_check returned: {ok}")
		except sqlite3.DatabaseError as e:
			logging.warning("Doit state DB is corrupt (%s) - removing and starting fresh", e)
			os.unlink(STATE_DB)
	doit_cmd = ["run"]
	if force:
		doit_cmd.append("--always-execute")
	doit_result = DoitMain(ModuleTaskLoader(mod)).run(doit_cmd)
	if doit_result != 0:
		# doit exited with error (task failure). Propagate to parent process so
		# install.py knows to abort and report "components" as failed.
		sys.exit(doit_result)
	return ran


# ── Service restart ───────────────────────────────────────────────────────────


def _restart(svc: str, runtime: str) -> None:
	if runtime == DOCKER:
		subprocess.run(["supervisorctl", "restart", svc], check=True)
	else:
		subprocess.run(["systemctl", "restart", svc], check=True)


# ── Main entry point ──────────────────────────────────────────────────────────


def run(env: dict, component_names: list[str] | None = None, force: bool = False) -> None:
	"""Discover, install packages, run doit tasks, restart services.

	env: parsed /etc/mailinabox.conf.
	component_names: explicit list to run, or None for all enabled.
	force: if True, run all tasks even if up-to-date (skip cache checks).
	"""
	_runner_lockfile = open("/tmp/mailinabox-runner.lock", "w")
	try:
		fcntl.flock(_runner_lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
	except BlockingIOError:
		sys.exit("Another setup run is already in progress.")

	runtime = os.environ.get("RUNTIME", BAREMETAL)
	all_defs = _discover()

	if component_names is not None:
		known = {comp.name for comp, _ in all_defs}
		missing = [n for n in component_names if n not in known]
		if missing:
			raise ValueError(f"Unknown components: {missing}")
		defs = [(c, fn) for c, fn in all_defs if c.name in component_names]
	else:
		defs = all_defs

	enabled = [(c, fn) for c, fn in defs if runtime not in c.skip_on and (c.enabled is None or c.enabled(env))]

	if not enabled:
		log.info("No components to run.")
		return

	# One batched apt install for all enabled components.
	all_packages = sorted({p for c, _ in enabled for p in c.packages})
	if all_packages:
		log.info("Installing packages: %s", " ".join(all_packages))
		pkg.ensure_installed(all_packages)

	# Build per-component task lists. Components with no tasks (configure-only)
	# are still restarted below but don't participate in doit.
	component_tasks: dict[str, list[dict]] = {}
	for comp, fn in enabled:
		tasks = fn(env, runtime)
		if tasks:
			component_tasks[comp.name] = tasks

	ran = _run_doit(component_tasks, force=force) if component_tasks else set()

	# Restart services only when at least one task actually ran for that component.
	# Because all tasks are stamped (none use uptodate=[False]), `ran` accurately
	# reflects what changed this invocation - no need to restart postfix just
	# because we ran setup with nothing changed.
	restart_failures: list[str] = []
	for comp, _ in enabled:
		if comp.name not in ran:
			log.info("Skipping restart for %s (all tasks cached)", comp.name)
			continue
		targets = comp.docker_services if runtime == DOCKER else comp.services
		for svc in targets:
			log.info("Restarting %s", svc)
			try:
				_restart(svc, runtime)
			except FileNotFoundError:
				# supervisorctl/systemctl not present - non-fatal (e.g. Docker entrypoint-managed).
				log.warning("WARNING: failed to restart %s - systemctl/supervisorctl not found", svc)
			except subprocess.CalledProcessError:
				log.error("ERROR: failed to restart %s - service may be broken, check logs", svc)
				restart_failures.append(svc)

	if restart_failures:
		sys.exit(f"Services failed to restart: {', '.join(restart_failures)}")

	all_notices = [n for comp, _ in enabled for n in comp.notices]
	if all_notices:
		print("\n" + "=" * 60)
		print("POST-INSTALL NOTICES")
		print("=" * 60)
		for notice in all_notices:
			print(f"  * {notice}")
		print("=" * 60 + "\n")


# ── Build mode ───────────────────────────────────────────────────────────────


def build(component_names: list[str], skip_packages: bool = False) -> None:
	"""Install packages and run build-safe tasks for use in Dockerfiles.

	Runs at Docker image build time - no /etc/mailinabox.conf exists yet.
	Only tasks tagged with "build": True are executed. Config-writing tasks
	that need real env vars are skipped and run at container startup instead.

	RUNTIME must be unset when calling this so ensure_installed() runs apt
	normally (at runtime RUNTIME=docker makes it a no-op).

	skip_packages: skip the apt install step and run tasks only. Used by the
	venv-builder Docker stage which pre-installs compile deps manually and only
	needs the venv/pip tasks, not the full COMPONENT.packages list.
	"""
	all_defs = _discover()

	known = {comp.name for comp, _ in all_defs}
	missing = [n for n in component_names if n not in known]
	if missing:
		raise ValueError(f"Unknown components: {missing}")

	defs = [(c, fn) for c, fn in all_defs if c.name in component_names]

	if not skip_packages:
		# Batched apt install for all named components.
		all_packages = sorted({p for c, _ in defs for p in c.packages})
		if all_packages:
			log.info("Installing packages: %s", " ".join(all_packages))
			pkg.ensure_installed(all_packages)

	# Use a defaultdict so env["ANY_KEY"] returns "" instead of KeyError.
	# make_tasks() may construct task dicts that reference env keys at call
	# time; those values are never used since we filter to build-safe tasks only.
	env: dict = defaultdict(str)

	component_tasks: dict[str, list[dict]] = {}
	for comp, fn in defs:
		all_tasks = fn(env, BAREMETAL)
		build_tasks = [t for t in all_tasks if t.get("build") is True]
		if build_tasks:
			component_tasks[comp.name] = build_tasks

	if component_tasks:
		_run_doit(component_tasks)
	else:
		log.info("No build-time tasks to run.")


# ── CLI / conf helpers ────────────────────────────────────────────────────────


def load_conf(path: str = "/etc/mailinabox.conf") -> dict:
	conf = {}
	try:
		with open(path) as f:
			for line in f:
				line = line.strip()
				if not line or line.startswith("#") or "=" not in line:
					continue
				k, _, v = line.partition("=")
				conf[k.strip()] = v.strip().strip("'\"")
	except FileNotFoundError:
		pass
	return conf


if __name__ == "__main__":
	import argparse

	logging.basicConfig(level=logging.INFO, format="%(message)s")
	parser = argparse.ArgumentParser(description="Run MIAB component runner")
	parser.add_argument("components", nargs="*", help="Components to run (default: all)")
	parser.add_argument("--force", action="store_true", help="Always execute tasks, skip cache checks")
	parser.add_argument("--build-mode", action="store_true", help="Docker build time: install packages and run build-safe tasks only. No /etc/mailinabox.conf needed. RUNTIME must be unset.")
	parser.add_argument("--skip-packages", action="store_true", help="--build-mode only: skip apt install and run tasks only. Used by the venv-builder Docker stage.")
	args = parser.parse_args()
	if args.build_mode:
		if not args.components:
			parser.error("--build-mode requires at least one component name")
		build(args.components, skip_packages=args.skip_packages)
	else:
		env = load_conf()
		if not env:
			if os.path.exists("/etc/mailinabox.conf"):
				log.error("ERROR: /etc/mailinabox.conf exists but is empty or unreadable - re-run setup")
			else:
				log.error("ERROR: /etc/mailinabox.conf not found - run setup first")
			sys.exit(1)
		run(env, component_names=args.components or None, force=args.force)
