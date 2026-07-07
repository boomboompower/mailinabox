package helper

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// fakeRunner records every argv and returns scripted errors.
type fakeRunner struct {
	calls [][]string
	env   [][]string
	// failOn maps argv[0] basename to an error to return.
	failOn map[string]error
}

func (f *fakeRunner) Run(_ context.Context, argv []string, extraEnv []string) error {
	f.calls = append(f.calls, argv)
	f.env = append(f.env, extraEnv)
	if err, ok := f.failOn[filepath.Base(argv[0])]; ok {
		return err
	}
	return nil
}

func dispatch(t *testing.T, d Deps, intent string, args map[string]string) error {
	t.Helper()
	return Dispatch(context.Background(), d, Request{Intent: intent, Args: args})
}

func TestValidationRejections(t *testing.T) {
	run := &fakeRunner{}
	d := Deps{Run: run, Root: t.TempDir()}

	cases := []struct {
		name   string
		intent string
		args   map[string]string
		want   string
	}{
		{"unknown intent", "shell.exec", map[string]string{"cmd": "id"}, "unknown intent"},
		{"unlisted service", "service.restart", map[string]string{"service": "sshd"}, "not in allowlist"},
		{"missing arg", "service.restart", map[string]string{}, "do not match"},
		{"extra arg", "service.restart", map[string]string{"service": "nginx", "path": "/etc"}, "do not match"},
		{"unlisted postfix key", "postfix.set", map[string]string{"key": "inet_interfaces", "value": "all"}, "not in allowlist"},
		{"newline in value", "postfix.set", map[string]string{"key": "relayhost", "value": "a\nb"}, "control character"},
		{"oversized value", "postfix.set", map[string]string{"key": "relayhost", "value": strings.Repeat("x", 2000)}, "exceeds"},
		{"unlisted map", "postfix.map", map[string]string{"map": "virtual", "content": "x"}, "not in allowlist"},
		{"unlisted config target", "config.write", map[string]string{"target": "sudoers", "content": "x"}, "not in allowlist"},
		{"oversized content", "config.write", map[string]string{"target": "nginx_local", "content": strings.Repeat("x", maxContentLen+1)}, "exceeds"},
		{"args on no-arg intent", "host.reboot", map[string]string{"force": "1"}, "do not match"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := dispatch(t, d, tc.intent, tc.args)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("got %v, want error containing %q", err, tc.want)
			}
		})
	}
	if len(run.calls) != 0 {
		t.Fatalf("validation failures must not execute anything; ran %v", run.calls)
	}
}

func TestServiceLifecycle(t *testing.T) {
	run := &fakeRunner{}
	d := Deps{Run: run}

	for _, action := range []string{"restart", "reload", "stop", "disable"} {
		if err := dispatch(t, d, "service."+action, map[string]string{"service": "nginx"}); err != nil {
			t.Fatalf("service.%s: %v", action, err)
		}
	}
	want := [][]string{
		{"/usr/bin/systemctl", "restart", "nginx"},
		{"/usr/bin/systemctl", "reload", "nginx"},
		{"/usr/bin/systemctl", "stop", "nginx"},
		{"/usr/bin/systemctl", "disable", "nginx"},
	}
	if !reflect.DeepEqual(run.calls, want) {
		t.Fatalf("got %v, want %v", run.calls, want)
	}
}

func TestNsdCustomReloadSequence(t *testing.T) {
	run := &fakeRunner{}
	d := Deps{Run: run}

	if err := dispatch(t, d, "service.reload", map[string]string{"service": "nsd"}); err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"/usr/sbin/nsd-control", "reconfig"},
		{"/usr/sbin/nsd-control", "reload"},
	}
	if !reflect.DeepEqual(run.calls, want) {
		t.Fatalf("got %v, want %v", run.calls, want)
	}
}

func TestNsdReloadFallsBackToRestart(t *testing.T) {
	run := &fakeRunner{failOn: map[string]error{"nsd-control": errors.New("boom")}}
	d := Deps{Run: run}

	if err := dispatch(t, d, "service.reload", map[string]string{"service": "nsd"}); err != nil {
		t.Fatalf("fallback should succeed, got %v", err)
	}
	last := run.calls[len(run.calls)-1]
	want := []string{"/usr/bin/systemctl", "restart", "nsd"}
	if !reflect.DeepEqual(last, want) {
		t.Fatalf("last call %v, want fallback %v", last, want)
	}
}

func TestPostfixSet(t *testing.T) {
	run := &fakeRunner{}
	d := Deps{Run: run}

	if err := dispatch(t, d, "postfix.set", map[string]string{"key": "relayhost", "value": "[smtp.example.com]:587"}); err != nil {
		t.Fatal(err)
	}
	// Empty value must be allowed - disabling the relay sets relayhost=.
	if err := dispatch(t, d, "postfix.set", map[string]string{"key": "relayhost", "value": ""}); err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"/usr/sbin/postconf", "-e", "relayhost=[smtp.example.com]:587"},
		{"/usr/sbin/postconf", "-e", "relayhost="},
	}
	if !reflect.DeepEqual(run.calls, want) {
		t.Fatalf("got %v, want %v", run.calls, want)
	}
}

func TestPostfixMapWritesPostmapsAndRemovesPlaintext(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "etc/postfix"), 0o755); err != nil {
		t.Fatal(err)
	}
	run := &fakeRunner{}
	d := Deps{Run: run, Root: root}

	secret := "[smtp.example.com]:587 user:hunter2\n"
	if err := dispatch(t, d, "postfix.map", map[string]string{"map": "sasl_passwd", "content": secret}); err != nil {
		t.Fatal(err)
	}

	path := filepath.Join(root, "etc/postfix/sasl_passwd")
	want := [][]string{{"/usr/sbin/postmap", "hash:" + path}}
	if !reflect.DeepEqual(run.calls, want) {
		t.Fatalf("got %v, want %v", run.calls, want)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("plaintext %s must be removed after postmap", path)
	}
}

func TestPostfixMapRemovesPlaintextOnPostmapFailure(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "etc/postfix"), 0o755); err != nil {
		t.Fatal(err)
	}
	run := &fakeRunner{failOn: map[string]error{"postmap": errors.New("boom")}}
	d := Deps{Run: run, Root: root}

	err := dispatch(t, d, "postfix.map", map[string]string{"map": "sasl_passwd", "content": "secret"})
	if err == nil {
		t.Fatal("want postmap error")
	}
	if _, statErr := os.Stat(filepath.Join(root, "etc/postfix/sasl_passwd")); !os.IsNotExist(statErr) {
		t.Fatal("plaintext must be removed even when postmap fails")
	}
}

func TestConfigWriteAtomicWithMode(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "etc/nginx/conf.d")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	d := Deps{Run: &fakeRunner{}, Root: root}

	content := "server { listen 127.0.0.1:8080; }\n"
	if err := dispatch(t, d, "config.write", map[string]string{"target": "nginx_local", "content": content}); err != nil {
		t.Fatal(err)
	}

	path := filepath.Join(dir, "local.conf")
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != content {
		t.Fatalf("content mismatch: %q", got)
	}
	fi, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if fi.Mode().Perm() != 0o644 {
		t.Fatalf("mode %v, want 0644", fi.Mode().Perm())
	}
	// No temp files left behind.
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("stray files in %s: %v", dir, entries)
	}
}

func TestHostIntentsUseExactArgv(t *testing.T) {
	run := &fakeRunner{}
	d := Deps{Run: run}

	for _, intent := range []string{"host.apt_update", "host.apt_upgrade", "host.reboot"} {
		if err := dispatch(t, d, intent, nil); err != nil {
			t.Fatalf("%s: %v", intent, err)
		}
	}
	want := [][]string{
		{"/usr/bin/apt-get", "-qq", "update"},
		{"/usr/bin/apt-get", "-y", "upgrade"},
		{"/sbin/shutdown", "-r", "now"},
	}
	if !reflect.DeepEqual(run.calls, want) {
		t.Fatalf("got %v, want %v", run.calls, want)
	}
	if !reflect.DeepEqual(run.env[1], []string{"DEBIAN_FRONTEND=noninteractive"}) {
		t.Fatalf("apt_upgrade env %v, want noninteractive", run.env[1])
	}
}
