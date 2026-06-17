#!/bin/bash
# Are we running as root?
if [[ $EUID -ne 0 ]]; then
	echo "This script must be run as root. Please re-run like this:"
	echo
	echo "sudo $0"
	echo
	exit 1
fi

# Check that we are running on a supported Ubuntu LTS release.
# Pull in the variables defined in /etc/os-release but in a
# namespace to avoid polluting our variables.
source <(cat /etc/os-release | sed s/^/OS_RELEASE_/)
if [ "${OS_RELEASE_ID:-}" != "ubuntu" ]; then
	echo "Mail-in-a-Box only supports Ubuntu. You are running:"
	echo
	echo "${OS_RELEASE_ID:-"Unknown linux distribution"} ${OS_RELEASE_VERSION_ID:-}"
	echo
	exit 1
fi
case "${OS_RELEASE_VERSION_ID:-}" in
	24.04)
		# Ubuntu 24.04 LTS - fully supported, recommended.
		;;
	26.04)
		# Ubuntu 26.04 LTS - newly released, should work but less tested.
		echo "WARNING: Ubuntu 26.04 support is new and less tested than 24.04."
		echo "         Consider using 24.04 for production deployments."
		echo
		;;
	22.04)
		# Ubuntu 22.04 LTS - still works but approaching end of life (April 2027).
		echo "WARNING: Ubuntu 22.04 reaches end of life in April 2027."
		echo "         Consider upgrading to 24.04."
		echo
		;;
	*)
		echo "Mail-in-a-Box supports Ubuntu 24.04 (recommended), 26.04, and 22.04."
		echo "You are running: Ubuntu ${OS_RELEASE_VERSION_ID:-unknown}"
		echo
		exit 1
		;;
esac

# Check that we have enough memory.
#
# /proc/meminfo reports free memory in kibibytes. Our baseline will be 512 MB,
# which is 500000 kibibytes.
#
# We will display a warning if the memory is below 768 MB which is 750000 kibibytes
#
# Skip the check if we appear to be running inside of Vagrant, because that's really just for testing.
TOTAL_PHYSICAL_MEM=$(awk 'NR==1{print $2}' /proc/meminfo)
if [ "$TOTAL_PHYSICAL_MEM" -lt 490000 ]; then
if [ ! -d /vagrant ]; then
	TOTAL_PHYSICAL_MEM=$(( TOTAL_PHYSICAL_MEM * 1024 / 1000 / 1000 ))
	echo "Your Mail-in-a-Box needs more memory (RAM) to function properly."
	echo "Please provision a machine with at least 512 MB, 1 GB recommended."
	echo "This machine has $TOTAL_PHYSICAL_MEM MB memory."
	exit
fi
fi
if [ "$TOTAL_PHYSICAL_MEM" -lt 750000 ]; then
	echo "WARNING: Your Mail-in-a-Box has less than 768 MB of memory."
	echo "         It might run unreliably when under heavy load."
fi

# Check that tempfs is mounted with exec
MOUNTED_TMP_AS_NO_EXEC=$(grep "/tmp.*noexec" /proc/mounts || /bin/true)
if [ -n "$MOUNTED_TMP_AS_NO_EXEC" ]; then
	echo "Mail-in-a-Box has to have exec rights on /tmp, please mount /tmp with exec"
	exit
fi

# Check that no .wgetrc exists
if [ -e ~/.wgetrc ]; then
	echo "Mail-in-a-Box expects no overrides to wget defaults, ~/.wgetrc exists"
	exit
fi

# Check that we are running on x86_64 or i686 architecture, which are the only
# ones we support / test.
ARCHITECTURE=$(uname -m)
if [ "$ARCHITECTURE" != "x86_64" ] && [ "$ARCHITECTURE" != "i686" ]; then
	echo
	echo "WARNING:"
	echo "Mail-in-a-Box has only been tested on x86_64 and i686 platform"
	echo "architectures. Your architecture, $ARCHITECTURE, may not work."
	echo "You are on your own."
	echo
fi
