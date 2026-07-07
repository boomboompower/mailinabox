import time
from contextlib import contextmanager

from .registry import StepResult


class CheckFailed(Exception):
	"""Raise inside a step to stop the check right there. The step is marked
	as failed and no further steps in this check will run."""


class Reporter:
	"""Handed to every check function. Tracks the ordered list of steps a
	check goes through, the same way a CI job shows step-by-step progress.

	- A step that raises stops the check immediately (no later steps run).
	- A step that calls warn() keeps going - a warning never stops a check.
	"""

	def __init__(self, on_progress=None, on_progress_key=None):
		self.steps = []
		self._on_progress = on_progress
		self._on_progress_key = on_progress_key

	@contextmanager
	def step(self, name):
		s = StepResult(name=name, status="running", started_at=time.monotonic())
		self.steps.append(s)
		self._emit()
		try:
			yield s
			if s.status == "running":
				# Nobody called warn() during this step, and nothing raised - clean pass.
				s.status = "ok"
		except CheckFailed as e:
			s.status = "error"
			s.message = str(e)
			raise
		except Exception as e:
			s.status = "error"
			s.message = str(e)
			raise
		finally:
			s.finished_at = time.monotonic()
			self._emit()

	def warn(self, message):
		"""Mark the current step as a warning. Does not stop the check."""
		if self.steps:
			self.steps[-1].status = "warning"
			self.steps[-1].message = message
			self._emit()

	def _emit(self):
		if self._on_progress:
			self._on_progress(self._on_progress_key, list(self.steps))


def summarize(steps):
	"""Roll a list of StepResults up into one overall status + message."""
	if any(s.status == "error" for s in steps):
		failed = next(s for s in steps if s.status == "error")
		return "error", f"failed at step '{failed.name}': {failed.message}" if failed.message else f"failed at step '{failed.name}'"
	if any(s.status == "warning" for s in steps):
		warned = [s for s in steps if s.status == "warning"]
		return "warning", "; ".join(s.message for s in warned if s.message) or "completed with warnings"
	return "ok", ""
