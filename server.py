#!/usr/bin/env python3
"""VaultMini — the simplest possible Vaultwarden frontend."""
import subprocess, json, os, sys, tempfile, time, uuid, mimetypes
from flask import Flask, request, jsonify, render_template_string, send_file, Response

app = Flask(__name__)

VAULT_URL = "https://vault.404nfound.com"
BW_PATH = "/home/bruce/.npm-global/bin/bw"

# In-memory session store: token → {session_key, bw_home, expires}
SESSIONS = {}

def bw_env(home):
    env = os.environ.copy()
    env['HOME'] = home
    env['BITWARDENCLI_APPDATA_DIR'] = home
    return env

def cleanup_sessions():
    now = time.time()
    expired = [t for t, s in list(SESSIONS.items()) if s['expires'] < now]
    for t in expired:
        del SESSIONS[t]

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
var sessionToken = '';

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

    html += '<tr data-search="' + (it.name||'').toLowerCase() + ' ' + (it.username||'').toLowerCase() + '">' +
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
    var res = await fetch('/api/attachment', {
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
    var res = await fetch('/api/items', {
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
    cleanup_sessions()
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and master password required'}), 400

    home = tempfile.mkdtemp(prefix="bw_")
    env = bw_env(home)

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
            'expires': time.time() + 600,
        }

        return jsonify({'items': simplified, 'session_token': token})

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Operation timed out'}), 504
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid response from vault'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attachment', methods=['POST'])
def api_attachment():
    cleanup_sessions()
    data = request.get_json()
    token = data.get('session_token', '')
    item_id = data.get('item_id', '')
    attachment_id = data.get('attachment_id', '')

    if not token or token not in SESSIONS:
        return jsonify({'error': 'Session expired. Please refresh.'}), 401

    session = SESSIONS[token]
    env = bw_env(session['bw_home'])
    env['BW_SESSION'] = session['session_key']

    # Refresh TTL
    session['expires'] = time.time() + 600

    out_dir = tempfile.mkdtemp(prefix="bw_att_")
    try:
        result = subprocess.run(
            [BW_PATH, 'get', 'attachment', item_id, '--itemid', item_id,
             '--output', out_dir],
            env=env, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return jsonify({'error': result.stderr.strip() or 'Failed to get attachment'}), 500

        # bw outputs the file as the attachment's original filename in out_dir
        files = os.listdir(out_dir)
        if not files:
            return jsonify({'error': 'No file output from bw'}), 500

        filepath = os.path.join(out_dir, files[0])
        filename = files[0]

        mime, _ = mimetypes.guess_type(filename)
        if not mime:
            mime = 'application/octet-stream'

        def generate():
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
            # Clean up after streaming
            os.unlink(filepath)
            os.rmdir(out_dir)

        return Response(
            generate(),
            mimetype=mime,
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Attachment download timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lock', methods=['POST'])
def api_lock():
    data = request.get_json()
    token = data.get('session_token', '')
    if token in SESSIONS:
        session = SESSIONS.pop(token)
        env = bw_env(session['bw_home'])
        env['BW_SESSION'] = session['session_key']
        subprocess.run([BW_PATH, 'logout'], env=env, capture_output=True, timeout=5)
    return jsonify({'ok': True})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f'VaultMini running on http://localhost:{port}')
    app.run(host='127.0.0.1', port=port, debug=False)
