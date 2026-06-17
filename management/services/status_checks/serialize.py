def step_to_dict(step):
	return {
		"name": step.name,
		"status": step.status,
		"message": step.message,
	}

def result_to_dict(result):
	return {
		"name": result.name,
		"category": result.category,
		"status": result.status,
		"message": result.message,
		"domain": result.domain,
		"steps": [step_to_dict(s) for s in result.steps],
	}

def results_to_list(results):
	"""results is {key: CheckResult} as returned by run_checks(). Sorted by
	category then name so the same input always renders in the same order."""
	return [result_to_dict(r) for _key, r in sorted(results.items(), key=lambda kv: (kv[1].category, kv[1].name, kv[1].domain or ""))]
