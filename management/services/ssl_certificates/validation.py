# Pure certificate parsing/validation - no I/O beyond reading the files
# passed in. Reused independently by services/dns_update and
# services/status_checks (check_certificate, load_cert_chain, load_pem),
# which is the concrete evidence this is a distinct, reusable concern and
# not just code that happens to sit near the rest of this module.

import re

from core.utils import shell

def check_certificate(domain, ssl_certificate, ssl_private_key, warn_if_expiring_soon=10, rounded_time=False, just_check_domain=False):
	# Check that the ssl_certificate & ssl_private_key files are good
	# for the provided domain.

	from cryptography.hazmat.primitives.asymmetric import rsa, dsa, ec
	from cryptography.x509 import Certificate

	# The ssl_certificate file may contain a chain of certificates. We'll
	# need to split that up before we can pass anything to openssl or
	# parse them in Python. Parse it with the cryptography library.
	try:
		ssl_cert_chain = load_cert_chain(ssl_certificate)
		cert = load_pem(ssl_cert_chain[0])
		if not isinstance(cert, Certificate): raise ValueError("This is not a certificate file.")
	except ValueError as e:
		return (f"There is a problem with the certificate file: {e!s}", None)

	# First check that the domain name is one of the names allowed by
	# the certificate.
	if domain is not None:
		certificate_names, _cert_primary_name = get_certificate_domains(cert)

		# Check that the domain appears among the acceptable names, or a wildcard
		# form of the domain name (which is a stricter check than the specs but
		# should work in normal cases).
		wildcard_domain = re.sub(r"^[^\.]+", "*", domain)
		if domain not in certificate_names and wildcard_domain not in certificate_names:
			return ("The certificate is for the wrong domain name. It is for {}.".format(", ".join(sorted(certificate_names))), None)

	# Second, check that the certificate matches the private key.
	if ssl_private_key is not None:
		try:
			with open(ssl_private_key, 'rb') as f:
				priv_key = load_pem(f.read())
		except ValueError as e:
			return (f"The private key file {ssl_private_key} is not a private key file: {e!s}", None)

		if (not isinstance(priv_key, rsa.RSAPrivateKey)
			and not isinstance(priv_key, dsa.DSAPrivateKey)
			and not isinstance(priv_key, ec.EllipticCurvePrivateKey)):
			return (f"The private key file {ssl_private_key} is not a private key file.", None)

		if priv_key.public_key().public_numbers() != cert.public_key().public_numbers():
			return (f"The certificate does not correspond to the private key at {ssl_private_key}.", None)

		# We could also use the openssl command line tool to get the modulus
		# listed in each file. The output of each command below looks like "Modulus=XXXXX".
		# $ openssl rsa -inform PEM -noout -modulus -in ssl_private_key
		# $ openssl x509 -in ssl_certificate -noout -modulus

	# Third, check if the certificate is self-signed. Return a special flag string.
	if cert.issuer == cert.subject:
		return ("SELF-SIGNED", None)

	# When selecting which certificate to use for non-primary domains, we check if the primary
	# certificate or a www-parent-domain certificate is good for the domain. There's no need
	# to run extra checks beyond this point.
	if just_check_domain:
		return ("OK", None)

	# Check that the certificate hasn't expired. The datetimes returned by the
	# certificate are 'naive' and in UTC. We need to get the current time in UTC.
	import datetime
	now = datetime.datetime.now(datetime.timezone.utc)
	if not(cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
		return (f"The certificate has expired or is not yet valid. It is valid from {cert.not_valid_before_utc} to {cert.not_valid_after_utc}.", None)

	# Next validate that the certificate is valid. This checks whether the certificate
	# is self-signed, that the chain of trust makes sense, that it is signed by a CA
	# that Ubuntu has installed on this machine's list of CAs, and I think that it hasn't
	# expired.

	# The certificate chain has to be passed separately and is given via STDIN.
	# This command returns a non-zero exit status in most cases, so trap errors.
	retcode, verifyoutput = shell('check_output', [
		"openssl",
		"verify", "-verbose",
		"-purpose", "sslserver", "-policy_check",]
		+ ([] if len(ssl_cert_chain) == 1 else ["-untrusted", "/proc/self/fd/0"])
		+ [ssl_certificate],
		input=b"\n\n".join(ssl_cert_chain[1:]),
		trap=True)

	if "self signed" in verifyoutput:
		# Certificate is self-signed. Probably we detected this above.
		return ("SELF-SIGNED", None)

	if retcode != 0:
		if "unable to get local issuer certificate" in verifyoutput:
			return (f"The certificate is missing an intermediate chain or the intermediate chain is incorrect or incomplete. ({verifyoutput})", None)

		# There is some unknown problem. Return the `openssl verify` raw output.
		return ("There is a problem with the certificate.", verifyoutput.strip())

	# `openssl verify` returned a zero exit status so the cert is currently
	# good.

	# But is it expiring soon?
	cert_expiration_date = cert.not_valid_after_utc
	ndays = (cert_expiration_date-now).days
	if not rounded_time or ndays <= 10:
		# Yikes better renew soon!
		expiry_info = "The certificate expires in %d days on %s." % (ndays, cert_expiration_date.date().isoformat())
	else:
		# We'll renew it with Lets Encrypt.
		expiry_info = f"The certificate expires on {cert_expiration_date.date().isoformat()}."

	if warn_if_expiring_soon and ndays <= warn_if_expiring_soon:
		# Warn on day 10 to give 4 days for us to automatically renew the
		# certificate, which occurs on day 14.
		return ("The certificate is expiring soon: " + expiry_info, None)

	# Return the special OK code.
	return ("OK", expiry_info)

def load_cert_chain(pemfile):
	# A certificate .pem file may contain a chain of certificates.
	# Load the file and split them apart.
	re_pem = rb"(-+BEGIN (?:.+)-+[\r\n]+(?:[A-Za-z0-9+/=]{1,64}[\r\n]+)+-+END (?:.+)-+[\r\n]+)"
	with open(pemfile, "rb") as f:
		pem = f.read() + b"\n" # ensure trailing newline
		pemblocks = re.findall(re_pem, pem)
		if len(pemblocks) == 0:
			msg = "File does not contain valid PEM data."
			raise ValueError(msg)
		return pemblocks

def load_pem(pem):
	# Parse a "---BEGIN .... END---" PEM string and return a Python object for it
	# using classes from the cryptography package.
	from cryptography.x509 import load_pem_x509_certificate
	from cryptography.hazmat.primitives import serialization
	from cryptography.hazmat.backends import default_backend
	pem_type = re.match(b"-+BEGIN (.*?)-+[\r\n]", pem)
	if pem_type is None:
		msg = "File is not a valid PEM-formatted file."
		raise ValueError(msg)
	pem_type = pem_type.group(1)
	if pem_type.endswith(b"PRIVATE KEY"):
		return serialization.load_pem_private_key(pem, password=None, backend=default_backend())
	if pem_type == b"CERTIFICATE":
		return load_pem_x509_certificate(pem, default_backend())
	raise ValueError("Unsupported PEM object type: " + pem_type.decode("ascii", "replace"))

def get_certificate_domains(cert):
	from cryptography.x509 import DNSName, ExtensionNotFound, OID_COMMON_NAME, OID_SUBJECT_ALTERNATIVE_NAME
	import idna

	names = set()
	cn = None

	# The domain may be found in the Subject Common Name (CN). This comes back as an IDNA (ASCII)
	# string, which is the format we store domains in - so good.
	try:
		cn = cert.subject.get_attributes_for_oid(OID_COMMON_NAME)[0].value
		names.add(cn)
	except IndexError:
		# No common name? Certificate is probably generated incorrectly.
		# But we'll let it error-out when it doesn't find the domain.
		pass

	# ... or be one of the Subject Alternative Names. The cryptography library handily IDNA-decodes
	# the names for us. We must encode back to ASCII, but wildcard certificates can't pass through
	# IDNA encoding/decoding so we must special-case. See https://github.com/pyca/cryptography/pull/2071.
	def idna_decode_dns_name(dns_name):
		if dns_name.startswith("*."):
			return "*." + idna.encode(dns_name[2:]).decode('ascii')
		return idna.encode(dns_name).decode('ascii')

	try:
		sans = cert.extensions.get_extension_for_oid(OID_SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(DNSName)
		names.update(idna_decode_dns_name(san) for san in sans)
	except ExtensionNotFound:
		pass

	return names, cn
