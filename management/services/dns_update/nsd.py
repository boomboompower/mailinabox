import datetime
import os
import re

def write_nsd_zone(domain, zonefile, records, env, force):
	from services.dns_update.dnssec import hash_dnssec_keys

	# On the $ORIGIN line, there's typically a ';' comment at the end explaining
	# what the $ORIGIN line does. Any further data after the domain confuses
	# ldns-signzone, however. It used to say '; default zone domain'.
	#
	# The SOA contact address for all of the domains on this system is hostmaster
	# @ the PRIMARY_HOSTNAME. Hopefully that's legit.
	#
	# For the refresh through TTL fields, a good reference is:
	# https://www.ripe.net/publications/docs/ripe-203
	#
	# A hash of the available DNSSEC keys are added in a comment so that when
	# the keys change we force a re-generation of the zone which triggers
	# re-signing it.

	zone = """
$ORIGIN {domain}.
$TTL 86400          ; default time to live

@ IN SOA ns1.{primary_domain}. hostmaster.{primary_domain}. (
           __SERIAL__     ; serial number
           7200     ; Refresh (secondary nameserver update interval)
           3600     ; Retry (when refresh fails, how often to try again, should be lower than the refresh)
           1209600  ; Expire (when refresh fails, how long secondary nameserver will keep records around anyway)
           86400    ; Negative TTL (how long negative responses are cached)
           )
"""

	# Replace replacement strings.
	zone = zone.format(domain=domain, primary_domain=env["PRIMARY_HOSTNAME"])

	# Add records.
	for subdomain, querytype, value, _explanation in records:
		if subdomain:
			zone += subdomain
		zone += "\tIN\t" + querytype + "\t"
		if querytype == "TXT":
			# Divide into 255-byte max substrings.
			v2 = ""
			while len(value) > 0:
				s = value[0:255]
				value = value[255:]
				s = s.replace('\\', '\\\\') # escape backslashes
				s = s.replace('"', '\\"') # escape quotes
				s = '"' + s + '"' # wrap in quotes
				v2 += s + " "
			value = v2
		zone += value + "\n"

	# Append a stable hash of DNSSEC signing keys in a comment.
	zone += f"\n; DNSSEC signing keys hash: {hash_dnssec_keys(domain, env)}\n"

	# DNSSEC requires re-signing a zone periodically. That requires
	# bumping the serial number even if no other records have changed.
	# We don't see the DNSSEC records yet, so we have to figure out
	# if a re-signing is necessary so we can prematurely bump the
	# serial number.
	force_bump = False
	if not os.path.exists(zonefile + ".signed"):
		# No signed file yet. Shouldn't normally happen unless a box
		# is going from not using DNSSEC to using DNSSEC.
		force_bump = True
	else:
		# We've signed the domain. Check if we are close to the expiration
		# time of the signature. If so, we'll force a bump of the serial
		# number so we can re-sign it.
		with open(zonefile + ".signed", encoding="utf-8") as f:
			signed_zone = f.read()
		expiration_times = re.findall(r"\sRRSIG\s+SOA\s+\d+\s+\d+\s\d+\s+(\d{14})", signed_zone)
		if len(expiration_times) == 0:
			# weird
			force_bump = True
		else:
			# All of the times should be the same, but if not choose the soonest.
			expiration_time = min(expiration_times)
			expiration_time = datetime.datetime.strptime(expiration_time, "%Y%m%d%H%M%S")
			if expiration_time - datetime.datetime.now() < datetime.timedelta(days=3):
				# We're within three days of the expiration, so bump serial & resign.
				force_bump = True

	# Set the serial number.
	serial = datetime.datetime.now().strftime("%Y%m%d00")
	if os.path.exists(zonefile):
		# If the zone already exists, is different, and has a later serial number,
		# increment the number.
		with open(zonefile, encoding="utf-8") as f:
			existing_zone = f.read()
			m = re.search(r"(\d+)\s*;\s*serial number", existing_zone)
			if m:
				# Clear out the serial number in the existing zone file for the
				# purposes of seeing if anything *else* in the zone has changed.
				existing_serial = m.group(1)
				existing_zone = existing_zone.replace(m.group(0), "__SERIAL__     ; serial number")

				# If the existing zone is the same as the new zone (modulo the serial number),
				# there is no need to update the file. Unless we're forcing a bump.
				if zone == existing_zone and not force_bump and not force:
					return False

				# If the existing serial is not less than a serial number
				# based on the current date plus 00, increment it. Otherwise,
				# the serial number is less than our desired new serial number
				# so we'll use the desired new number.
				if existing_serial >= serial:
					serial = str(int(existing_serial) + 1)

	zone = zone.replace("__SERIAL__", serial)

	# Write the zone file.
	with open(zonefile, "w", encoding="utf-8") as f:
		f.write(zone)

	return True # file is updated

def get_dns_zonefile(zone, env):
	from services.dns_update.zones import get_dns_zones

	# zone is validated against the managed-zone list here; fn (not zone) is used
	# in the path, so there is no path traversal even though the caller passes zone
	# directly from a URL parameter.
	for domain, fn in get_dns_zones(env):
		if zone == domain:
			break
	else:
		msg = f"{zone} is not a domain name that corresponds to a zone."
		raise ValueError(msg)

	nsd_zonefile = "/etc/nsd/zones/" + fn
	with open(nsd_zonefile, encoding="utf-8") as f:
		return f.read()

def write_nsd_conf(zonefiles, additional_records, env):
	from services.dns_update.custom_records import get_secondary_dns

	# Write the list of zones to a configuration file.
	nsd_conf_file = "/etc/nsd/nsd.conf.d/zones.conf"
	nsdconf = ""

	# Append the zones.
	for domain, zonefile in zonefiles:
		nsdconf += f"""
zone:
	name: {domain}
	zonefile: {zonefile}
"""

		# If custom secondary nameservers have been set, allow zone transfers
		# and, if not a subnet, notifies to them.
		for ipaddr in get_secondary_dns(additional_records, mode="xfr"):
			if "/" not in ipaddr:
				nsdconf += f"\n\tnotify: {ipaddr} NOKEY"
			nsdconf += f"\n\tprovide-xfr: {ipaddr} NOKEY\n"

	# Check if the file is changing. If it isn't changing,
	# return False to flag that no change was made.
	if os.path.exists(nsd_conf_file):
		with open(nsd_conf_file, encoding="utf-8") as f:
			if f.read() == nsdconf:
				return False

	# Write out new contents and return True to signal that
	# configuration changed.
	with open(nsd_conf_file, "w", encoding="utf-8") as f:
		f.write(nsdconf)
	return True
