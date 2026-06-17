# Contributing

Contributions are welcome. This is an actively developed fork of Mail-in-a-Box with a specific direction - read this guide before sending a PR to avoid wasted effort.

## Project direction

This project replaces the PHP/Nextcloud stack with modern alternatives (oxi.email, FileBrowser, Radicale) and adds a Vue 3 admin UI and WebAuthn. The mail core - Postfix, Dovecot, NSD - is intentionally stable and conservative.

**Good contributions:**
- Bug fixes with a clear reproduction
- Hardening and security improvements
- Compatibility fixes for supported Ubuntu versions (22.04, 24.04, 26.04)
- Admin UI improvements (Vue 3, `frontend/`)
- Docker stack improvements
- Documentation

**Out of scope:**
- Reintroducing PHP, Nextcloud, Roundcube, or Z-Push
- Adding new external services without a strong case
- Changes that break idempotency of setup scripts

## Development setup

### Prerequisites

- Python 3.10+
- [Docker](https://docs.docker.com/get-docker/) with Compose (`docker compose version`)
- Node.js 20+ and npm (for admin UI work only)

### Quickstart

```bash
git clone https://github.com/boomboompower/mailinabox
cd mailinabox
python3 setup/boxctl docker    # interactive Docker setup wizard
```

Or manually:

```bash
cp deploy/docker/.env.example deploy/docker/.env
# set PRIMARY_HOSTNAME in .env

docker compose -f deploy/docker/docker-compose.yml \
  --profile oxi --profile filebrowser --profile radicale --profile monitoring \
  up --build
```

The admin panel is at `https://localhost:8443/admin`. The initial admin account is configured during the first-run wizard.

### Iterating on a single component

Rebuild one container without restarting the stack:

```bash
docker compose -f deploy/docker/docker-compose.yml --profile oxi up --build -d webmail
```

Re-run a setup script inside its container:

```bash
docker exec -it miab-mail bash -c "cd /opt/mailinabox && sudo setup/mail/postfix.sh"
```

### Admin UI (Vue 3)

The frontend lives in `frontend/` and is built separately from the setup scripts:

```bash
cd frontend
npm install
npm run dev      # dev server with hot reload - proxies API to the management daemon
npm run build    # production build, output to management/static/app/
```

The admin UI talks to the management daemon at `https://<box>/admin/api/`. In dev mode, Vite proxies API calls to the running Docker management container.

## Codebase layout

```
setup/
  infra/          # TLS, nginx, fail2ban, firewall, system
  mail/           # Postfix, Dovecot, rspamd, SpamAssassin
  webmail/        # oxi.email, Cypht, SnappyMail, Roundcube
  optional/       # FileBrowser, Radicale
  monitoring/     # Munin
  boxctl/         # interactive setup wizard (Python TUI)
  conf/
    nginx/        # nginx config templates
    mail/         # Dovecot, Postfix config templates
    fail2ban/     # jails and filters
    systemd/      # service unit files

management/       # Python management daemon and REST API
  services/       # mail, DNS, SSL, backup, web service logic

frontend/         # Vue 3 + Vite + TypeScript admin UI
  src/
    pages/        # one file per admin panel page
    components/   # shared components
    stores/       # Pinia stores
    composables/  # API hooks

deploy/
  docker/         # Dockerfiles, compose files, entrypoints
```

All setup scripts are **idempotent** - running them more than once must be safe. This is a hard requirement.

## Commit style

- One commit per logical change. Large features should be split by subsystem (e.g. separate commits for backend wiring, nginx config, and UI).
- Commit messages: short imperative title, blank line, then a brief explanation of *why* if the change isn't obvious.
- No "Co-Authored-By" trailers.

## Pull requests

Use the PR template. At minimum, describe what changed and how you tested it (Docker, bare metal, or neither - all are fine, just be honest).

Setup script changes should be tested with a full Docker stack run. Changes to `management/` or `frontend/` can be tested with the Docker management container alone.

## Tests

There is no automated test suite. Contributions that add test coverage are welcome.

## License

This project is licensed under the [MIT License](../LICENSE). By submitting a pull request you agree to license your contribution under MIT.

## Code of Conduct

This project has a [Code of Conduct](CODE_OF_CONDUCT.md).
