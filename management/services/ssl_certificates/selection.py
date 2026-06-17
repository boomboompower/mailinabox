# Choosing which already-installed certificate is best for a given domain.

import os
import re

def get_ssl_certificates(env):
	# Scan all of the installed SSL certificates and map every domain
	# that the certificates are good for to the best certificate for
	# the domain.
	from .validation import load_pem, load_cert_chain, get_certificate_domains

	from cryptography.hazmat.primitives.asymmetric import dsa, rsa, ec
	from cryptography.x509 import Certificate

	# The certificates are all stored here:
	ssl_root = os.path.join(env["STORAGE_ROOT"], 'ssl')

	# List all of the files in the SSL directory and one level deep.
	def get_file_list():
		if not os.path.exists(ssl_root):
			return
		for fn in os.listdir(ssl_root):
			if fn == 'ssl_certificate.pem':
				# This is always a symbolic link
				# to the certificate to use for
				# PRIMARY_HOSTNAME. Don't let it
				# be eligible for use because we
				# could end up creating a symlink
				# to itself --- we want to find
				# the cert that it should be a
				# symlink to.
				continue
			fn = os.path.join(ssl_root, fn)
			if os.path.isfile(fn):
				yield fn
			elif os.path.isdir(fn):
				for fn1 in os.listdir(fn):
					fn1 = os.path.join(fn, fn1)
					if os.path.isfile(fn1):
						yield fn1

	# Remember stuff.
	private_keys = { }
	certificates = [ ]

	# Scan each of the files to find private keys and certificates.
	# We must load all of the private keys first before processing
	# certificates so that we can check that we have a private key
	# available before using a certificate.
	for fn in get_file_list():
		try:
			pem = load_pem(load_cert_chain(fn)[0])
		except ValueError:
			# Not a valid PEM format for a PEM type we care about.
			continue

		# Is it a certificate?
		if isinstance(pem, Certificate):
			certificates.append({ "filename": fn, "cert": pem })
		# It is a private key
		elif (isinstance(pem, (rsa.RSAPrivateKey, dsa.DSAPrivateKey, ec.EllipticCurvePrivateKey))):
			private_keys[pem.public_key().public_numbers()] = { "filename": fn, "key": pem }


	# Process the certificates.
	domains = { }
	for cert in certificates:
		# What domains is this certificate good for?
		cert_domains, primary_domain = get_certificate_domains(cert["cert"])
		cert["primary_domain"] = primary_domain

		# Is there a private key file for this certificate?
		private_key = private_keys.get(cert["cert"].public_key().public_numbers())
		if not private_key:
			continue
		cert["private_key"] = private_key

		# Add this cert to the list of certs usable for the domains.
		for domain in cert_domains:
			# The primary hostname can only use a certificate mapped
			# to the system private key.
			if domain == env['PRIMARY_HOSTNAME'] and cert["private_key"]["filename"] != os.path.join(env['STORAGE_ROOT'], 'ssl', 'ssl_private_key.pem'):
				continue

			domains.setdefault(domain, []).append(cert)

	# Sort the certificates to prefer good ones.
	import datetime
	now = datetime.datetime.now(datetime.timezone.utc)
	ret = { }
	for domain, cert_list in domains.items():
		#for c in cert_list: print(domain, c.not_valid_before_utc, c.not_valid_after_utc, "("+str(now)+")", c.issuer, c.subject, c._filename)
		cert_list.sort(key = lambda cert : (
			# must be valid NOW
			cert["cert"].not_valid_before_utc <= now <= cert["cert"].not_valid_after_utc,

			# prefer one that is not self-signed
			cert["cert"].issuer != cert["cert"].subject,

			###########################################################
			# The above lines ensure that valid certificates are chosen
			# over invalid certificates. The lines below choose between
			# multiple valid certificates available for this domain.
			###########################################################

			# prefer one with the expiration furthest into the future so
			# that we can easily rotate to new certs as we get them
			cert["cert"].not_valid_after_utc,

			###########################################################
			# We always choose the certificate that is good for the
			# longest period of time. This is important for how we
			# provision certificates for Let's Encrypt. To ensure that
			# we don't re-provision every night, we have to ensure that
			# if we choose to provison a certificate that it will
			# *actually* be used so the provisioning logic knows it
			# doesn't still need to provision a certificate for the
			# domain.
			###########################################################

			# in case a certificate is installed in multiple paths,
			# prefer the... lexicographically last one?
			cert["filename"],

		), reverse=True)
		cert = cert_list.pop(0)
		ret[domain] = {
			"private-key": cert["private_key"]["filename"],
			"certificate": cert["filename"],
			"primary-domain": cert["primary_domain"],
			"certificate_object": cert["cert"],
			}

	return ret

def get_domain_ssl_files(domain, ssl_certificates, env, allow_missing_cert=False, use_main_cert=True):
	from .validation import load_pem, load_cert_chain

	if use_main_cert or not allow_missing_cert:
		# Get the system certificate info.
		ssl_private_key = os.path.join(os.path.join(env["STORAGE_ROOT"], 'ssl', 'ssl_private_key.pem'))
		ssl_certificate = os.path.join(os.path.join(env["STORAGE_ROOT"], 'ssl', 'ssl_certificate.pem'))
		system_certificate = {
			"private-key": ssl_private_key,
			"certificate": ssl_certificate,
			"primary-domain": env['PRIMARY_HOSTNAME'],
			"certificate_object": load_pem(load_cert_chain(ssl_certificate)[0]),
		}

	if use_main_cert and domain == env['PRIMARY_HOSTNAME']:
		# The primary domain must use the server certificate because
		# it is hard-coded in some service configuration files.
		return system_certificate

	wildcard_domain = re.sub(r"^[^\.]+", "*", domain)
	if domain in ssl_certificates:
		return ssl_certificates[domain]
	if wildcard_domain in ssl_certificates:
		return ssl_certificates[wildcard_domain]
	if not allow_missing_cert:
		# No valid certificate is available for this domain! Return default files.
		return system_certificate
	# No valid certificate is available for this domain.
	return None
