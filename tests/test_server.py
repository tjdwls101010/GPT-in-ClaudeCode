"""Verify the HTTP contract with isolated external-provider endpoints."""

import base64
import http.client
import json
import pathlib
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.server import make_server


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name)
        self.requests = []
        requests = self.requests

        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.path, dict(self.headers), json.loads(body)))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(b'data: {"type":"response.completed"}\n\n')

            def log_message(self, *args):
                pass

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.start(self.upstream)
        url = f'http://127.0.0.1:{self.upstream.server_port}'
        token = 'test.' + base64.urlsafe_b64encode(json.dumps({'exp': time.time() + 3600}).encode()).decode().rstrip('=') + '.test'
        (self.path / 'auth.json').write_text(json.dumps({'tokens': {'access_token': token, 'account_id': 'test-account', 'refresh_token': 'DO_NOT_COPY'}}))
        self.config = {'port': 0, 'key': 'local-secret', 'codex_home': str(self.path), 'codex': 'codex', 'codex_base_url': url, 'claude_base_url': url, 'proxy_url': url, 'models': [{'id': 'gpt-example', 'name': 'Example', 'efforts': ['low', 'high'], 'default_effort': 'low'}]}
        self.gateway = make_server(self.config)
        self.start(self.gateway)

    def start(self, server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def post(self, path, body, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.request('POST', path, json.dumps(body), {'Content-Type': 'application/json', **(headers or {})})
        response = conn.getresponse()
        return response.status, response.read()

    def test_requests_without_local_key_are_rejected_before_any_upstream_call(self):
        status, _ = self.post('/v1/messages', {'model': 'gpt-example', 'messages': []})
        self.assertEqual(status, 401)
        self.assertEqual(self.requests, [])

    def test_claude_requests_keep_the_existing_login_and_stream_verbatim(self):
        status, body = self.post('/v1/messages?beta=true', {'model': 'claude-sonnet-5', 'messages': []}, {'x-gpt-in-claudecode-key': 'local-secret', 'Authorization': 'Bearer CLAUDE_LOGIN', 'anthropic-beta': 'oauth-test'})
        self.assertEqual(status, 200)
        self.assertEqual(body, b'data: {"type":"response.completed"}\n\n')
        path, headers, sent = self.requests[0]
        self.assertEqual(path, '/v1/messages?beta=true')
        headers = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(headers['authorization'], 'Bearer CLAUDE_LOGIN')
        self.assertEqual(headers['anthropic-beta'], 'oauth-test')
        self.assertNotIn('x-gpt-in-claudecode-key', headers)

    def test_gpt_uses_converter_without_forwarding_claude_credentials(self):
        status, _ = self.post('/v1/messages', {'model': 'gpt-example', 'messages': [], 'output_config': {'effort': 'high'}}, {'x-gpt-in-claudecode-key': 'local-secret', 'Authorization': 'Bearer CLAUDE_LOGIN', 'x-api-key': 'CLAUDE_KEY'})
        self.assertEqual(status, 200)
        headers = {k.lower(): v for k, v in self.requests[0][1].items()}
        self.assertEqual(headers['authorization'], 'Bearer local-secret')
        self.assertNotIn('x-api-key', headers)

    def test_unsupported_effort_is_rejected_instead_of_silently_changed(self):
        status, _ = self.post('/v1/messages', {'model': 'gpt-example', 'messages': [], 'output_config': {'effort': 'max'}}, {'x-gpt-in-claudecode-key': 'local-secret'})
        self.assertEqual(status, 400)
        self.assertEqual(self.requests, [])

    def test_codex_hop_reads_current_access_token_without_copying_refresh_token(self):
        status, _ = self.post('/codex/responses', {'model': 'gpt-example', 'input': [], 'reasoning': {'effort': 'high'}}, {'Authorization': 'Bearer local-secret', 'x-api-key': 'DO_NOT_FORWARD'})
        self.assertEqual(status, 200)
        path, headers, body = self.requests[0]
        headers = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(path, '/responses')
        self.assertTrue(headers['authorization'].startswith('Bearer test.'))
        self.assertEqual(headers['chatgpt-account-id'], 'test-account')
        self.assertNotIn('x-api-key', headers)
        self.assertNotIn('DO_NOT_COPY', json.dumps(self.requests))
        auth = json.loads((self.path / 'auth.json').read_text())
        auth['tokens']['access_token'] = auth['tokens']['access_token'].replace('test.', 'changed.', 1)
        (self.path / 'auth.json').write_text(json.dumps(auth))
        self.post('/codex/responses', {'model': 'gpt-example', 'input': [], 'reasoning': {'effort': 'high'}}, {'Authorization': 'Bearer local-secret'})
        headers = {k.lower(): v for k, v in self.requests[1][1].items()}
        self.assertTrue(headers['authorization'].startswith('Bearer changed.'))

    def test_expired_access_token_is_refreshed_by_codex_in_the_installed_home(self):
        auth_path = self.path / 'auth.json'
        auth = json.loads(auth_path.read_text())
        expired = base64.urlsafe_b64encode(b'{"exp":1}').decode().rstrip('=')
        auth['tokens']['access_token'] = 'expired.' + expired + '.test'
        auth_path.write_text(json.dumps(auth))
        executable = self.path / 'codex'
        executable.write_text("""#!/usr/bin/env python3
import base64, json, os, pathlib, sys, time
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    if request['method'] == 'account/read' and request['params']['refreshToken']:
        path = pathlib.Path(os.environ['CODEX_HOME']) / 'auth.json'
        auth = json.loads(path.read_text())
        claims = base64.urlsafe_b64encode(json.dumps({'exp':time.time()+3600}).encode()).decode().rstrip('=')
        auth['tokens']['access_token'] = 'refreshed.' + claims + '.test'
        path.write_text(json.dumps(auth))
    print(json.dumps({'id':request['id'], 'result':{}}), flush=True)
""")
        executable.chmod(0o755)
        self.config['codex'] = str(executable)
        status, _ = self.post('/codex/responses', {'model': 'gpt-example', 'input': [], 'reasoning': {'effort': 'high'}}, {'Authorization': 'Bearer local-secret'})
        self.assertEqual(status, 200)
        headers = {k.lower(): v for k, v in self.requests[0][1].items()}
        self.assertTrue(headers['authorization'].startswith('Bearer refreshed.'))
        self.assertEqual(json.loads(auth_path.read_text())['tokens']['refresh_token'], 'DO_NOT_COPY')


if __name__ == '__main__':
    unittest.main()
