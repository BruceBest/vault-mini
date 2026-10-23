#!/usr/bin/env python3
"""VaultMini — the simplest possible Vaultwarden frontend."""
from io import BytesIO
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit
from flask import Flask, request, jsonify, render_template_string, send_file
from werkzeug.exceptions import NotFound


def normalize_base_path(value):
    """Only accept literal URL path segments, never URLs/query strings."""
    value = value.rstrip('/')
    if not value:
        return ''
    if not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)+', value):
        raise ValueError('BASE_PATH must be empty or a path such as /mini')
    return value


class PathPrefixMiddleware:
    """Mount the whole application below a prefix; proxy must retain it."""

    def __init__(self, application, prefix):
        self.application = application
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '/')
        if self.prefix:
            if path != self.prefix and not path.startswith(self.prefix + '/'):
                return NotFound()(environ, start_response)
            environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + self.prefix
            environ['PATH_INFO'] = path[len(self.prefix):] or '/'
        return self.application(environ, start_response)

app = Flask(__name__)

VAULT_URL = os.environ.get('VAULT_URL', '').strip().rstrip('/')
BW_PATH = os.environ.get('BW_PATH') or shutil.which('bw') or 'bw'
BASE_PATH = normalize_base_path(os.environ.get('BASE_PATH', ''))
SESSION_TTL = 600
app.wsgi_app = PathPrefixMiddleware(app.wsgi_app, BASE_PATH)


def validate_runtime():
    parsed = urlsplit(VAULT_URL)
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError('Set VAULT_URL to your Vaultwarden HTTP(S) server URL')
    if not shutil.which(BW_PATH):
        raise ValueError('bw CLI not found; install it and set BW_PATH or PATH')

# In-memory session store: token → {session_key, bw_home, expires}
SESSIONS = {}

def bw_env(home):
    env = os.environ.copy()
    env['HOME'] = home
    env['BITWARDENCLI_APPDATA_DIR'] = home
    # Do not inherit a different user's CLI session or automatic login secrets.
    for key in ('BW_SESSION', 'BW_CLIENTID', 'BW_CLIENTSECRET', 'BW_PASSWORD'):
        env.pop(key, None)
    return env


def discard_session(token):
    session = SESSIONS.pop(token, None)
    if session:
        shutil.rmtree(session['bw_home'], ignore_errors=True)


def cleanup_sessions():
    now = time.time()
    expired = [t for t, s in list(SESSIONS.items()) if s['expires'] < now]
    for t in expired:
        discard_session(t)

INDEX = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VaultMini</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  .container { width: 100%; max-width: 720px; padding: 2rem; }
  h1 { font-size: 1.5rem; font-weight: 600; color: #58a6ff; margin-bottom: 0.25rem; }
  .sub { color: #8b949e; font-size: 0.85rem; margin-bottom: 1.5rem; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; }
  label { display: block; font-size: 0.8rem; color: #8b949e; margin-bottom: 0.35rem; margin-top: 1rem; }
  label:first-of-type { margin-top: 0; }
  input { width: 100%; padding: 0.6rem 0.75rem; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 0.95rem; outline: none; }
  input:focus { border-color: #58a6ff; }
  button { width: 100%; padding: 0.65rem; background: #238636; color: #fff; border: none; border-radius: 6px; font-size: 0.95rem; font-weight: 500; cursor: pointer; }
  button:hover { background: #2ea043; }
  button:disabled { background: #30363d; cursor: not-allowed; }
  .error { color: #f85149; font-size: 0.85rem; margin-top: 0.75rem; padding: 0.5rem; background: #1a0b0b; border-radius: 4px; display: none; }
  table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
  th { text-align: left; font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.5rem 0.75rem; border-bottom: 1px solid #21262d; }
  td { padding: 0.6rem 0.75rem; border-bottom: 1px solid #21262d; font-size: 0.9rem; vertical-align: top; }
  tr:hover td { background: #1c2128; }
  .name-cell { color: #58a6ff; font-weight: 500; }
  .copy-btn { background: none; border: 1px solid #30363d; color: #8b949e; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; cursor: pointer; width: auto; margin-left: 0.35rem; }
  .copy-btn:hover { border-color: #58a6ff; color: #58a6ff; }
  .copied { border-color: #238636 !important; color: #3fb950 !important; }
  .password-dots { letter-spacing: 0.15em; }
  .show-hide { cursor: pointer; color: #58a6ff; font-size: 0.75rem; margin-left: 0.35rem; user-select: none; }
  .search-box { width: 100%; padding: 0.5rem 0.75rem; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 0.9rem; outline: none; margin-bottom: 0.75rem; }
  .count { color: #8b949e; font-size: 0.8rem; margin-bottom: 0.5rem; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
  .toolbar .email { color: #8b949e; font-size: 0.8rem; }
  .toolbar button { width: auto; padding: 0.35rem 0.75rem; font-size: 0.8rem; background: #30363d; margin: 0; }
  .toolbar button:hover { background: #484f58; }
  .att-link { color: #58a6ff; font-size: 0.8rem; text-decoration: none; cursor: pointer; display: inline-block; margin-right: 0.5rem; }
  .att-link:hover { text-decoration: underline; }
  .att-link.downloading { color: #8b949e; cursor: wait; text-decoration: none; }
  .att-section { margin-top: 0.25rem; }
  .att-section .att-label { color: #484f58; font-size: 0.7rem; margin-right: 0.25rem; }
</style>
</head>
<body>
<div class="container">
  <h1>VaultMini</h1>
  <p class="sub">{{ vault_url }}</p>
  <div class="card" id="login-card">
    <label for="email">Email</label>
    <input type="email" id="email" autocomplete="username" placeholder="your@email.com">
    <label for="password">Master Password</label>
    <input type="password" id="password" autocomplete="current-password" placeholder="********">
    <button id="unlock-btn" onclick="unlock()">Unlock Vault</button>
    <div class="error" id="error"></div>
  </div>
  <div id="results"></div>
</div>
<script>
var currentEmail = '';
var sessionToken = '';
var apiItems = {{ url_for('api_items') | tojson }};
var apiAttachment = {{ url_for('api_attachment') | tojson }};
var apiLock = {{ url_for('api_lock') | tojson }};

async function unlock() {
  var btn = document.getElementById('unlock-btn');
  var errEl = document.getElementById('error');
  btn.disabled = true; btn.textContent = 'Unlocking...';
  errEl.style.display = 'none';

  try {
    var email = document.getElementById('email').value;
    var password = document.getElementById('password').value;
    currentEmail = email;

    var res = await fetch(apiItems, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: email, password: password})
    });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Unlock failed');

    sessionToken = data.session_token;
    document.getElementById('password').value = '';
    showLoggedIn(email);
    renderItems(data.items);
  } catch(e) {
    errEl.textContent = e.message;
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Unlock Vault';
  }
}

function showLoggedIn(email) {
  document.getElementById('login-card').innerHTML =
    '<div class="toolbar">' +
    '<span class="email">' + esc(email) + '</span>' +
    '<button onclick="lock()">Lock</button>' +
    '</div>' +
    '<input type="password" id="re-password" placeholder="Master password" style="margin-bottom:0.5rem">' +
    '<button id="refresh-btn" onclick="refresh()" style="margin-top:0">Refresh</button>' +
    '<div class="error" id="error2"></div>';
}

function renderItems(items) {
  var results = document.getElementById('results');
  if (!items || items.length === 0) {
    results.innerHTML = '<p style="color:#8b949e;margin-top:1rem">No items in vault.</p>';
    return;
  }

  var html = '<input type="text" class="search-box" id="search" placeholder="Filter..." oninput="doFilter()">' +
    '<div class="count" id="count">' + items.length + ' items</div>' +
    '<table><thead><tr><th>Name</th><th>User</th><th>Pass</th></tr></thead><tbody>';

  window._allItems = items;

  for (var i = 0; i < items.length; i++) {
    var it = items[i];
    var n = esc(it.name || '(none)');
    var u = esc(it.username || '');
    var uri = esc(it.uri || '');

    // Attachments
    var attHtml = '';
    if (it.attachments && it.attachments.length > 0) {
      attHtml = '<div class="att-section"><span class="att-label">📎</span>';
      for (var j = 0; j < it.attachments.length; j++) {
        var att = it.attachments[j];
        attHtml += '<a class="att-link" href="#" data-att-id="' + esc(att.id) + '" data-att-name="' + esc(att.fileName) + '" data-item-id="' + esc(it.id) + '" title="' + esc(att.fileName) + ' (' + formatSize(att.size) + ')">' + esc(att.fileName) + '</a>';
      }
      attHtml += '</div>';
    }

    html += '<tr data-search="' + esc(((it.name||'') + ' ' + (it.username||'')).toLowerCase()) + '">' +
      '<td class="name-cell" title="' + uri + '">' + n + attHtml + '</td>' +
      '<td><span class="val">' + u + '</span><button class="copy-btn" onclick="copyFrom(this)">copy</button></td>' +
      '<td><span class="password-dots">********</span><span class="val" style="display:none">' + esc(it.password || '') + '</span>' +
      '<span class="show-hide" onclick="togglePw(this)">show</span>' +
      '<button class="copy-btn" onclick="copyFrom(this)">copy</button></td>' +
      '</tr>';
  }
  html += '</tbody></table>';
  results.innerHTML = html;
}

function formatSize(bytes) {
  if (!bytes) return '0 B';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/(1024*1024)).toFixed(1) + ' MB';
}

// Delegated click handler for attachment links (uses data-att-* attributes)
document.addEventListener('click', function(e) {
  var link = e.target.closest('.att-link');
  if (!link) return;
  e.preventDefault();
  var attId = link.getAttribute('data-att-id');
  var fileName = link.getAttribute('data-att-name');
  var itemId = link.getAttribute('data-item-id');
  if (!attId || !itemId) return;
  downloadAtt(link, attId, fileName, itemId);
});

async function downloadAtt(link, attId, fileName, itemId) {
  var origText = link.textContent;
  link.classList.add('downloading');
  link.textContent = 'downloading...';

  try {
    var res = await fetch(apiAttachment, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_token: sessionToken,
        item_id: itemId,
        attachment_id: attId
      })
    });

    if (!res.ok) {
      var err = await res.json();
      throw new Error(err.error || 'Download failed');
    }

    var blob = await res.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch(e) {
    alert('Download failed: ' + e.message);
  } finally {
    link.classList.remove('downloading');
    link.textContent = origText;
  }
}

function togglePw(el) {
  var td = el.parentElement;
  var dots = td.querySelector('.password-dots');
  var real = td.querySelector('.val');
  if (dots.style.display === 'none') {
    dots.style.display = ''; real.style.display = 'none'; el.textContent = 'show';
  } else {
    dots.style.display = 'none'; real.style.display = ''; el.textContent = 'hide';
  }
}

function copyFrom(btn) {
  var text = btn.parentElement.querySelector('.val').textContent;
  navigator.clipboard.writeText(text).then(function() {
    btn.classList.add('copied');
    var old = btn.textContent;
    btn.textContent = 'copied!';
    setTimeout(function() { btn.classList.remove('copied'); btn.textContent = old; }, 1200);
  });
}

function doFilter() {
  var q = document.getElementById('search').value.toLowerCase();
  var rows = document.querySelectorAll('tbody tr');
  var vis = 0;
  for (var i = 0; i < rows.length; i++) {
    var ok = !q || rows[i].getAttribute('data-search').indexOf(q) >= 0;
    rows[i].style.display = ok ? '' : 'none';
    if (ok) vis++;
  }
  document.getElementById('count').textContent = vis + ' / ' + rows.length + ' items';
}

async function refresh() {
  var pw = document.getElementById('re-password').value;
  var errEl = document.getElementById('error2');
  var btn = document.getElementById('refresh-btn');
  if (!pw) { errEl.textContent = 'Enter password'; errEl.style.display='block'; return; }
  errEl.style.display = 'none'; btn.disabled = true; btn.textContent = 'Refreshing...';
  try {
    var res = await fetch(apiItems, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: currentEmail, password: pw})
    });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    sessionToken = data.session_token;
    document.getElementById('re-password').value = '';
    document.getElementById('results').innerHTML = '';
    renderItems(data.items);
  } catch(e) {
    errEl.textContent = e.message; errEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Refresh';
  }
}

async function lock() {
  // Clear decrypted values immediately, even if the logout request fails.
  document.getElementById('results').innerHTML = '';
  window._allItems = [];
  try {
    await fetch(apiLock, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_token: sessionToken})
    });
  } finally {
    sessionToken = '';
    location.reload();
  }
}

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX, vault_url=VAULT_URL)

@app.route('/api/items', methods=['POST'])
def api_items():
    cleanup_sessions()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    email = data.get('email', '')
    if isinstance(email, str):
        email = email.strip()
    password = data.get('password', '')

    if (not isinstance(email, str) or not isinstance(password, str)
            or not email or email.startswith('-') or not password):
        return jsonify({'error': 'Email and master password required'}), 400

    home = tempfile.mkdtemp(prefix="bw_")
    env = bw_env(home)
    keep_home = False

    try:
        configured = subprocess.run(
            [BW_PATH, 'config', 'server', VAULT_URL],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10
        )
        if configured.returncode != 0:
            return jsonify({'error': 'Failed to configure vault server'}), 502
        login_env = dict(env, BW_PASSWORD=password)
        result = subprocess.run(
            [BW_PATH, 'login', email, '--passwordenv', 'BW_PASSWORD', '--raw'],
            env=login_env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            err = result.stderr.strip() or 'Login failed'
            return jsonify({'error': err}), 401

        session_key = result.stdout.strip()
        if not session_key:
            return jsonify({'error': 'Empty CLI session key'}), 502
        env['BW_SESSION'] = session_key

        result = subprocess.run(
            [BW_PATH, 'list', 'items'],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return jsonify({'error': result.stderr.strip() or 'Failed to list items'}), 500

        items = json.loads(result.stdout)
        if not isinstance(items, list):
            return jsonify({'error': 'Invalid item list from vault'}), 502
        simplified = []
        for item in items:
            login = item.get('login') or {}
            uris = login.get('uris') or []
            uri = uris[0].get('uri', '') if uris else ''

            atts = item.get('attachments') or []
            attachments = [{
                'id': a.get('id', ''),
                'fileName': a.get('fileName', 'unnamed'),
                'size': a.get('size', 0),
            } for a in atts]

            simplified.append({
                'id': item.get('id', ''),
                'name': item.get('name', ''),
                'username': login.get('username', ''),
                'password': login.get('password', ''),
                'uri': uri,
                'attachments': attachments,
            })

        # Store session for attachment downloads (10 min TTL)
        token = uuid.uuid4().hex
        SESSIONS[token] = {
            'session_key': session_key,
            'bw_home': home,
            'expires': time.time() + SESSION_TTL,
        }
        keep_home = True
        return jsonify({'items': simplified, 'session_token': token})

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Operation timed out'}), 504
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid response from vault'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if not keep_home:
            shutil.rmtree(home, ignore_errors=True)


@app.route('/api/attachment', methods=['POST'])
def api_attachment():
    cleanup_sessions()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    token = data.get('session_token', '')
    item_id = data.get('item_id', '')
    attachment_id = data.get('attachment_id', '')
    if not isinstance(token, str) or not token or token not in SESSIONS:
        return jsonify({'error': 'Session expired. Please refresh.'}), 401
    if not all(isinstance(value, str) and value and not value.startswith('-')
               for value in (item_id, attachment_id)):
        return jsonify({'error': 'Item and attachment IDs required'}), 400

    session = SESSIONS[token]
    env = bw_env(session['bw_home'])
    env['BW_SESSION'] = session['session_key']
    session['expires'] = time.time() + SESSION_TTL

    # Read into a response buffer before deleting decrypted temporary files.
    # This intentionally buffers an attachment in memory, as the browser already does.
    with tempfile.TemporaryDirectory(prefix='bw_att_') as out_dir:
        try:
            result = subprocess.run(
                [BW_PATH, 'get', 'attachment', attachment_id, '--itemid', item_id,
                 '--output', out_dir + os.sep],
                env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                return jsonify({'error': result.stderr.strip() or 'Failed to get attachment'}), 500
            files = [name for name in os.listdir(out_dir)
                     if os.path.isfile(os.path.join(out_dir, name))
                     and not os.path.islink(os.path.join(out_dir, name))]
            if len(files) != 1:
                return jsonify({'error': 'Expected one attachment output from bw'}), 502
            filename = files[0]
            with open(os.path.join(out_dir, filename), 'rb') as f:
                payload = BytesIO(f.read())
            return send_file(payload, mimetype='application/octet-stream',
                             as_attachment=True, download_name=filename)
        except subprocess.TimeoutExpired:
            return jsonify({'error': 'Attachment download timed out'}), 504
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/lock', methods=['POST'])
def api_lock():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    token = data.get('session_token', '')
    if not isinstance(token, str):
        return jsonify({'error': 'Session token must be a string'}), 400
    session = SESSIONS.get(token)
    if session:
        env = bw_env(session['bw_home'])
        env['BW_SESSION'] = session['session_key']
        try:
            subprocess.run([BW_PATH, 'logout'], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            discard_session(token)
    return jsonify({'ok': True})


@app.after_request
def prevent_secret_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


if __name__ == '__main__':
    try:
        validate_runtime()
        port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('PORT', '8090'))
        if not 1 <= port <= 65535:
            raise ValueError('PORT must be between 1 and 65535')
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    host = os.environ.get('HOST', '127.0.0.1')
    print(f'VaultMini running on http://{host}:{port}{BASE_PATH}/')
    app.run(host=host, port=port, debug=False, threaded=False)
