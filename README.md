# VaultMini

A minimal single-page frontend for Vaultwarden/Bitwarden.  
Open → enter master password → see all vault items in a clean table.  
**Supports attachments** — click to download any file stored in vault items.  
No organizations, no collections, no browser extensions, no noise.

## Architecture

```
Browser  ──→  VaultMini (Flask :8090)  ──→  bw CLI  ──→  Vaultwarden API (your server)
```

- **server.py**: Flask app serving the HTML page + `/api/items` + `/api/attachment` endpoints
- **bw CLI**: Bitwarden CLI (authenticates, fetches, decrypts vault items & attachments)
- **Session model**: Login once, session key held in memory (10 min TTL). Attachment downloads reuse the same session.

## Prerequisites

- Python 3.8+
- `flask` (`pip install flask`)
- Bitwarden CLI (`@bitwarden/cli` via npm): `npm install -g @bitwarden/cli`
- A running Vaultwarden (or Bitwarden) instance with at least one user account that has complete encryption keys (i.e., properly registered through the web vault, not just invited)

## Quick Start

```bash
# 1. Install dependencies
pip install flask
npm install -g @bitwarden/cli

# 2. Edit VAULT_URL and BW_PATH in server.py
VAULT_URL = "https://your-vault.example.com"
BW_PATH = "/usr/local/bin/bw"  # or wherever `which bw` points

# 3. Run
python3 server.py 8090
# → http://localhost:8090
```

## Configuration

Open `server.py` and edit the globals near the top:

```python
VAULT_URL = "https://vault.404nfound.com"   # Your Vaultwarden/Bitwarden server
BW_PATH = "/home/bruce/.npm-global/bin/bw"   # Path to bw CLI binary (run `which bw`)
```

## Systemd Service (Linux)

Edit `vault-mini.service` to match your paths and user:

```ini
[Unit]
Description=VaultMini - Minimal Vaultwarden Frontend
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/vault-mini
ExecStart=/usr/bin/python3 /path/to/vault-mini/server.py 8090
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo cp vault-mini.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vault-mini
```

## Exposing to the Internet

### Option A: Cloudflare Tunnel

Add to your `cloudflared` config:

```yaml
- hostname: mini.yourdomain.com
  service: http://localhost:8090
```

Then add the DNS route:

```bash
cloudflared tunnel route dns <tunnel-id> mini.yourdomain.com
```

### Option B: Nginx reverse proxy

```nginx
location /mini/ {
    proxy_pass http://127.0.0.1:8090/;
    proxy_set_header Host $host;
}
```

### Option C: SSH tunnel (temporary)

```bash
ssh -L 8090:localhost:8090 user@server
# Then open http://localhost:8090 locally
```

## API

Single endpoint used by the frontend:

**`POST /api/items`**

Request:
```json
{
  "email": "user@example.com",
  "password": "master-password"
}
```

Response (200):
```json
{
  "items": [
    {
      "id": "abc123...",
      "name": "GitHub",
      "username": "lab-bot",
      "password": "ghp_xxxx",
      "uri": "https://github.com",
      "attachments": [
        {"id": "att-1", "fileName": "id_rsa", "size": 3243}
      ]
    }
  ],
  "session_token": "a1b2c3..."
}
```

Response (401):
```json
{"error": "Login failed"}
```

**`POST /api/attachment`**

Request:
```json
{
  "session_token": "a1b2c3...",
  "item_id": "abc123...",
  "attachment_id": "att-1"
}
```

Response (200): Raw file bytes with `Content-Disposition: attachment` header (browser triggers download).

Response (401):
```json
{"error": "Session expired. Please refresh."}
```

## Important Notes

1. **User must have complete encryption keys.** If the account was only "invited" via admin panel but never completed registration through the web vault, `bw login` will fail with "Failed to decrypt user key" or "Legacy encryption is no longer supported." The account must be fully registered — create it through the normal web vault sign-up flow.

2. **Session-based.** `/api/items` logs in and returns a `session_token`. Attachment downloads reuse the same session (10 min TTL). Clicking "Lock" or waiting 10 minutes logs out the session.

3. **No write operations.** This is read-only. You cannot add, edit, or delete vault items through VaultMini.

4. **Single-account.** The frontend expects one email + one master password. For team use, share one account's credentials.

## Files

```
vault-mini/
├── README.md             # This file
├── server.py             # Flask app (inline HTML + API endpoint)
├── run.sh                # Quick launch script
└── vault-mini.service    # systemd unit file
```
