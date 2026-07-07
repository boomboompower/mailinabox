"""
Verify that for each known shared-write target, every pair of writer components
that are both enabled in a representative config has a task_dep ordering path
between them (directly or transitively).

This ensures sequential writes to shared files and prevents concurrent editconf
corruption.
"""

from collections import deque

import pytest

from tests.components.conftest import make_env, all_task_names
from tests.components._helpers import build_graph_full

# Hard-coded known shared-write targets and their writer components.
# Not every writer may be enabled in every config; the test checks only the
# pairs that are actually enabled together.
SHARED_FILES: dict[str, list[str]] = {
	# users writes map paths; rspamd/dkim write milter keys - different keys, not
	# a collision risk. Only include the milter writers for the ordering check.
	"/etc/postfix/main.cf": ["postfix", "rspamd", "dkim", "clamav"],
	"/etc/dovecot/conf.d/10-mail.conf": ["dovecot", "spamassassin"],
	"/etc/dovecot/conf.d/20-imap.conf": ["dovecot", "spamassassin"],
}


def _build_dep_graph(graph: dict[str, list[dict]]) -> dict[str, set[str]]:
	"""Return a mapping task_name -> set of direct task_dep names."""
	deps: dict[str, set[str]] = {}
	for comp_name, tasks in graph.items():
		for t in tasks:
			full_name = f"{comp_name}:{t['name']}"
			deps[full_name] = set(t.get("task_dep", []))
	return deps


def _has_path(dep_graph: dict[str, set[str]], src: str, dst: str) -> bool:
	"""BFS: return True if there is a directed path from src to dst in dep_graph."""
	visited: set[str] = set()
	queue: deque[str] = deque([src])
	while queue:
		node = queue.popleft()
		if node == dst:
			return True
		if node in visited:
			continue
		visited.add(node)
		for neighbour in dep_graph.get(node, set()):
			if neighbour not in visited:
				queue.append(neighbour)
	return False


def _any_task_in_comp(task_names: set[str], comp: str) -> list[str]:
	return [n for n in task_names if n.startswith(f"{comp}:")]


# Representative configs chosen to activate distinct sets of shared-file writers.
# Label, runtime, env overrides.
_CONFIGS = [
	(
		"spamassassin+baremetal+clamav",
		"baremetal",
		{"SPAM_FILTER": "spamassassin", "WEBMAIL_CLIENT": "none", "ENABLE_RADICALE": "false", "ENABLE_FILEBROWSER": "false", "ENABLE_CLAMAV": "true"},
	),
	(
		"rspamd+baremetal+clamav",
		"baremetal",
		{"SPAM_FILTER": "rspamd", "WEBMAIL_CLIENT": "none", "ENABLE_RADICALE": "false", "ENABLE_FILEBROWSER": "false", "ENABLE_CLAMAV": "true"},
	),
	(
		"rspamd+docker",
		"docker",
		{"SPAM_FILTER": "rspamd", "WEBMAIL_CLIENT": "none", "ENABLE_RADICALE": "false", "ENABLE_FILEBROWSER": "false", "ENABLE_CLAMAV": "false"},
	),
	(
		"spamassassin+docker",
		"docker",
		{"SPAM_FILTER": "spamassassin", "WEBMAIL_CLIENT": "none", "ENABLE_RADICALE": "false", "ENABLE_FILEBROWSER": "false", "ENABLE_CLAMAV": "false"},
	),
]


@pytest.mark.parametrize("label,runtime,overrides", _CONFIGS, ids=[c[0] for c in _CONFIGS])
def test_shared_writes_are_ordered(label, runtime, overrides, tmp_path):
	"""For each shared file, enabled writer pairs must have a dep ordering path."""
	env = make_env(tmp_path, **overrides)

	graph = build_graph_full(env, runtime)
	dep_graph = _build_dep_graph(graph)
	names = all_task_names(graph)
	enabled_comps = set(graph.keys())

	failures: list[str] = []

	for shared_file, writers in SHARED_FILES.items():
		active_writers = [w for w in writers if w in enabled_comps]

		for i, comp_a in enumerate(active_writers):
			for comp_b in active_writers[i + 1 :]:
				tasks_a = _any_task_in_comp(names, comp_a)
				tasks_b = _any_task_in_comp(names, comp_b)
				if not tasks_a or not tasks_b:
					continue

				# There must be at least one (task_a, task_b) pair with a dep path
				# in either direction so that doit serialises their writes.
				ordered = any(_has_path(dep_graph, ta, tb) or _has_path(dep_graph, tb, ta) for ta in tasks_a for tb in tasks_b)
				if not ordered:
					failures.append(f"{shared_file}: no ordering path between {comp_a!r} and {comp_b!r}")

	assert not failures, "Shared-write ordering violations:\n" + "\n".join(failures)
