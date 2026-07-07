import importlib
import multiprocessing
import pkgutil
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from .registry import REGISTRY, CheckResult
from .reporter import Reporter, summarize

_discovered = False


def discover_checks():
	"""Import every module under checks/ so its @check-decorated functions
	register themselves. A broken check file is reported and skipped - it
	must never take down every other check."""
	global _discovered
	if _discovered:
		return
	from . import checks as checks_pkg

	for _, modname, _ in pkgutil.iter_modules(checks_pkg.__path__, checks_pkg.__name__ + "."):
		try:
			importlib.import_module(modname)
		except Exception:
			print(f"status check module {modname} failed to load:", file=sys.stderr)
			traceback.print_exc()
	_discovered = True


def get_optimal_pool_size():
	"""Calculate optimal worker count based on CPU count and workload."""
	try:
		cpu_count = multiprocessing.cpu_count()
		if cpu_count < 1 or cpu_count > 256:
			cpu_count = 4
	except (ValueError, OSError):
		cpu_count = 4
	# Most checks are I/O-bound (DNS, network, subprocess calls), so a higher
	# thread count than CPU count pays off, capped to avoid resource exhaustion.
	return min(cpu_count * 2, 20)


def _work_items(env, domains_filter=None):
	"""Expand every registered check into one or more work items. A normal
	check is one item. A per_domain check becomes one item per domain, run
	independently and in parallel rather than as a loop inside one check.

	domains_filter, if given, limits per_domain checks to that set of domains
	(used by the --only CLI flag) - it has no effect on non-domain checks.
	"""
	items = {}
	for chk in REGISTRY.values():
		if chk.per_domain is None:
			items[chk.name] = (chk, None)
		else:
			try:
				domains = list(chk.per_domain(env))
			except Exception:
				domains = []
			if domains_filter is not None:
				domains = [d for d in domains if d in domains_filter]
			for domain in domains:
				items[f"{chk.name}:{domain}"] = (chk, domain)
	return items


def _run_one(chk, domain, env):
	reporter = Reporter()
	try:
		if domain is not None:
			chk.fn(env, domain, reporter)
		else:
			chk.fn(env, reporter)
	except Exception as e:
		# A step already marked itself as the failure point. If the
		# exception came from somewhere else entirely (a bug in the check,
		# not a deliberate step failure), make sure it's still captured
		# instead of crashing the whole run.
		if not reporter.steps or reporter.steps[-1].status != "error":
			from .registry import StepResult

			reporter.steps.append(StepResult(name="unhandled error", status="error", message=str(e)))
	status, message = summarize(reporter.steps) if reporter.steps else ("ok", "")
	return CheckResult(name=chk.name, category=chk.category, status=status, message=message, steps=reporter.steps, domain=domain)


def run_checks(env, on_progress=None, domains_filter=None):
	"""Run every registered, applicable check. Returns {result_key: CheckResult}.

	Dependencies are data, not control flow: a check only gets skipped if a
	check it specifically depends on failed. Unrelated checks always run,
	even during a partial outage.
	"""
	discover_checks()
	results = {}
	remaining = _work_items(env, domains_filter)

	with ThreadPoolExecutor(max_workers=get_optimal_pool_size()) as pool:
		while remaining:
			# A work item is ready once every check it depends on has finished
			# (regardless of whether those dependencies passed or failed).
			ready_keys = [key for key, (chk, _domain) in remaining.items() if all(dep in results for dep in chk.depends_on)]
			if not ready_keys:
				# A dependency cycle or a typo'd depends_on name - don't hang forever.
				for key, (chk, domain) in remaining.items():
					results[key] = CheckResult(name=chk.name, category=chk.category, status="skipped", message="dependency could not be resolved", domain=domain)
				break

			runnable = {}
			for key in ready_keys:
				chk, domain = remaining[key]
				failed_dep = next((d for d in chk.depends_on if results[d].status == "error"), None)
				if failed_dep:
					results[key] = CheckResult(name=chk.name, category=chk.category, status="skipped", message=f"skipped: '{failed_dep}' failed", domain=domain)
				elif chk.enabled is not None and not chk.enabled(env):
					results[key] = CheckResult(name=chk.name, category=chk.category, status="skipped", message="not applicable", domain=domain)
				else:
					runnable[key] = (chk, domain)

			futures = {pool.submit(_run_one, chk, domain, env): key for key, (chk, domain) in runnable.items()}
			for future in as_completed(futures):
				key = futures[future]
				result = future.result()
				results[key] = result
				if on_progress:
					on_progress(key, result)

			remaining = {key: v for key, v in remaining.items() if key not in ready_keys}

	return results
