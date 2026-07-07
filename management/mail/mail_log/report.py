import datetime

from dateutil.relativedelta import relativedelta

from . import state


def print_time_table(labels, data, do_print=True):
	labels.insert(0, "hour")
	data.insert(0, [str(h) for h in range(24)])

	temp = "│ {:<%d} " % max(len(l) for l in labels)
	lines = [temp.format(label) for label in labels]

	for h in range(24):
		max_len = max(len(str(d[h])) for d in data)
		base = "{:>%d} " % max(2, max_len)

		for i, d in enumerate(data):
			lines[i] += base.format(d[h])

	lines.insert(0, "┬ totals by time of day:")
	lines.append("└" + (len(lines[-1]) - 2) * "─")

	if do_print:
		print("\n".join(lines))
		return None
	return lines


def print_user_table(users, data=None, sub_data=None, activity=None, latest=None, earliest=None, delimit=False, numstr=str):
	str_temp = "{:<32} "
	lines = []
	data = data or []

	col_widths = len(data) * [0]
	col_left = len(data) * [False]
	vert_pos = 0

	do_accum = all(isinstance(n, (int, float)) for _, d in data for n in d)
	data_accum = len(data) * ([0] if do_accum else [" "])

	last_user = None

	for row, user in enumerate(users):
		if delimit:
			if last_user and last_user != user:
				lines.append(len(lines[-1]) * "…")
			last_user = user

		line = "{:<32} ".format(user[:31] + "…" if len(user) > 32 else user)

		for col, (l, d) in enumerate(data):
			if isinstance(d[row], str):
				col_str = str_temp.format(d[row][:31] + "…" if len(d[row]) > 32 else d[row])
				col_left[col] = True
			elif isinstance(d[row], datetime.datetime):
				col_str = f"{d[row]!s:<20}"
				col_left[col] = True
			else:
				temp = f"{{:>{max(5, len(l) + 1, len(str(d[row])) + 1)}}}"
				col_str = temp.format(str(d[row]))
			col_widths[col] = max(col_widths[col], len(col_str))
			line += col_str

			if do_accum:
				data_accum[col] += d[row]

		try:
			if None not in [latest, earliest]:  # noqa: PLR6201
				vert_pos = len(line)
				e = earliest[row]
				l = latest[row]
				timespan = relativedelta(l, e)
				if timespan.months:
					temp = " │ {:0.1f} months"
					line += temp.format(timespan.months + timespan.days / 30.0)
				elif timespan.days:
					temp = " │ {:0.1f} days"
					line += temp.format(timespan.days + timespan.hours / 24.0)
				elif (e.hour, e.minute) == (l.hour, l.minute):
					temp = " │ {:%H:%M}"
					line += temp.format(e)
				else:
					temp = " │ {:%H:%M} - {:%H:%M}"
					line += temp.format(e, l)

		except KeyError:
			pass

		lines.append(line.rstrip())

		try:
			if state.VERBOSE:
				if sub_data is not None:
					for l, d in sub_data:
						if d[row]:
							lines.extend(('┬', f'│ {l}', '├─%s─' % (len(l) * '─'), '│'))
							max_len = 0
							for v in list(d[row]):
								lines.append(f"│ {v}")
								max_len = max(max_len, len(v))
							lines.append("└" + (max_len + 1) * "─")

				if activity is not None:
					lines.extend(print_time_table([label for label, _ in activity], [data[row] for _, data in activity], do_print=False))

		except KeyError:
			pass

	header = str_temp.format("")

	for col, (l, _) in enumerate(data):
		if col_left[col]:
			header += l.ljust(max(5, len(l) + 1, col_widths[col]))
		else:
			header += l.rjust(max(5, len(l) + 1, col_widths[col]))

	if None not in [latest, earliest]:  # noqa: PLR6201
		header += " │ timespan   "

	lines.insert(0, header.rstrip())

	table_width = max(len(l) for l in lines)
	t_line = table_width * "─"
	b_line = table_width * "─"

	if vert_pos:
		t_line = t_line[: vert_pos + 1] + "┼" + t_line[vert_pos + 2 :]
		b_line = b_line[: vert_pos + 1] + ("┬" if state.VERBOSE else "┼") + b_line[vert_pos + 2 :]

	lines.insert(1, t_line)
	lines.append(b_line)

	# Print totals

	data_accum = [numstr(a) for a in data_accum]
	footer = str_temp.format("Totals:" if do_accum else " ")
	for row, (l, _) in enumerate(data):
		temp = "{:>%d}" % max(5, len(l) + 1)
		footer += temp.format(data_accum[row])

	try:
		if None not in [latest, earliest]:  # noqa: PLR6201
			max_l = max(latest)
			min_e = min(earliest)
			timespan = relativedelta(max_l, min_e)
			if timespan.days:
				temp = " │ {:0.2f} days"
				footer += temp.format(timespan.days + timespan.hours / 24.0)
			elif (min_e.hour, min_e.minute) == (max_l.hour, max_l.minute):
				temp = " │ {:%H:%M}"
				footer += temp.format(min_e)
			else:
				temp = " │ {:%H:%M} - {:%H:%M}"
				footer += temp.format(min_e, max_l)

	except KeyError:
		pass

	lines.append(footer)

	print("\n".join(lines))


def print_header(msg):
	print('\n' + msg)
	print("═" * len(msg), '\n')
