#!/bin/bash
# Munin: resource monitoring tool
#################################################

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

# install Munin
echo "Installing Munin (system monitoring)..."
apt_install_cached "munin" munin munin-node libcgi-fast-perl procps
# libcgi-fast-perl: needed by /usr/lib/munin/cgi/munin-cgi-graph
# procps: provides ps/free/top - required by munin plugins for CPU/memory/process monitoring

# edit config
cat > /etc/munin/munin.conf <<EOF;
dbdir /var/lib/munin
htmldir /var/cache/munin/www
logdir /var/log/munin
rundir /var/run/munin
tmpldir /etc/munin/templates

includedir /etc/munin/munin-conf.d

# path dynazoom uses for requests
cgiurl_graph /admin/munin/cgi-graph

# a simple host tree
[$PRIMARY_HOSTNAME]
address 127.0.0.1

# send alerts to the following address
contacts admin
contact.admin.command mail -s "Munin notification \${var:host}" administrator@$PRIMARY_HOSTNAME
contact.admin.always_send warning critical
EOF

# The Debian installer touches these files and chowns them to www-data:adm for use with spawn-fcgi
chown munin /var/log/munin/munin-cgi-html.log
chown munin /var/log/munin/munin-cgi-graph.log

# ensure munin-node knows the name of this machine
# and reduce logging level to warning
setup/tools/editconf.py /etc/munin/munin-node.conf -s \
	host_name="$PRIMARY_HOSTNAME" \
	log_level=1

# Bind to IPv4 only. The default is '::' (IPv6 any) which fails in
# environments without IPv6 support (e.g. Docker).
if grep -q "^host " /etc/munin/munin-node.conf; then
	sed -i "s/^host .*/host 0.0.0.0/" /etc/munin/munin-node.conf
else
	echo "host 0.0.0.0" >> /etc/munin/munin-node.conf
fi

# Update the activated plugins through munin's autoconfiguration.
munin-node-configure --shell --remove-also 2>/dev/null | sh || /bin/true

# Deactivate monitoring of NTP peers. Not sure why anyone would want to monitor a NTP peer. The addresses seem to change
# (which is taken care of my munin-node-configure, but only when we re-run it.)
find /etc/munin/plugins/ -lname /usr/share/munin/plugins/ntp_ -print0 | xargs -0 /bin/rm -f

# Deactivate monitoring of network interfaces that are not up. Otherwise we can get a lot of empty charts.
for f in $(find /etc/munin/plugins/ \( -lname /usr/share/munin/plugins/if_ -o -lname /usr/share/munin/plugins/if_err_ -o -lname /usr/share/munin/plugins/bonding_err_ \)); do
	IF=$(echo "$f" | sed s/.*_//);
	if ! grep -qFx up "/sys/class/net/$IF/operstate" 2>/dev/null; then
		rm "$f";
	fi;
done

# Create a 'state' directory. Not sure why we need to do this manually.
mkdir -p /var/lib/munin-node/plugin-state/

# Create a systemd service for munin.
cp --remove-destination setup/conf/systemd/munin.service /lib/systemd/system/munin.service
hide_output systemctl daemon-reload
hide_output systemctl unmask munin.service
hide_output systemctl enable munin.service

# Restart services.
restart_service munin
restart_service munin-node

# generate initial statistics so the directory isn't empty
# (We get "Pango-WARNING **: error opening config file '/root/.config/pango/pangorc': Permission denied"
# if we don't explicitly set the HOME directory when sudo'ing.)
# We check to see if munin-cron is already running, if it is, there is no need to run it simultaneously
# generating an error.
if [ ! -f /var/run/munin/munin-update.lock ]; then
	sudo -H -u munin munin-cron &>/dev/null &
fi
