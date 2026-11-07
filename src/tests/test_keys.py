import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import keystore
import run_models as runner


class AuthServer:
    """A generic OpenAI-style server whose model list needs `Authorization: Bearer <key>`."""

    def __init__(self, key='good-key'):
        self.key = key
        self.calls = []

    def __enter__(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                fake.calls.append((self.path, self.headers.get('Authorization')))
                if self.path == '/v1/models' and self.headers.get('Authorization') == f'Bearer {fake.key}':
                    body, status = {'data': [{'id': 'm1', 'owned_by': 'test'}]}, 200
                elif self.path == '/v1/models':
                    body, status = {'error': 'Not authenticated'}, 401
                else:
                    body, status = {}, 404
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()


class ConfigDirCase(unittest.TestCase):
    """Every test gets its own config folder, so the real ~/.config is never touched."""

    def setUp(self):
        self.config = tempfile.TemporaryDirectory()
        self.addCleanup(self.config.cleanup)
        env = unittest.mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': self.config.name})
        env.start()
        self.addCleanup(env.stop)

    @property
    def keyfile(self):
        return Path(self.config.name) / 'llmtest' / 'keys.json'


class KeystoreTests(ConfigDirCase):
    def test_round_trip_one_key_per_server_and_overwrite(self):
        self.assertEqual(keystore.load('http://a:1'), '')
        keystore.save('http://a:1', 'key-a')
        keystore.save('http://b:2', 'key-b')
        self.assertEqual((keystore.load('http://a:1'), keystore.load('http://b:2')), ('key-a', 'key-b'))
        keystore.save('http://a:1', 'key-a2')
        self.assertEqual(keystore.load('http://a:1'), 'key-a2')
        self.assertEqual(keystore.load('http://b:2'), 'key-b')

    def test_only_the_owner_can_read_it_even_if_the_file_was_loose_before(self):
        keystore.save('http://a:1', 'k')
        self.assertEqual(stat.S_IMODE(self.keyfile.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.keyfile.parent.stat().st_mode), 0o700)
        self.keyfile.chmod(0o644)
        keystore.save('http://a:1', 'k2')
        self.assertEqual(stat.S_IMODE(self.keyfile.stat().st_mode), 0o600)
        self.assertEqual(list(self.keyfile.parent.glob('*.tmp')), [])

    def test_location_follows_xdg_then_falls_back_to_home_config(self):
        self.assertEqual(keystore.path(), self.keyfile)
        with unittest.mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': ''}), \
                unittest.mock.patch.object(Path, 'home', return_value=Path('/home/someone')):
            self.assertEqual(keystore.path(), Path('/home/someone/.config/llmtest/keys.json'))

    def test_a_damaged_or_foreign_file_is_ignored_and_replaced_on_save(self):
        self.keyfile.parent.mkdir(parents=True)
        for junk in ('not json', '[1, 2]', '{"http://a:1": 5, "http://b:2": ""}'):
            self.keyfile.write_text(junk)
            self.assertEqual(keystore.load('http://a:1'), '')
        keystore.save('http://a:1', 'good')
        self.assertEqual(json.loads(self.keyfile.read_text()), {'http://a:1': 'good'})

    def test_forget_one_or_all_and_the_file_goes_away_when_empty(self):
        keystore.save('http://a:1', 'ka')
        keystore.save('http://b:2', 'kb')
        self.assertEqual(keystore.forget(['http://nope:3']), 0)
        self.assertEqual(keystore.forget(['http://a:1']), 1)
        self.assertEqual(keystore.load('http://b:2'), 'kb')
        self.assertEqual(keystore.forget(), 1)
        self.assertFalse(self.keyfile.exists())
        self.assertEqual(keystore.forget(), 0)


class ConnectTests(ConfigDirCase):
    def connect(self, server, key='', typed=None, tty=True, answer=''):
        """Run runner.connect; typed is what the hidden prompt returns (None: must not be asked)."""
        def password(_prompt):
            if typed is None:
                raise AssertionError('must not ask for a key')
            return typed

        def reply(_prompt):
            if answer is None:
                raise EOFError
            return answer
        with unittest.mock.patch.object(runner.getpass, 'getpass', password), \
                unittest.mock.patch.object(runner.os, 'isatty', return_value=tty), \
                unittest.mock.patch('builtins.input', reply), \
                contextlib.redirect_stdout(io.StringIO()) as shown:
            result = runner.connect(server.url, key, 'auto')
        return result, shown.getvalue()

    def test_first_run_asks_then_remembers_and_the_next_run_does_not_ask(self):
        with AuthServer() as server:
            (found, models), shown = self.connect(server, typed='good-key')
            self.assertEqual([m['id'] for m in models], ['m1'])
            self.assertIn('Saved', shown)
            self.assertEqual(keystore.load(found.root), 'good-key')
            (_, models), shown = self.connect(server, typed=None)  # would fail if it asked
            self.assertEqual([m['id'] for m in models], ['m1'])
            self.assertIn('Using the remembered API key', shown)

    def test_declining_saves_nothing(self):
        with AuthServer() as server:
            self.connect(server, typed='good-key', answer='n')
        self.assertFalse(self.keyfile.exists())

    def test_end_of_input_at_the_offer_saves_nothing_and_does_not_crash(self):
        with AuthServer() as server:
            (_, models), _ = self.connect(server, typed='good-key', answer=None)
        self.assertTrue(models)
        self.assertFalse(self.keyfile.exists())

    def test_a_rotated_key_is_noticed_and_replaced(self):
        with AuthServer() as server:
            self.connect(server, typed='good-key')
            server.key = 'rotated'
            _, shown = self.connect(server, typed='rotated')
            self.assertIn('remembered API key for this server was rejected', shown)
            self.assertEqual(keystore.load(server.url), 'rotated')

    def test_a_stale_key_does_not_linger_when_the_replacement_is_not_saved(self):
        with AuthServer() as server:
            self.connect(server, typed='good-key')
            server.key = 'rotated'
            self.connect(server, typed='rotated', answer='n')
        self.assertFalse(self.keyfile.exists())

    def test_keys_are_per_server_and_never_sent_to_another_one(self):
        with AuthServer('key-a') as a, AuthServer('key-b') as b:
            self.connect(a, typed='key-a')
            self.connect(b, typed='key-b')
            self.assertEqual({keystore.load(a.url), keystore.load(b.url)}, {'key-a', 'key-b'})
            self.assertNotIn('Bearer key-b', [auth for _, auth in a.calls])
            self.assertNotIn('Bearer key-a', [auth for _, auth in b.calls])

    def test_a_key_from_a_flag_or_the_environment_is_used_but_never_offered_or_saved(self):
        with AuthServer() as server:
            self.connect(server, key='good-key', typed=None, answer=None)  # no prompt of any kind
            with self.assertRaises(runner.ApiError):
                self.connect(server, key='wrong', typed=None)  # rejected: an error, not a re-ask
        self.assertFalse(self.keyfile.exists())

    def test_without_a_terminal_a_missing_key_is_an_error_not_a_prompt(self):
        with AuthServer() as server, self.assertRaises(runner.ApiError):
            self.connect(server, typed=None, tty=False)
        self.assertFalse(self.keyfile.exists())


class ForgetKeyFlagTests(ConfigDirCase):
    def run_main(self, *argv):
        with unittest.mock.patch.object(sys, 'argv', ['run_models.py', *argv]), \
                contextlib.redirect_stdout(io.StringIO()) as shown:
            return runner.main(), shown.getvalue()

    def test_forget_one_server_or_everything(self):
        keystore.save('http://a:1', 'ka')
        keystore.save('http://b:2', 'kb')
        code, shown = self.run_main('--url', 'http://a:1/v1', '--forget-key')  # /v1 is normalised away
        self.assertEqual(code, 0)
        self.assertIn('Forgot 1 remembered key.', shown)
        self.assertEqual((keystore.load('http://a:1'), keystore.load('http://b:2')), ('', 'kb'))
        _, shown = self.run_main('--forget-key')
        self.assertIn('Forgot 1 remembered key.', shown)
        _, shown = self.run_main('--forget-key')
        self.assertIn('Forgot 0 remembered keys.', shown)


if __name__ == '__main__':
    unittest.main()
