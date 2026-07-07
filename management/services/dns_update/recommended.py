def build_external_dns_records(env):
	from services.dns_update.zones import build_zones

	ret = []
	for domain, _zonefile, records in build_zones(env):
		zone_records = [
			{
				"qname": domain if qname is None else f"{qname}.{domain}",
				"rtype": rtype,
				"value": value,
				"category": category,
			}
			for qname, rtype, value, category in records
			if category is not None
		]

		# Sort: required first, then recommended, then optional.
		zone_records.sort(key=lambda r: 0 if r["category"] == "required" else (1 if r["category"] == "recommended" else 2))

		if zone_records:
			ret.append((domain, zone_records))
	return ret
