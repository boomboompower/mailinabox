#!/bin/bash
source /etc/mailinabox.conf
source setup/functions.sh # load our functions
trap 'echo "SETUP DIED at line $LINENO: $BASH_COMMAND" >&2' ERR

# Stop background apt services to prevent dpkg lock conflicts during setup.
systemctl stop apt-daily.service apt-daily-upgrade.service unattended-upgrades.service 2>/dev/null || true

# Basic System Configuration
# -------------------------

# ### Set hostname of the box

# If the hostname is not correctly resolvable sudo can't be used. This will result in
# errors during the install
#
# First set the hostname in the configuration file, then activate the setting

echo "$PRIMARY_HOSTNAME" > /etc/hostname
hostname "$PRIMARY_HOSTNAME"

# ### Fix permissions

# Ensure critical system directories are not group-writable.
# Some cloud images ship with overly permissive defaults.
chmod g-w /etc /etc/default /usr

# ### Add swap space to the system

# If the physical memory of the system is below 2GB it is wise to create a
# swap file. This will make the system more resiliant to memory spikes and
# prevent for instance spam filtering from crashing

# We will create a 1G file, this should be a good balance between disk usage
# and buffers for the system. We will only allocate this file if there is more
# than 5GB of disk space available

# The following checks are performed:
# - Check if swap is currently mountend by looking at /proc/swaps
# - Check if the user intents to activate swap on next boot by checking fstab entries.
# - Check if a swapfile already exists
# - Check if the root file system is not btrfs, might be an incompatible version with
#   swapfiles. User should handle it them selves.
# - Check the memory requirements
# - Check available diskspace

# See https://www.digitalocean.com/community/tutorials/how-to-add-swap-on-ubuntu-14-04
# for reference

SWAP_MOUNTED=$(tail -n+2 /proc/swaps)
SWAP_IN_FSTAB=$(grep "swap" /etc/fstab || /bin/true)
ROOT_IS_BTRFS=$(grep "\/ .*btrfs" /proc/mounts || /bin/true)
TOTAL_PHYSICAL_MEM=$(awk 'NR==1{print $2}' /proc/meminfo)
AVAILABLE_DISK_SPACE=$(df / --output=avail | tail -n 1)
if
	[ -z "$SWAP_MOUNTED" ] &&
	[ -z "$SWAP_IN_FSTAB" ] &&
	[ ! -e /swapfile ] &&
	[ -z "$ROOT_IS_BTRFS" ] &&
	[ "$TOTAL_PHYSICAL_MEM" -lt 1900000 ] &&
	[ "$AVAILABLE_DISK_SPACE" -gt 5242880 ]
then
	echo "Adding a swap file to the system..."

	# Allocate and activate the swap file. Allocate in 1KB chunks
	# doing it in one go, could fail on low memory systems
	fallocate -l 1G /swapfile
	if [ -e /swapfile ]; then
		chmod 600 /swapfile
		hide_output mkswap /swapfile
		swapon /swapfile
	fi

	# Check if swap is mounted then activate on boot
	if swapon -s | grep -q "\/swapfile"; then
		echo "/swapfile   none    swap    sw    0   0" >> /etc/fstab
	else
		echo "ERROR: Swap allocation failed"
	fi
fi

# ### Set log retention policy.

# Set the systemd journal log retention from infinite to 10 days,
# since over time the logs take up a large amount of space.
# (See https://discourse.mailinabox.email/t/journalctl-reclaim-space-on-small-mailinabox/6728/11.)
setup/tools/editconf.py /etc/systemd/journald.conf MaxRetentionSec=10day

# ### Improve server privacy

# Disable MOTD adverts to prevent revealing server information in MOTD request headers
# See https://ma.ttias.be/what-exactly-being-sent-ubuntu-motd/
if [ -f /etc/default/motd-news ]; then
    setup/tools/editconf.py /etc/default/motd-news ENABLED=0
    rm -f /var/cache/motd-news
fi

# ### Enable universe repository

# Ensure the universe repository is enabled since some packages come from
# there and minimal Ubuntu installs may have it turned off.

if [ ! -f /usr/bin/add-apt-repository ]; then
	echo "Installing add-apt-repository..."
	hide_output apt-get update
	apt_install software-properties-common
fi

# Only call add-apt-repository if universe is not already enabled - it triggers
# an internal apt-get update which we'd immediately repeat below.
if ! grep -qr "^deb .*universe" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
	hide_output add-apt-repository -y universe
fi

# ### Update Packages

# Disable downloading of translation files - saves significant time on apt-get update.
mkdir -p /etc/apt/apt.conf.d
echo 'Acquire::Languages "none";' > /etc/apt/apt.conf.d/99no-translations

# Update system packages to make sure we have the latest upstream versions.

if [ "${MIAB_SKIP_UPDATES:-0}" = "1" ]; then
	if [ ! -f /etc/mailinabox.conf ]; then
		echo "WARNING: --no-upgrade was passed but this looks like a first install."
		echo "         Package index may be stale - installation could fail or install outdated packages."
	fi
	echo "Skipping system package upgrade (--no-upgrade)."
else
	echo "Updating system packages..."
	hide_output apt-get update --allow-releaseinfo-change

	# Apply security patches only - general updates are handled by unattended-upgrades.
	# Install unattended-upgrades first in case this is a minimal image without it.
	# Fall back to a full upgrade if either step fails.
	_security_upgrade_ok=false
	if command -v unattended-upgrade &>/dev/null \
	   || apt_get_quiet install unattended-upgrades 2>/dev/null; then
		if hide_output unattended-upgrade; then
			_security_upgrade_ok=true
		fi
	fi
	if ! $_security_upgrade_ok; then
		apt_get_quiet upgrade
	fi
	unset _security_upgrade_ok

	apt_get_quiet autoremove
fi

# ### Install System Packages

# Install basic utilities.
#
# * python3 / python3-dev / python3-pip / python3-setuptools: management daemon and admin panel run on Python
# * netcat-openbsd: `nc` is used in start.sh to wait for the management daemon to come up on port 10222
# * wget / curl: downloading binaries (oxi, FileBrowser) and the icanhazip.com public IP probe
# * git: some setup steps fetch directly from GitHub
# * sudo: management daemon runs as the storage user but needs occasional root operations
# * coreutils: `nproc` sets Dovecot process limits; `mktemp` is used by hide_output
# * bc: computes the Dovecot vsz_limit from available RAM
# * file: MIME-type checks during mail processing
# * openssh-client: `ssh-keygen` generates /root/.ssh/id_rsa_miab for rsync backups
# * unzip: extracting downloaded archives during setup
# * unattended-upgrades: keeps the box patched between Mail-in-a-Box upgrades
# * cron: daily DNSSEC re-signing and backup jobs
# * fail2ban: brute-force protection for SMTP, IMAP, the admin panel, oxi, and FileBrowser
# * rsyslog: provides the log files that fail2ban watches
# * unbound: local recursive resolver required for DANE validation and bypassing RBL shared-IP limits
# * dns-root-data: DNSSEC root trust anchor file required by unbound - normally a recommended package,
#   listed explicitly here because we use --no-install-recommends
# * ufw: host firewall - only installed when DISABLE_FIREWALL is not set

echo "Installing system packages..."
SYSTEM_PKGS=(
	python3 python3-dev python3-pip python3-setuptools
	netcat-openbsd wget curl git sudo coreutils bc file
	openssh-client unzip
	unattended-upgrades cron fail2ban rsyslog
	unbound
	dns-root-data
)
if [ -z "${DISABLE_FIREWALL:-}" ]; then
	SYSTEM_PKGS+=(ufw)
fi
apt_install_cached "system" "${SYSTEM_PKGS[@]}"

# Keep the system clock accurate using native systemd-timesyncd. Important for TLS certificate management.
timedatectl set-ntp true

# ### Suppress Upgrade Prompts
# Prevent the OS from prompting to upgrade to the next Ubuntu release.
# A mail server should only upgrade its OS deliberately, not automatically.
if [ -f /etc/update-manager/release-upgrades ]; then
	setup/tools/editconf.py /etc/update-manager/release-upgrades Prompt=never
	rm -f /var/lib/ubuntu-release-upgrader/release-upgrade-available
fi

# ### Set the system timezone
#
# Some systems are missing /etc/timezone. Daily cron tasks
# like the system backup are run at a time tied to the system timezone, so
# letting the user choose will help us identify the right time to do those
# things (i.e. late at night in whatever timezone the user actually lives
# in).
#
# However, changing the timezone once it is set seems to confuse fail2ban
# and requires restarting fail2ban (done below in the fail2ban
# section) and syslog (see #328). There might be other issues, and it's
# not likely the user will want to change this, so we only ask on first
# setup.
if [ -z "${NONINTERACTIVE:-}" ]; then
	if [ ! -f /etc/timezone ] || [ -n "${FIRST_TIME_SETUP:-}" ]; then
		if [ -n "${TIMEZONE:-}" ]; then
			timedatectl set-timezone "$TIMEZONE"
		else
			# Fallback: TIMEZONE not set (e.g. boxctl skipped), use dpkg interactively.
			dpkg-reconfigure tzdata
		fi
		restart_service rsyslog
	fi
else
	# Non-interactive: use $TIMEZONE if provided, otherwise default to UTC.
	if [ ! -f /etc/timezone ]; then
		timedatectl set-timezone "${TIMEZONE:-Etc/UTC}"
		restart_service rsyslog
	fi
fi

# We need an ssh key to store backups via rsync, if it doesn't exist create one
if [ ! -f /root/.ssh/id_rsa_miab ]; then
	echo 'Creating SSH key for backup…'
	ssh-keygen -t ed25519 -f /root/.ssh/id_rsa_miab -N '' -q
fi

# ### Package maintenance
#
# Allow apt to install system updates automatically every day.

cat > /etc/apt/apt.conf.d/02periodic <<EOF;
APT::Periodic::MaxAge "7";
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Verbose "0";
EOF

# ### Firewall

# Various virtualized environments like Docker and some VPSs don't provide #NODOC
# a kernel that supports iptables. To avoid error-like output in these cases, #NODOC
# we skip this if the user sets DISABLE_FIREWALL=1. #NODOC
if [ -z "${DISABLE_FIREWALL:-}" ]; then
	# Allow incoming connections to SSH.
	ufw_limit ssh;

	# ssh might be running on an alternate port. Use sshd -T to dump sshd's #NODOC
	# settings, find the port it is supposedly running on, and open that port #NODOC
	# too. #NODOC
	SSH_PORT=$(sshd -T 2>/dev/null | grep "^port " | sed "s/port //" | tr '\n' ' ' || true) #NODOC
	if [ -n "$SSH_PORT" ]; then
	    for port in $SSH_PORT; do
	        if [ "$port" != "22" ]; then
	            echo "Opening alternate SSH port $port." #NODOC
                ufw_limit "$port" #NODOC
            fi
        done
	fi

	ufw --force enable;
fi #NODOC

# Install a local recursive DNS server --- i.e. for DNS queries made by
# local services running on this machine.
#
# (This is unrelated to the box's public, non-recursive DNS server that
# answers remote queries about domain names hosted on this box. For that
# see dns.sh.)
#
# This setup enforces strict local DNSSEC validation (required for Postfix DANE)
# and bypasses upstream ISP DNS servers, ensuring that DNS-based real-time
# blacklists (RBLs) do not block our queries due to shared IP rate limits.
#
# We install `unbound` bound strictly to the 127.0.0.1 loopback interface so it
# does not conflict with the public authoritative DNS server (`nsd`).

# Ubuntu's unbound package enables unbound-resolvconf.service which tries to
# manage /etc/resolv.conf via resolvconf. This conflicts with our own DNS setup,
# so disable it immediately after installation on any Ubuntu version that ships it.
systemctl disable --now unbound-resolvconf.service 2>/dev/null || true

# Write a drop-in config that constrains unbound to the loopback interface,
# enables DNSSEC, and exposes unbound-control over a unix socket (no TLS needed
# since it is local-only).
mkdir -p /etc/unbound/unbound.conf.d
cat > /etc/unbound/unbound.conf.d/mailinabox.conf << 'EOF'
server:
    interface: 127.0.0.1
    port: 53
    do-ip6: no
    access-control: 127.0.0.0/8 allow
    hide-identity: yes
    hide-version: yes
    harden-glue: yes
    harden-dnssec-stripped: yes
    use-caps-for-id: yes
    cache-min-ttl: 300
    cache-max-ttl: 86400

remote-control:
    control-enable: yes
    control-use-cert: no
    control-interface: /var/run/unbound.ctl
EOF

# Disable systemd-resolved's stub listener so it does not occupy port 53,
# then point /etc/resolv.conf directly at unbound.
setup/tools/editconf.py /etc/systemd/resolved.conf DNSStubListener=no
systemctl restart systemd-resolved
echo "nameserver 127.0.0.1" > /etc/resolv.conf

restart_service unbound

# ### Fail2Ban Service

# Configure the Fail2Ban installation to prevent dumb bruce-force attacks against dovecot, postfix, ssh, etc.
rm -f /etc/fail2ban/jail.local # we used to use this file but don't anymore
rm -f /etc/fail2ban/jail.d/defaults-debian.conf # removes default config so we can manage all of fail2ban rules in one config
rm -f /etc/fail2ban/jail.d/nginx-ratelimit.conf # moved into mailinabox.conf
_radicale_jail=$( [ "${ENABLE_RADICALE:-true}" = "true" ] && echo true || echo false )
_wc=${WEBMAIL_CLIENT:-oxi}
_cypht_jail=$(    [ "$_wc" = "cypht"      ] && echo true || echo false )
_roundcube_jail=$([ "$_wc" = "roundcube"  ] && echo true || echo false )
_snappymail_jail=$([ "$_wc" = "snappymail" ] && echo true || echo false )
_oxi_jail=$(      [ "$_wc" = "oxi"        ] && echo true || echo false )
sed -e "s/PUBLIC_IPV6/$PUBLIC_IPV6/g" \
    -e "s/PUBLIC_IP/$PUBLIC_IP/g" \
    -e "s#STORAGE_ROOT#$STORAGE_ROOT#" \
    -e "s/RADICALE_JAIL_ENABLED/$_radicale_jail/g" \
    -e "s/CYPHT_JAIL_ENABLED/$_cypht_jail/g" \
    -e "s/ROUNDCUBE_JAIL_ENABLED/$_roundcube_jail/g" \
    -e "s/SNAPPYMAIL_JAIL_ENABLED/$_snappymail_jail/g" \
    -e "s/OXI_JAIL_ENABLED/$_oxi_jail/g" \
    setup/conf/fail2ban/jails.conf > /etc/fail2ban/jail.d/mailinabox.conf
cp -f setup/conf/fail2ban/filter.d/* /etc/fail2ban/filter.d/

# On first installation, the log files that the jails look at don't all exist.
# e.g., The FileBrowser log isn't created until FileBrowser starts for the
# first time. This causes fail2ban to fail to start. Later scripts will ensure
# the files exist and then fail2ban is given another restart at the very end of
# setup.
restart_service fail2ban

systemctl enable fail2ban
