"""
Verify that every task_dep reference in every generated task graph
resolves to a real task in that same graph.
"""

import pytest

from tests.components.conftest import CONFIG_MATRIX, make_env, all_task_names
from tests.components._helpers import build_graph_full


@pytest.mark.parametrize("cfg", CONFIG_MATRIX)
def test_no_dangling_task_deps(cfg, tmp_path):
	"""Every task_dep in the graph must name a task that exists in the graph."""
	runtime = cfg["_RUNTIME"]
	env = make_env(tmp_path, **{k: v for k, v in cfg.items() if k != "_RUNTIME"})

	graph = build_graph_full(env, runtime)
	names = all_task_names(graph)

	for comp_name, tasks in graph.items():
		for task in tasks:
			for dep in task.get("task_dep", []):
				assert dep in names, f"{comp_name}:{task['name']} has dangling task_dep {dep!r}; known tasks: {sorted(names)}"
