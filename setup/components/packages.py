"""
Single batched apt-get install across all enabled components. No-op in Docker
(packages are pre-baked into the container image).
"""

import os
import subprocess

from .component import DOCKER


def ensure_installed(packages: list[str]) -> None:
	if not packages:
		return
	if os.environ.get("RUNTIME") == DOCKER:
		return
	env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_SUSPEND": "1"}
	subprocess.run(["apt-get", "-qq", "update"], check=True, env=env)
	subprocess.run(
		[
			"apt-get",
			"install",
			"-y",
			"--no-install-recommends",
			"-o",
			"Dpkg::Options::=--force-confdef",
			"-o",
			"Dpkg::Options::=--force-confnew",
			"-o",
			"DPkg::Lock::Timeout=300",
			*packages,
		],
		check=True,
		env=env,
	)
