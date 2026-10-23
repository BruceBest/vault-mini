# VaultMini

A minimal, read-only web frontend for Vaultwarden/Bitwarden with search, copy,
and attachment downloads. **VaultMini is not the password database**: the
Vaultwarden server remains the authoritative store.

```text
Browser --HTTPS--> VaultMini (Flask :8090) --> bw CLI --> Vaultwarden API
```

## Fresh installation (no old Python environment needed)

Prerequisites: Python **3.10+**, venv/pip, Git, and Bitwarden CLI. Download the
native CLI from the [official releases](https://github.com/bitwarden/clients/releases)
and verify its published checksum, or install `@bitwarden/cli` with npm when
Node.js is available. For a migration, pin the CLI to the version already tested
with your Vaultwarden server (the existing GLKB deployment uses **2026.4.2**).
Do not put a master password in a command or config file.

```bash
git clone https://github.com/BruceBest/vault-mini.git
cd vault-mini
# For repeatable deployments, check out an explicitly reviewed commit/tag.
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
command -v bw
bw --version

# No server.py editing required. Replace the URL with your actual server.
export VAULT_URL=https://your-vault.example.com
export BW_PATH="$(command -v bw)"
export BASE_PATH=''   # dedicated hostname / localhost root
./run.sh
# Open http://127.0.0.1:8090/
```

`run.sh` uses this checkout's `.venv/bin/python`, never a Hermes or another
application's Python. It does not install anything automatically. An optional
`VAULT_MINI_PYTHON` absolute path overrides the interpreter.

The repository does not automatically load `.env` files. Use exported shell
variables for manual runs or an explicit systemd `EnvironmentFile` below.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `VAULT_URL` | **required** | Full HTTP(S) Vaultwarden/Bitwarden server URL; use HTTPS outside a trusted local connection |
| `BW_PATH` | `bw` from `PATH` | CLI executable; use an absolute path for systemd |
| `BASE_PATH` | empty | Empty for `/`, or a prefix such as `/mini`; no URL/query/fragment |
| `HOST` | `127.0.0.1` | Listen address; keep loopback behind a same-host proxy |
| `PORT` | `8090` | Listen port; `./run.sh 8091` overrides it |

For the existing GLKB public URL, configure:

```bash
export VAULT_URL=https://vault-glkb.404nfound.com
export BW_PATH=/absolute/path/to/bw
export BASE_PATH=/mini
./run.sh
# http://127.0.0.1:8090/mini
```

The old repository's `vault.404nfound.com`, `/home/bruce/...`, and Hermes venv
paths are not deployment defaults. Get `BW_PATH` from the **new** machine.

## User-level systemd (Linux)

The supplied `vault-mini.service` is a **user unit**, not a system-wide unit.
It assumes a checkout at `~/vault-mini` and its `.venv` already installed.
Change `WorkingDirectory`/`ExecStart` if using a different path. Do not add a
`User=` field or install this file into `/etc/systemd/system` unchanged.

```bash
install -d -m 700 ~/.config/vault-mini
install -m 600 config.env.example ~/.config/vault-mini/config.env
# Edit VAULT_URL, BW_PATH, BASE_PATH and other values with your editor.
# config.env is systemd EnvironmentFile syntax: KEY=value, no `export`.

install -d ~/.config/systemd/user
install -m 644 vault-mini.service ~/.config/systemd/user/vault-mini.service
systemctl --user daemon-reload
systemctl --user enable --now vault-mini.service
systemctl --user status vault-mini.service
journalctl --user -u vault-mini.service -n 50 --no-pager
```

To keep the service running without an active login and start it at boot:

```bash
loginctl enable-linger "$(id -un)"
loginctl show-user "$(id -un)" -p Linger
```

If local policy disallows linger, ask the administrator. When acting via sudo
as a service user, set `XDG_RUNTIME_DIR=/run/user/<that-user's-UID>` and use
`systemctl --user` as that account. Do not assume UID 992 on a new machine.

## Reverse proxy / Cloudflare Tunnel

### Dedicated hostname

Set `BASE_PATH` empty. Example ingress before the catch-all rule:

```yaml
- hostname: mini.example.com
  service: http://127.0.0.1:8090
```

### Shared hostname under `/mini`

Set `BASE_PATH=/mini`. Preserve the prefix when forwarding:

```yaml
ingress:
  - hostname: vault.example.com
    path: ^/mini(/.*)?$
    service: http://127.0.0.1:8090
  - hostname: vault.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Put the `/mini` rule **before** the Vaultwarden catch-all. Cloudflared path
matching is regex, not glob matching. Validate the full existing tunnel config
before restarting it:

```bash
cloudflared --config /path/to/config.yml tunnel ingress validate
cloudflared --config /path/to/config.yml tunnel ingress rule https://vault.example.com/mini/api/items
```

The application strips its own prefix and uses Flask-generated API URLs, so
requests go to `/mini/api/items`, not Vaultwarden's `/api/items`.

Nginx equivalent (no trailing slash on `proxy_pass`, so the prefix is preserved):

```nginx
location = /mini {
    proxy_pass http://127.0.0.1:8090;
    proxy_set_header Host $host;
}
location /mini/ {
    proxy_pass http://127.0.0.1:8090;
    proxy_set_header Host $host;
}
```

If the proxy deliberately strips the prefix, reconfigure it to retain the
prefix for this setup; do not strip `/mini` twice. Requests outside a configured
prefix return 404.

For temporary local access use `ssh -L 8090:127.0.0.1:8090 user@server` and open
the matching root or `/mini` URL. Use a valid HTTPS public endpoint for clipboard
features and never expose the plain HTTP login form directly to the Internet.

## Migration: reinstall software, transfer only state

1. On the new host, install the container engine and pull the **same reviewed
   Vaultwarden version/digest** from its official registry. Download cloudflared
   and bw CLI independently. Clone a reviewed VaultMini commit and build `.venv`.
2. Configure this application using `VAULT_URL`, `BW_PATH` and `BASE_PATH`.
   Test the new runtime before the maintenance window. Do not copy the old
   Python site-packages, container storage, or Hermes venv.
3. Freeze writes and stop the old Vaultwarden before copying its complete
   persistent data directory. Preserve its SQLite database and matching WAL,
   attachments, existing Send files, `config.json`, and signing keys. Transfer
   its private service configuration (e.g. SMTP/ADMIN env) securely as well.
4. Restore to a clean new data directory and verify checksums **before startup**.
   Check a disposable database copy for integrity, then test local services.
5. Switch the public route, test real login/sync/attachments with an authorized
   user, and retain the old stopped deployment for rollback. Never serve two
   independent writable databases through simultaneous Tunnel connectors.

VaultMini has **no authoritative password database to migrate**. Its in-memory
session tokens are deliberately not copied: users log in again. If reusing a
Cloudflare Tunnel, transfer its specific runtime credential privately; if making
a new Tunnel, provision new credentials instead. No master-password/CSV export
is necessary for a full Vaultwarden data-directory migration.

If `VAULT_URL` points to the existing public domain, a pre-cutover `/mini` login
on the new host can still access the **old** backend. It is not proof that the
new database was restored. Test frontend routing without real credentials before
cutover and do authorized end-to-end validation after route ownership is clear.

## API and tests

All paths below are relative to `BASE_PATH`:

- `POST /api/items`: JSON `email` + `password`; returns simplified items and an
  opaque `session_token`. It logs in through bw and reads items, not writes them.
- `POST /api/attachment`: JSON `session_token`, `item_id`, `attachment_id`;
  downloads that attachment as an octet-stream. The CLI receives
  `bw get attachment <attachment_id> --itemid <item_id> --output <directory>/`.
- `POST /api/lock`: JSON `session_token`; attempts CLI logout, discards the local
  session and removes that session's temporary CLI directory.

```bash
.venv/bin/python -m unittest discover -s tests -v
bash -n run.sh
```

Tests use explicitly synthetic fixtures / mocked CLI results or a local fake
CLI. They never connect to your production vault or require a real password.
CI tests multiple Python versions. Passing these tests is not a substitute for
an authorized post-migration login/attachment test against the real deployment.

## Security and limitations

- **Trust the host and proxy.** Unlike an official browser-side client, VaultMini
  receives your master password and decrypted vault contents on its server. Do
  not use an untrusted host, enable debug logging of request bodies, or store
  passwords in config. Use HTTPS and appropriate access restrictions/rate limits.
- Passwords are passed to bw via its `--passwordenv` option, not CLI arguments.
  Same-account processes and privileged users may still inspect process memory
  or environment. This is not protection from a compromised host.
- Sessions live in **one process** for 10 minutes of inactivity, extended by
  attachment requests. Expired records/CLI directories are cleaned on the next
  items/attachment request; expiry is not a background timer and does not revoke
  an upstream session immediately. Restarting loses all in-memory sessions.
- Lock explicitly calls the backend now; simply closing a tab does not. Temporary
  CLI data is cleaned on handled failures, expiry and lock; a hard process kill
  can leave files in the OS temp directory. Use a private service-owned `TMPDIR`
  and plan safe cleanup while stopped. Never migrate those temporary files.
- Attachment downloads are buffered in memory before temporary files are deleted.
  Size your host/proxy limits for your attachments; this is not a large-file
  streaming service.
- The launcher uses Flask's built-in single-process server with threading
  disabled to keep in-memory session cleanup serialized. It is intended for
  low-volume controlled use, **not a hardened high-availability public service**.
  Multi-worker WSGI deployment requires redesigning session storage/coordination.
- There is no 2FA/SSO/API-key prompt flow in this frontend. Unsupported CLI auth
  challenges fail rather than reading interactive stdin. Use official clients
  for those workflows; do not disable account protections to accommodate it.
- Users must have completed normal Vaultwarden registration with encryption
  keys. An invitation alone is not a complete account.
- Use individual accounts and organization sharing for teams; do not share a
  master password. This interface does not implement organization management or
  vault-item editing.
