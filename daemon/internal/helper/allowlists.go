package helper

import "os"

// Closed vocabularies for every intent. Nothing here is caller-extensible;
// unknown names are rejected before any command runs.

// serviceDef describes one service the helper may act on.
type serviceDef struct {
	// reload is a custom reload command sequence. nil means
	// "systemctl reload <name>".
	reload [][]string
	// reloadFallback runs if the custom reload sequence fails. nil means
	// the reload error is returned as-is.
	reloadFallback []string
}

// services mirrors the service set managed by the Python daemon
// (management/services/control_plane.py). Custom sequences are copied
// verbatim from _BARE_METAL_RELOAD / _BARE_METAL_RELOAD_FALLBACK.
var services = map[string]serviceDef{
	"nsd": {
		reload: [][]string{
			{"/usr/sbin/nsd-control", "reconfig"},
			{"/usr/sbin/nsd-control", "reload"},
		},
		reloadFallback: []string{"/usr/bin/systemctl", "restart", "nsd"},
	},
	// unbound cache flush is expressed as a "reload" at the caller level.
	"unbound": {
		reload: [][]string{
			{"/usr/sbin/unbound-control", "-c", "/etc/unbound/unbound.conf", "flush_zone", "."},
		},
	},
	"postfix":     {},
	"dovecot":     {},
	"opendkim":    {},
	"opendmarc":   {},
	"spampd":      {},
	"nginx":       {},
	"filebrowser": {},
	"oxi-email":   {},
}

// postfixKeys are the only main.cf parameters postfix.set may touch -
// exactly the relay parameters the daemon manages today
// (management/core/views/relay_views.py).
var postfixKeys = map[string]bool{
	"relayhost":                  true,
	"smtp_sasl_auth_enable":      true,
	"smtp_sasl_password_maps":    true,
	"smtp_sasl_security_options": true,
	"smtp_tls_security_level":    true,
}

// configTarget is one named file config.write may replace. The path and
// mode are baked in here; callers never supply paths.
type configTarget struct {
	path string
	mode os.FileMode
}

var configTargets = map[string]configTarget{
	"nginx_local": {path: "/etc/nginx/conf.d/local.conf", mode: 0o644},
}

// mapTarget is one named Postfix lookup table postfix.map may rebuild.
// The helper writes the plaintext, runs postmap, then deletes the
// plaintext so secrets exist on disk only during the rebuild.
type mapTarget struct {
	path string
}

var mapTargets = map[string]mapTarget{
	"sasl_passwd": {path: "/etc/postfix/sasl_passwd"},
}
