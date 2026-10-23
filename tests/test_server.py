"""Regression tests use synthetic data only; no real vault or credentials."""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class AppTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix='vault-mini-tests-')
        self.env = patch.dict(os.environ, {
            'VAULT_URL': 'https://synthetic-vault.example',
            'BW_PATH': '/synthetic/bw', 'BASE_PATH': '',
            'TMPDIR': self.sandbox.name,
        })
        self.env.start()
        importlib.reload(server)
        # tempfile caches gettempdir; keep every test artifact inside sandbox.
        self.tmp = patch.object(tempfile, 'tempdir', self.sandbox.name)
        self.tmp.start()
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()

    def tearDown(self):
        for token in list(server.SESSIONS):
            server.discard_session(token)
        self.tmp.stop()
        self.env.stop()
        self.sandbox.cleanup()

    def cli(self, *results):
        return patch.object(server.subprocess, 'run', side_effect=results)

    def completed(self, stdout='', returncode=0, stderr=''):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def session(self, token='synthetic-token', expired=False):
        home = tempfile.mkdtemp(prefix='bw_')
        Path(home, 'synthetic-cache').write_text('not a real vault')
        server.SESSIONS[token] = {
            'bw_home': home, 'session_key': 'synthetic-session-key',
            'expires': time.time() + (-10 if expired else 600),
        }
        return home

    def test_root_urls_and_no_cache(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'var apiItems = "/api/items"', response.data)
        self.assertIn(b'var apiLock = "/api/lock"', response.data)
        self.assertIn(b'https://synthetic-vault.example', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_prefix_routes_and_boundary(self):
        with patch.dict(os.environ, BASE_PATH='/mini/'):
            importlib.reload(server)
        client = server.app.test_client()
        for path in ['/mini', '/mini/']:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'var apiItems = "/mini/api/items"', response.data)
            self.assertIn(b'var apiAttachment = "/mini/api/attachment"', response.data)
        self.assertEqual(client.get('/').status_code, 404)
        self.assertEqual(client.get('/minibus').status_code, 404)
        self.assertEqual(client.post('/api/items', json={}).status_code, 404)
        self.assertEqual(client.post('/mini/api/items', json={}).status_code, 400)

    def test_base_path_validation(self):
        for path in ['mini', '//mini', '/mini?x', '/mini/../admin', '/mini"', 'https://x']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                server.normalize_base_path(path)
        self.assertEqual(server.normalize_base_path('/mini/'), '/mini')
        self.assertEqual(server.normalize_base_path('/'), '')

    def test_runtime_requires_url_and_executable(self):
        with patch.object(server, 'VAULT_URL', ''), self.assertRaises(ValueError):
            server.validate_runtime()
        with patch.object(server, 'VAULT_URL', 'https://user:pass@example.com'), self.assertRaises(ValueError):
            server.validate_runtime()
        with patch.object(server.shutil, 'which', return_value=None), self.assertRaises(ValueError):
            server.validate_runtime()
        with patch.object(server.shutil, 'which', return_value='/synthetic/bw'):
            server.validate_runtime()

    def test_invalid_json_types(self):
        for endpoint in ['/api/items', '/api/attachment', '/api/lock']:
            for value in [None, [], 'string']:
                with self.subTest(endpoint=endpoint, value=value):
                    self.assertEqual(self.client.post(endpoint, json=value).status_code, 400)
        self.assertEqual(self.client.post('/api/items', json={'email': [], 'password': 'x'}).status_code, 400)
        self.assertEqual(self.client.post('/api/lock', json={'session_token': []}).status_code, 400)
        self.assertEqual(self.client.post('/api/attachment', json={'session_token': []}).status_code, 401)

    def test_login_password_not_in_argv_and_non_login_item(self):
        items = [{'id': 'synthetic-item', 'name': 'test', 'login': None, 'attachments': []}]
        with self.cli(self.completed(), self.completed('synthetic-session-key'), self.completed(json.dumps(items))) as run:
            response = self.client.post('/api/items', json={
                'email': ' test@example.invalid ', 'password': 'synthetic-master-password'
            })
        self.assertEqual(response.status_code, 200)
        command = run.call_args_list[1].args[0]
        self.assertNotIn('synthetic-master-password', command)
        self.assertIn('--passwordenv', command)
        self.assertEqual(run.call_args_list[1].kwargs['env']['BW_PASSWORD'], 'synthetic-master-password')
        self.assertNotIn('BW_PASSWORD', run.call_args_list[2].kwargs['env'])
        self.assertEqual(response.json['items'][0]['password'], '')
        self.assertIn(response.json['session_token'], server.SESSIONS)

    def test_login_failure_cleans_cli_directory(self):
        with self.cli(self.completed(), self.completed(returncode=1, stderr='Synthetic login denied')):
            response = self.client.post('/api/items', json={'email': 'a@example.invalid', 'password': 'synthetic'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(list(Path(self.sandbox.name).glob('bw_*')), [])

    def test_config_failure_stops_before_login(self):
        with self.cli(self.completed(returncode=1)) as run:
            response = self.client.post('/api/items', json={'email': 'a@example.invalid', 'password': 'synthetic'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(list(Path(self.sandbox.name).glob('bw_*')), [])

    def test_expiry_removes_cli_cache(self):
        home = self.session(expired=True)
        response = self.client.post('/api/attachment', json={'session_token': 'synthetic-token'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Path(home).exists())
        self.assertFalse(server.SESSIONS)

    def test_attachment_uses_attachment_id_and_cleans_temp(self):
        self.session()
        def fake_run(command, **kwargs):
            self.assertEqual(command[1:7], ['get', 'attachment', 'synthetic-attachment', '--itemid', 'synthetic-item', '--output'])
            self.assertTrue(command[-1].endswith(os.sep))
            Path(command[-1], '测试 " report.txt').write_bytes(b'synthetic attachment bytes')
            return self.completed()
        with patch.object(server.subprocess, 'run', side_effect=fake_run):
            response = self.client.post('/api/attachment', json={
                'session_token': 'synthetic-token', 'item_id': 'synthetic-item',
                'attachment_id': 'synthetic-attachment'
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'synthetic attachment bytes')
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            response.close()
        self.assertEqual(list(Path(self.sandbox.name).glob('bw_att_*')), [])

    def test_attachment_missing_ids(self):
        self.session()
        for item, attachment in [('', 'x'), ('x', ''), ('x', '--help'), ([], 'x')]:
            response = self.client.post('/api/attachment', json={
                'session_token': 'synthetic-token', 'item_id': item, 'attachment_id': attachment
            })
            self.assertEqual(response.status_code, 400)

    def test_attachment_timeout_cleans_temp(self):
        self.session()
        with self.cli(subprocess.TimeoutExpired(['synthetic-bw'], 60)):
            response = self.client.post('/api/attachment', json={
                'session_token': 'synthetic-token', 'item_id': 'x', 'attachment_id': 'y'
            })
        self.assertEqual(response.status_code, 504)
        self.assertEqual(list(Path(self.sandbox.name).glob('bw_att_*')), [])

    def test_lock_cleans_even_if_logout_times_out(self):
        home = self.session()
        with self.cli(subprocess.TimeoutExpired(['synthetic-bw'], 5)):
            response = self.client.post('/api/lock', json={'session_token': 'synthetic-token'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(server.SESSIONS)
        self.assertFalse(Path(home).exists())

    def test_environment_does_not_inherit_other_sessions(self):
        with patch.dict(os.environ, {'BW_SESSION': 'other', 'BW_CLIENTID': 'other', 'BW_PASSWORD': 'other'}):
            env = server.bw_env('/synthetic/home')
        self.assertNotIn('BW_SESSION', env)
        self.assertNotIn('BW_CLIENTID', env)
        self.assertNotIn('BW_PASSWORD', env)
        self.assertEqual(env['BITWARDENCLI_APPDATA_DIR'], '/synthetic/home')


class LauncherTests(unittest.TestCase):
    def test_real_http_process_root_and_prefix(self):
        # Launch the actual server with a non-authenticating fake bw executable.
        # A free TCP port is selected by binding a socket; no real backend is used.
        import socket
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='vault-mini-process-test-') as directory:
            fake = Path(directory, 'bw')
            fake.write_text('#!' + sys.executable + '\n' + '''
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
if args[:2] == ['config', 'server']:
    print('synthetic server configured')
elif args[:1] == ['login']:
    assert '--passwordenv' in args
    assert os.environ.get('BW_PASSWORD') == 'synthetic-only-password'
    print('synthetic-process-session')
elif args[:2] == ['list', 'items']:
    print(json.dumps([{'id': 'synthetic-item', 'name': 'fixture',
                      'login': {'username': 'synthetic-user', 'password': 'synthetic-item-password'},
                      'attachments': [{'id': 'synthetic-att', 'fileName': 'fixture.txt', 'size': 7}]}]))
elif args[:2] == ['get', 'attachment']:
    assert args[2] == 'synthetic-att'
    assert args[args.index('--itemid') + 1] == 'synthetic-item'
    target = Path(args[args.index('--output') + 1])
    (target / 'fixture.txt').write_bytes(b'fixture')
elif args == ['logout']:
    print('synthetic logout')
else:
    raise SystemExit('unexpected synthetic command')
''')
            fake.chmod(0o700)
            for prefix in ['', '/mini']:
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                env = dict(os.environ, VAULT_URL='https://synthetic.invalid',
                           BW_PATH=str(fake), BASE_PATH=prefix, PORT=str(port),
                           VAULT_MINI_PYTHON=sys.executable, TMPDIR=directory)
                process = subprocess.Popen([str(root/'run.sh')], env=env, cwd=directory,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                try:
                    url = f'http://127.0.0.1:{port}{prefix}/'
                    for _ in range(100):
                        if process.poll() is not None:
                            assert process.stdout is not None
                            self.fail('Server exited: ' + process.stdout.read().decode())
                        try:
                            with urlopen(url, timeout=1) as response:
                                body = response.read()
                                self.assertEqual(response.status, 200)
                                self.assertIn((prefix+'/api/items').encode(), body)
                                break
                        except OSError:
                            time.sleep(0.05)
                    else:
                        self.fail('Server did not become ready')
                    from urllib.request import Request
                    def post(path, payload):
                        request = Request(f'http://127.0.0.1:{port}{prefix}{path}',
                                          data=json.dumps(payload).encode(),
                                          headers={'Content-Type': 'application/json'},
                                          method='POST')
                        return urlopen(request, timeout=5)
                    with post('/api/items', {'email': 'synthetic@example.invalid',
                                             'password': 'synthetic-only-password'}) as response:
                        data = json.load(response)
                    self.assertEqual(data['items'][0]['name'], 'fixture')
                    token = data['session_token']
                    with post('/api/attachment', {'session_token': token,
                                                 'item_id': 'synthetic-item',
                                                 'attachment_id': 'synthetic-att'}) as response:
                        self.assertEqual(response.read(), b'fixture')
                    with post('/api/lock', {'session_token': token}) as response:
                        self.assertTrue(json.load(response)['ok'])
                    self.assertEqual(list(Path(directory).glob('bw_*')), [])
                    if prefix:
                        with self.assertRaises(HTTPError) as caught:
                            urlopen(f'http://127.0.0.1:{port}/', timeout=2)
                        self.assertEqual(caught.exception.code, 404)
                        caught.exception.close()
                finally:
                    process.terminate()
                    process.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
