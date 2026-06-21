#!/bin/bash
# HTTP: Turn on a web server serving static files
#################################################

source setup/functions.sh # load our functions
source /etc/mailinabox.conf # load global vars

# Some Ubuntu images start off with Apache. Remove it since we
# will use nginx. Use autoremove to remove any Apache dependencies.
if [ -f /usr/sbin/apache2 ]; then
	echo "Removing apache..."
	hide_output apt-get -y purge apache2 apache2-*
	hide_output apt-get -y --purge autoremove
fi

# Install nginx. Turn off nginx's default website.

echo "Installing Nginx (web server)..."

apt_install_cached "web" nginx idn2

rm -f /etc/nginx/sites-enabled/default

# Copy in a nginx configuration file for common and best-practices
# SSL settings from @konklone. Replace STORAGE_ROOT so it can find
# the DH params.
rm -f /etc/nginx/nginx-ssl.conf # we used to put it here
sed "s#STORAGE_ROOT#$STORAGE_ROOT#" \
	setup/conf/nginx/nginx-ssl.conf > /etc/nginx/conf.d/ssl.conf

# Fix some nginx defaults.
#
# The server_names_hash_bucket_size seems to prevent long domain names!
# The default, according to nginx's docs, depends on "the size of the
# processor’s cache line." It could be as low as 32. We fixed it at
# 64 in 2014 to accommodate a long domain name (20 characters?). But
# even at 64, a 58-character domain name won't work (#93), so now
# we're going up to 128.
#
# Drop TLSv1.0, TLSv1.1, following the Mozilla "Intermediate" recommendations
# at https://ssl-config.mozilla.org/#server=nginx&server-version=1.17.0&config=intermediate&openssl-version=1.1.1.
setup/tools/editconf.py /etc/nginx/nginx.conf -s \
	server_names_hash_bucket_size="128;" \
	ssl_protocols="TLSv1.2 TLSv1.3;"

# Other nginx settings will be configured by the management service
# since it depends on what domains we're serving, which we don't know
# until mail accounts have been created.

# Create the iOS/OS X Mobile Configuration file which is exposed via the
# nginx configuration at /mailinabox-mobileconfig.
mkdir -p /var/lib/mailinabox
chmod a+rx /var/lib/mailinabox
cp --remove-destination setup/conf/web/admin-down.html /var/lib/mailinabox/admin-down.html
cp --remove-destination setup/conf/web/500.html /var/lib/mailinabox/500.html
UUID1=$(cat /proc/sys/kernel/random/uuid)
UUID2=$(cat /proc/sys/kernel/random/uuid)
UUID3=$(cat /proc/sys/kernel/random/uuid)
UUID4=$(cat /proc/sys/kernel/random/uuid)
sed \
	-e "s/PRIMARY_HOSTNAME/$PRIMARY_HOSTNAME/" \
	-e "s/UUID1/$UUID1/" \
	-e "s/UUID2/$UUID2/" \
	-e "s/UUID3/$UUID3/" \
	-e "s/UUID4/$UUID4/" \
	setup/conf/web/ios-profile.xml > /var/lib/mailinabox/mobileconfig.xml
chmod a+r /var/lib/mailinabox/mobileconfig.xml

# Create the Mozilla Auto-configuration file which is exposed via the
# nginx configuration at /.well-known/autoconfig/mail/config-v1.1.xml.
# The format of the file is documented at:
# https://wiki.mozilla.org/Thunderbird:Autoconfiguration:ConfigFileFormat
# and https://developer.mozilla.org/en-US/docs/Mozilla/Thunderbird/Autoconfiguration/FileFormat/HowTo.
cat setup/conf/web/mozilla-autoconfig.xml \
	| sed "s/PRIMARY_HOSTNAME/$PRIMARY_HOSTNAME/" \
	 > /var/lib/mailinabox/mozilla-autoconfig.xml
chmod a+r /var/lib/mailinabox/mozilla-autoconfig.xml

# Outlook autodiscover XML - served at /autodiscover/autodiscover.xml and
# /.well-known/autoconfig/autodiscover.xml for Outlook and compatible clients.
cat setup/conf/web/autodiscover.xml \
	| sed "s/PRIMARY_HOSTNAME/$PRIMARY_HOSTNAME/" \
	 > /var/lib/mailinabox/autodiscover.xml
chmod a+r /var/lib/mailinabox/autodiscover.xml

# Create a generic mta-sts.txt file which is exposed via the
# nginx configuration at /.well-known/mta-sts.txt
# more documentation is available on:
# https://www.uriports.com/blog/mta-sts-explained/
# default mode is "enforce". In /etc/mailinabox.conf change
# "MTA_STS_MODE=testing" which means "Messages will be delivered
# as though there was no failure but a report will be sent if
# TLS-RPT is configured" if you are not sure you want this yet. Or "none".
PUNY_PRIMARY_HOSTNAME=$(echo "$PRIMARY_HOSTNAME" | idn2)
cat setup/conf/web/mta-sts.txt \
        | sed "s/MODE/${MTA_STS_MODE}/" \
        | sed "s/PRIMARY_HOSTNAME/$PUNY_PRIMARY_HOSTNAME/" \
         > /var/lib/mailinabox/mta-sts.txt
chmod a+r /var/lib/mailinabox/mta-sts.txt

# make a default homepage
if [ -d "$STORAGE_ROOT/www/static" ]; then mv "$STORAGE_ROOT/www/static" "$STORAGE_ROOT/www/default"; fi # migration #NODOC
mkdir -p "$STORAGE_ROOT/www/default"
if [ ! -f "$STORAGE_ROOT/www/default/index.html" ]; then
	cp setup/conf/web/www_default.html "$STORAGE_ROOT/www/default/index.html"
fi
if [ ! -d "$STORAGE_ROOT/www" ] || [ "$(stat -c %U "$STORAGE_ROOT/www")" != "$STORAGE_USER" ]; then
	chown -R "$STORAGE_USER" "$STORAGE_ROOT/www"
fi

# Configure nginx log rotation with copytruncate so fail2ban's inotify watch
# on /var/log/nginx/access.log remains valid across daily rotation (no inode
# change means no watch gap between rotation and fail2ban re-opening the file).
# Override nginx logrotate to use copytruncate so fail2ban's inotify watch
# on access.log survives daily rotation without an inode-change gap.
# This replaces the stock /etc/logrotate.d/nginx shipped by the nginx package.
cat > /etc/logrotate.d/nginx << 'EOF'
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
}
EOF

# Install the web_update helper to a fixed path so boxctl doesn't depend
# on the source repo surviving after setup.
cp --remove-destination setup/tools/web_update /usr/local/lib/mailinabox/web_update
chmod +x /usr/local/lib/mailinabox/web_update

# Start services.
restart_service nginx

# Open ports.
ufw_allow http
ufw_allow https
