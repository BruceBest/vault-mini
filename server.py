#!/usr/bin/env python3
"""VaultMini — the simplest possible Vaultwarden frontend. One password, all passwords."""
import subprocess, json, os, sys, tempfile
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

VAULT_URL = "https://vault.404nfound.com"
BW_PATH = "/home/bruce/.npm-global/bin/bw"
BW_HOME = tempfile.mkdtemp(prefix="bw_session_")

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
  .container { width: 100%; max-width: 640px; padding: 2rem; }
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
  td { padding: 0.6rem 0.75rem; border-bottom: 1px solid #21262d; font-size: 0.9rem; }
  tr:hover td { background: #1c2128; }
  .name-cell { color: #58a6ff; font-weight: 500; }
  .copy-btn { background: none; border: 1px solid #30363d; color: #8b949e; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; cursor: pointer; width: auto; }
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
</style>
</head>
<body>
<div class="container">
  <h1>VaultMini</h1>
  <p class="sub">vault.404nfound.com</p>
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

async function unlock() {
  var btn = document.getElementById('unlock-btn');
  var errEl = document.getElementById('error');
  btn.disabled = true; btn.textContent = 'Unlocking...';
  errEl.style.display = 'none';

  try {
    var email = document.getElementById('email').value;
    var password = document.getElementById('password').value;
    currentEmail = email;

    var res = await fetch('/api/items', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: email, password: password})
    });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Unlock failed');
    
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
    html += '<tr data-search="' + (it.name||'').toLowerCase() + ' ' + (it.username||'').toLowerCase() + '">' +
      '<td class="name-cell" title="' + uri + '">' + n + '</td>' +
      '<td><span class="val">' + u + '</span><button class="copy-btn" onclick="copyFrom(this)">copy</button></td>' +
      '<td><span class="password-dots">********</span><span class="val" style="display:none">' + esc(it.password || '') + '</span>' +
      '<span class="show-hide" onclick="togglePw(this)">show</span>' +
      '<button class="copy-btn" onclick="copyFrom(this)">copy</button></td>' +
      '</tr>';
  }
  html += '</tbody></table>';
  results.innerHTML = html;
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
    var res = await fetch('/api/items', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: currentEmail, password: pw})
    });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    document.getElementById('re-password').value = '';
    document.getElementById('results').innerHTML = '';
    renderItems(data.items);
  } catch(e) {
    errEl.textContent = e.message; errEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Refresh';
  }
}

function lock() { location.reload(); }

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX)

@app.route('/api/items', methods=['POST'])
def api_items():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and master password required'}), 400

    env = os.environ.copy()
    env['HOME'] = BW_HOME
    env['BITWARDENCLI_APPDATA_DIR'] = BW_HOME

    try:
        subprocess.run([BW_PATH, 'config', 'server', VAULT_URL],
                       env=env, capture_output=True, timeout=10)
        result = subprocess.run(
            [BW_PATH, 'login', email, password, '--raw'],
            env=env, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            err = result.stderr.strip() or 'Login failed'
            return jsonify({'error': err}), 401

        session_key = result.stdout.strip()
        env['BW_SESSION'] = session_key

        result = subprocess.run(
            [BW_PATH, 'list', 'items'],
            env=env, capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return jsonify({'error': result.stderr.strip() or 'Failed to list items'}), 500

        items = json.loads(result.stdout)
        simplified = []
        for item in items:
            login = item.get('login', {})
            uris = login.get('uris') or []
            uri = uris[0].get('uri', '') if uris else ''
            simplified.append({
                'name': item.get('name', ''),
                'username': login.get('username', ''),
                'password': login.get('password', ''),
                'uri': uri,
            })

        subprocess.run([BW_PATH, 'logout'], env=env, capture_output=True, timeout=5)
        return jsonify({'items': simplified})

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Operation timed out'}), 504
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid response from vault'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f'VaultMini running on http://localhost:{port}')
    app.run(host='127.0.0.1', port=port, debug=False)
