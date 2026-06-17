def build_recommended_dns(env):
	from services.dns_update.zones import build_zones

	ret = []
	for (domain, _zonefile, records) in build_zones(env):
		# remove records that we don't display
		records = [r for r in records if r[3] is not False]

		# put Required at the top, then Recommended, then everythiing else
		records.sort(key = lambda r : 0 if r[3].startswith("Required.") else (1 if r[3].startswith("Recommended.") else 2))

		# expand qnames
		for i in range(len(records)):
			qname = domain if records[i][0] is None else records[i][0] + "." + domain

			records[i] = {
				"qname": qname,
				"rtype": records[i][1],
				"value": records[i][2],
				"explanation": records[i][3],
			}

		# return
		ret.append((domain, records))
	return ret
