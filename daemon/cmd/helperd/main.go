// helperd is the privileged helper for the Mail-in-a-Box management
// daemon. It listens on a local Unix socket and executes a fixed menu of
// privileged operations (service restarts, allowlisted config writes,
// apt, reboot) on behalf of the unprivileged manager process.
//
// The intent menu, wire protocol, and invariants are documented in
// .claude/memories/helper-intent-menu.md. The menu is closed: this
// program never runs caller-supplied paths or command strings.
package main

import (
	"flag"
	"log"
	"net"
	"os"
	"os/signal"
	"os/user"
	"path/filepath"
	"strconv"
	"syscall"

	"mailinabox/daemon/internal/helper"
)

func main() {
	socketPath := flag.String("socket", "/run/mailinabox/helper.sock", "unix socket path to listen on")
	socketGroup := flag.String("socket-group", "mailinabox", "group granted connect access to the socket")
	allowUID := flag.Int("allow-uid", -1, "restrict callers to this peer uid (-1 allows any; socket permissions remain the primary gate)")
	flag.Parse()

	logger := log.New(os.Stderr, "", log.LstdFlags)

	if err := os.MkdirAll(filepath.Dir(*socketPath), 0o750); err != nil {
		logger.Fatalf("create socket directory: %v", err)
	}
	// Remove a stale socket from an unclean shutdown; refuse to remove
	// anything that is not a socket.
	if fi, err := os.Lstat(*socketPath); err == nil {
		if fi.Mode()&os.ModeSocket == 0 {
			logger.Fatalf("%s exists and is not a socket; refusing to remove", *socketPath)
		}
		if err := os.Remove(*socketPath); err != nil {
			logger.Fatalf("remove stale socket: %v", err)
		}
	}

	l, err := net.Listen("unix", *socketPath)
	if err != nil {
		logger.Fatalf("listen: %v", err)
	}

	if err := restrictSocket(*socketPath, *socketGroup); err != nil {
		l.Close()
		logger.Fatalf("socket permissions: %v", err)
	}

	srv := &helper.Server{
		Deps:     helper.Deps{Run: helper.ExecRunner{}},
		AllowUID: *allowUID,
		Log:      logger,
	}

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sig
		l.Close()
	}()

	logger.Printf("helperd listening on %s (group %s, allow-uid %d)", *socketPath, *socketGroup, *allowUID)
	if err := srv.Serve(l); err != nil {
		logger.Fatalf("serve: %v", err)
	}
}

// restrictSocket sets the socket to 0660 root:<group> so only the
// manager's group may connect.
func restrictSocket(path, group string) error {
	g, err := user.LookupGroup(group)
	if err != nil {
		return err
	}
	gid, err := strconv.Atoi(g.Gid)
	if err != nil {
		return err
	}
	if err := os.Chown(path, 0, gid); err != nil {
		return err
	}
	return os.Chmod(path, 0o660)
}
