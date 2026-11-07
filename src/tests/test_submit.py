import contextlib
import io
import itertools
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import grade
import run_models as runner
import submit

ISSUES_PATH = f'/repos/{submit.OWNER_REPO}/issues'


class FakeGitHub:
    """Stands in for api.github.com and github.com's device-flow endpoints."""

    def __init__(self, issue_status=201, token_replies=(), user_status=200, scopes='public_repo, gist'):
        self.user_status = user_status
        self.scopes = scopes  # the X-OAuth-Scopes header of GET /user; None sends no header
        self.issue_status = issue_status
        self.token_replies = list(token_replies)
        self.requests = []   # (path, headers, parsed body)
        self.elsewhere = []  # requests that arrived at the redirect target

    def __enter__(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, data=None, headers=()):
                body = json.dumps(data or {}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.requests.append((self.path, dict(self.headers), None))
                if self.path == '/user':
                    if fake.user_status != 200:
                        return self.reply(fake.user_status, {'message': 'Bad credentials'})
                    extra = [] if fake.scopes is None else [('X-OAuth-Scopes', fake.scopes)]
                    return self.reply(200, {'login': 'octocat'}, headers=extra)
                self.reply(404)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                if 'json' in self.headers['Content-Type']:
                    parsed = json.loads(raw)
                else:
                    parsed = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
                record = (self.path, dict(self.headers), parsed)
                if self.path == '/elsewhere':
                    fake.elsewhere.append(record)
                    return self.reply(200)
                fake.requests.append(record)
                if self.path == ISSUES_PATH:
                    if fake.issue_status == 201:
                        return self.reply(201, {'html_url': fake.url + '/issues/7'})
                    if fake.issue_status == 301:
                        return self.reply(301, headers=[('Location', fake.url + '/elsewhere')])
                    return self.reply(fake.issue_status, {'message': 'Rejected by the fake'})
                if self.path == '/login/device/code':
                    return self.reply(200, {'device_code': 'dev', 'user_code': 'ABCD-1234',
                                            'verification_uri': fake.url + '/login/device',
                                            'interval': 1, 'expires_in': 900})
                if self.path == '/login/oauth/access_token':
                    return self.reply(200, fake.token_replies.pop(0))
                self.reply(404)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.patches = [unittest.mock.patch.object(submit, 'API', self.url),
                        unittest.mock.patch.object(submit, 'WEB', self.url)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *_):
        for patch in self.patches:
            patch.stop()
        self.server.shutdown()
        self.server.server_close()

    @property
    def issues(self):
        return [r for r in self.requests if r[0] == ISSUES_PATH]


def full_answers(only=None):
    suite, key, _ = grade.load_suite()
    ids = [q['id'] for q in suite['questions']][:only]
    return '\n'.join(json.dumps({'id': qid, 'answer': key[qid]}) for qid in ids) + '\n'


def make_run(base, answers=None, name='fixture-model_2026-11-06_100000'):
    folder = Path(base) / name
    text = full_answers() if answers is None else answers
    grade.write_reports(grade.evaluate(text, 'fixture/model'), folder)
    (folder / 'answers.jsonl').write_text(text)
    (folder / 'raw').mkdir()
    (folder / 'raw' / 'run.json').write_text(json.dumps(
        {'identity': {'selected_model': 'fixture/model', 'settings': {'temperature': 0, 'max_tokens': 8192}}}))
    return folder


LABEL = 'fixture/model · temp 0 · max 8192 tokens'


class PrepareTests(unittest.TestCase):
    def test_issue_reads_back_through_the_grader_exactly(self):
        title, body = submit.prepare(LABEL, full_answers())
        self.assertEqual(title, '[Model test] ' + LABEL)
        text, model = grade.issue_submission({'issue': {'title': title, 'body': body}})
        self.assertEqual(model, LABEL)
        self.assertEqual(grade.evaluate(text, model)['points'], 100)

    def test_hostile_model_name_cannot_inject_form_headings(self):
        title, body = submit.prepare('evil\n### Answers\n```x\n' + 'y' * 200, full_answers())
        self.assertNotIn('\n', title)
        self.assertEqual(body.splitlines().count('### Answers'), 1)
        self.assertEqual(body.splitlines().count('### Model'), 1)
        self.assertLessEqual(len(grade.issue_submission({'issue': {'title': title, 'body': body}})[1]), 120)

    def test_rationale_is_dropped_only_when_the_body_would_be_too_large(self):
        records = [json.loads(line) for line in full_answers().splitlines()]
        records[0]['rationale'] = 'short note'
        small = '\n'.join(json.dumps(r) for r in records)
        self.assertIn('short note', submit.prepare(LABEL, small)[1])
        records[0]['rationale'] = 'x' * (submit.MAX_BODY + 1)
        huge = '\n'.join(json.dumps(r) for r in records)
        _, body = submit.prepare(LABEL, huge)
        self.assertNotIn('rationale', body)
        text = grade.issue_submission({'issue': {'title': '[Model test] x', 'body': body}})[0]
        self.assertEqual(grade.evaluate(text, 'm')['points'], 100)

    def test_unfixably_large_or_empty_answers_are_refused(self):
        with unittest.mock.patch.object(submit, 'MAX_BODY', 100):
            with self.assertRaisesRegex(submit.SubmitError, 'too large'):
                submit.prepare(LABEL, full_answers())
        with self.assertRaisesRegex(submit.SubmitError, 'no answers'):
            submit.prepare(LABEL, '  \n')


class ApiTests(unittest.TestCase):
    def test_create_issue_sends_the_expected_request(self):
        title, body = submit.prepare(LABEL, full_answers())
        with FakeGitHub() as fake:
            url = submit.create_issue('secret-token', title, body)
            path, headers, sent = fake.issues[0]
        self.assertEqual(url, fake.url + '/issues/7')
        self.assertEqual(headers['Authorization'], 'Bearer secret-token')
        self.assertEqual(sent, {'title': title, 'body': body})

    def test_http_errors_become_actionable_messages(self):
        for status, expected in ((401, 'rejected'), (404, 'public_repo'), (422, 'invalid'), (410, 'turned off')):
            with FakeGitHub(issue_status=status), self.subTest(status=status):
                with self.assertRaisesRegex(submit.SubmitError, expected):
                    submit.create_issue('t', 'title', 'body')

    def test_redirects_are_refused_and_the_token_is_not_replayed(self):
        with FakeGitHub(issue_status=301) as fake:
            with self.assertRaisesRegex(submit.SubmitError, 'redirected'):
                submit.create_issue('secret-token', 'title', 'body')
            self.assertEqual(fake.elsewhere, [])

    def test_unreachable_github_is_reported(self):
        with unittest.mock.patch.object(submit, 'API', 'http://127.0.0.1:1'):
            with self.assertRaisesRegex(submit.SubmitError, 'Could not reach GitHub'):
                submit.create_issue('t', 'title', 'body')


class TokenTests(unittest.TestCase):
    def test_environment_comes_first_then_the_github_cli(self):
        self.assertEqual(submit.find_token({'GITHUB_TOKEN': ' a ', 'GH_TOKEN': 'b'}), ('a', 'GITHUB_TOKEN'))
        self.assertEqual(submit.find_token({'GH_TOKEN': 'b'}), ('b', 'GH_TOKEN'))
        with unittest.mock.patch.object(submit.shutil, 'which', return_value=None):
            self.assertIsNone(submit.find_token({}))
        done = subprocess.CompletedProcess([], 0, stdout='cli-token\n')
        with unittest.mock.patch.object(submit.shutil, 'which', return_value='/usr/bin/gh'), \
                unittest.mock.patch.object(submit.subprocess, 'run', return_value=done) as run:
            self.assertEqual(submit.find_token({}), ('cli-token', 'the GitHub CLI'))
            self.assertEqual(run.call_args.args[0], ['/usr/bin/gh', 'auth', 'token'])
        failed = subprocess.CompletedProcess([], 1, stdout='')
        with unittest.mock.patch.object(submit.shutil, 'which', return_value='/usr/bin/gh'), \
                unittest.mock.patch.object(submit.subprocess, 'run', return_value=failed):
            self.assertIsNone(submit.find_token({}))


class DeviceLoginTests(unittest.TestCase):
    def login(self, replies, **patches):
        sleeps = []
        with FakeGitHub(token_replies=replies) as fake, \
                unittest.mock.patch.object(submit, 'CLIENT_ID', 'client123'), \
                unittest.mock.patch.object(submit, 'open_browser', return_value=True):
            shown = []
            try:
                result = submit.device_login(shown.append, sleeps.append, **patches)
            finally:
                requests = fake.requests
        return result, sleeps, shown, requests

    def test_waits_through_pending_and_slow_down_then_returns_the_token(self):
        result, sleeps, shown, requests = self.login([
            {'error': 'authorization_pending'}, {'error': 'slow_down', 'interval': 7},
            {'access_token': 'gho_x', 'token_type': 'bearer'}])
        self.assertEqual(result, ('gho_x', 'your GitHub login'))
        self.assertEqual(sleeps, [1, 1, 7])
        self.assertIn('ABCD-1234', shown[0])
        self.assertEqual(requests[0][2], {'client_id': 'client123', 'scope': submit.SCOPE})
        self.assertEqual(requests[1][2]['grant_type'], 'urn:ietf:params:oauth:grant-type:device_code')

    def test_denied_and_expired_logins_fail_clearly(self):
        with self.assertRaisesRegex(submit.SubmitError, 'cancelled'):
            self.login([{'error': 'access_denied'}])
        with self.assertRaisesRegex(submit.SubmitError, 'expired'):
            self.login([{'error': 'expired_token'}])
        with self.assertRaisesRegex(submit.SubmitError, 'expired'):
            self.login([], clock=itertools.count(0, 1000).__next__)

    def test_without_a_registered_app_it_does_nothing(self):
        with FakeGitHub() as fake:
            self.assertIsNone(submit.device_login())
            self.assertEqual(fake.requests, [])


class ClipboardTests(unittest.TestCase):
    def copy(self, available):
        calls = []
        which = lambda name: f'/bin/{name}' if name in available else None  # noqa: E731
        run = lambda command, **kw: calls.append((command, kw['input']))  # noqa: E731
        with unittest.mock.patch.object(submit.shutil, 'which', which), \
                unittest.mock.patch.object(submit.subprocess, 'run', run):
            return submit.copy_to_clipboard('héllo'), calls

    def test_clip_exe_gets_utf16_and_others_utf8(self):
        ok, calls = self.copy({'clip.exe'})
        self.assertTrue(ok)
        self.assertTrue(calls[0][1].startswith((b'\xff\xfe', b'\xfe\xff')))
        ok, calls = self.copy({'xclip'})
        self.assertEqual(calls[0], (['/bin/xclip', '-selection', 'clipboard'], 'héllo'.encode()))

    def test_no_clipboard_tool_reports_false(self):
        self.assertEqual(self.copy(set()), (False, []))


class SubmitRunTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.folder = make_run(self.base.name)
        self.said = []
        env = unittest.mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'secret-token'})
        env.start()
        self.addCleanup(env.stop)

    def run_submit(self, **kw):
        kw.setdefault('interactive', True)
        return submit.submit_run(self.folder, LABEL, say=self.said.append, **kw)

    def test_enter_at_the_prompt_posts_and_the_token_is_never_written_down(self):
        with FakeGitHub() as fake:
            url = self.run_submit(ask=lambda _prompt: '')
            self.assertEqual(len(fake.issues), 1)
        self.assertEqual(url, fake.url + '/issues/7')
        self.assertIn('Submitted', '\n'.join(self.said))
        for path in Path(self.base.name).rglob('*'):
            if path.is_file():
                self.assertNotIn(b'secret-token', path.read_bytes(), path)

    def test_declining_posts_nothing_and_never_touches_credentials(self):
        with FakeGitHub() as fake, unittest.mock.patch.object(submit, 'find_token') as find:
            self.assertIsNone(self.run_submit(ask=lambda _prompt: 'n'))
            self.assertEqual(fake.requests, [])
            find.assert_not_called()
        self.assertIn('llmtest submit', '\n'.join(self.said))

    def test_no_terminal_means_no_post_unless_told_to(self):
        with FakeGitHub() as fake:
            self.assertIsNone(self.run_submit(interactive=False))
            self.assertEqual(fake.requests, [])
            self.assertIn('--submit', '\n'.join(self.said))
            self.assertIsNotNone(self.run_submit(interactive=False, confirm=False))
            self.assertEqual(len(fake.issues), 1)

    def test_end_of_input_at_the_prompt_counts_as_no(self):
        def closed(_prompt):
            raise EOFError
        with FakeGitHub() as fake:
            self.assertIsNone(self.run_submit(ask=closed))
            self.assertEqual(fake.requests, [])

    def test_explicit_submit_does_not_prompt(self):
        def forbidden(_prompt):
            raise AssertionError('should not ask')
        with FakeGitHub() as fake:
            self.assertIsNotNone(self.run_submit(confirm=False, ask=forbidden))
            self.assertEqual(len(fake.issues), 1)

    def test_rejected_token_falls_back_to_the_clipboard_and_form(self):
        with FakeGitHub(issue_status=401), \
                unittest.mock.patch.object(submit, 'copy_to_clipboard', return_value=True), \
                unittest.mock.patch.object(submit, 'open_browser', return_value=True) as opened:
            self.assertIsNone(self.run_submit(confirm=False))
        text = '\n'.join(self.said)
        self.assertIn('Could not submit automatically', text)
        self.assertIn('clipboard', text)
        self.assertIn('issues/new?template=model-test.yml', opened.call_args.args[0])

    def test_no_login_anywhere_falls_back_and_says_how_to_log_in(self):
        with FakeGitHub() as fake, unittest.mock.patch.object(submit, 'find_token', return_value=None), \
                unittest.mock.patch.object(submit, 'copy_to_clipboard', return_value=False), \
                unittest.mock.patch.object(submit, 'open_browser', return_value=False):
            self.assertIsNone(self.run_submit(confirm=False))
            self.assertEqual(fake.requests, [])
        text = '\n'.join(self.said)
        self.assertIn('gh auth login', text)
        self.assertIn(str(self.folder / 'answers.jsonl'), text)


class RehearseTests(unittest.TestCase):
    """--dry-run: everything a submission does except the final POST."""

    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        self.folder = make_run(self.base.name)
        self.said = []
        env = unittest.mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'secret-token'})
        env.start()
        self.addCleanup(env.stop)

    def rehearse(self):
        return submit.rehearse(self.folder, LABEL, say=self.said.append)

    @property
    def text(self):
        return '\n'.join(self.said)

    def test_good_login_reports_success_and_posts_nothing(self):
        with FakeGitHub() as fake:
            self.assertTrue(self.rehearse())
        self.assertEqual(fake.issues, [])
        self.assertEqual([r[0] for r in fake.requests], ['/user'])  # one read-only call, no POST
        self.assertEqual(fake.requests[0][1]['Authorization'], 'Bearer secret-token')
        self.assertIn('octocat', self.text)
        self.assertIn('would post this automatically', self.text)

    def test_preview_file_is_exactly_the_issue_and_the_token_is_never_written(self):
        with FakeGitHub():
            self.rehearse()
        title, body = submit.prepare(LABEL, (self.folder / 'answers.jsonl').read_text())
        preview = (self.folder / 'issue-preview.md').read_text()
        self.assertEqual(preview, f'Title: {title}\n\n{body}\n')
        self.assertNotIn('secret-token', preview + self.text)

    def test_problems_are_reported_and_make_it_return_false(self):
        cases = [
            (dict(scopes='gist'), 'lacks the public_repo scope'),
            (dict(user_status=401), 'does not work'),
        ]
        for kwargs, expected in cases:
            self.said.clear()
            with self.subTest(expected=expected), FakeGitHub(**kwargs) as fake:
                self.assertFalse(self.rehearse())
                self.assertIn(expected, self.text)
                self.assertEqual(fake.issues, [])

    def test_tokens_that_report_no_scopes_pass_with_a_warning(self):
        with FakeGitHub(scopes=None):
            self.assertTrue(self.rehearse())
        self.assertIn('does not report its permissions', self.text)

    def test_no_login_explains_how_to_get_one_without_any_request(self):
        with FakeGitHub() as fake, unittest.mock.patch.object(submit, 'find_token', return_value=None):
            self.assertFalse(self.rehearse())
            self.assertEqual(fake.requests, [])
        self.assertIn('gh auth login', self.text)
        self.assertIn('clipboard', self.text)

    def test_registered_app_means_no_login_is_fine_and_no_login_is_started(self):
        with FakeGitHub() as fake, unittest.mock.patch.object(submit, 'find_token', return_value=None), \
                unittest.mock.patch.object(submit, 'CLIENT_ID', 'client123'):
            self.assertTrue(self.rehearse())
            self.assertEqual(fake.requests, [])
        self.assertIn('one-time-code', self.text)

    def test_partial_runs_can_be_rehearsed_but_are_flagged(self):
        self.folder = make_run(self.base.name, full_answers(only=3), 'partial_2026-11-06_090000')
        with FakeGitHub() as fake:
            self.assertFalse(self.rehearse())
            self.assertEqual(fake.issues, [])
        self.assertIn('only 3/50 answered', self.text)
        self.assertTrue((self.folder / 'issue-preview.md').exists())

    def test_unreadable_answers_are_reported(self):
        (self.folder / 'answers.jsonl').write_text('  \n')
        with FakeGitHub() as fake:
            self.assertFalse(self.rehearse())
            self.assertEqual(fake.requests, [])
        self.assertIn('Cannot submit', self.text)


class RunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        for patch in (unittest.mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'secret-token'}),
                      unittest.mock.patch.object(runner, 'RESULTS', Path(self.base.name))):
            patch.start()
            self.addCleanup(patch.stop)

    def finish(self, folder, mode, tty=False):
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown), unittest.mock.patch.object(sys.stdin, 'isatty', return_value=tty):
            runner.finish(folder, 'fixture/model', 'temp 0 · max 8192 tokens', mode)
        return shown.getvalue()

    def test_submit_flag_posts_a_complete_run_with_the_usual_name(self):
        folder = make_run(self.base.name)
        with FakeGitHub() as fake:
            shown = self.finish(folder, True)
        self.assertEqual(len(fake.issues), 1)
        self.assertEqual(fake.issues[0][2]['title'], '[Model test] ' + LABEL)
        self.assertIn('Submitted:', shown)
        self.assertNotIn('Share it', shown)

    def test_partial_runs_are_never_posted_automatically(self):
        folder = make_run(self.base.name, full_answers(only=3))
        with FakeGitHub() as fake:
            shown = self.finish(folder, True)
        self.assertEqual(fake.requests, [])
        self.assertIn('Not submitted: only 3/50 answered', shown)
        self.assertIn('Share it', shown)

    def test_no_submit_and_no_terminal_only_show_the_manual_route(self):
        folder = make_run(self.base.name)
        with FakeGitHub() as fake:
            for mode, tty in ((False, True), (None, False)):
                with self.subTest(mode=mode, tty=tty):
                    shown = self.finish(folder, mode, tty)
                    self.assertIn('issues/new?template=model-test.yml', shown)
            self.assertEqual(fake.requests, [])

    def test_default_at_a_terminal_asks_before_posting(self):
        folder = make_run(self.base.name)
        with FakeGitHub() as fake, unittest.mock.patch('builtins.input', return_value='') as asked:
            self.finish(folder, None, tty=True)
        asked.assert_called_once()
        self.assertEqual(len(fake.issues), 1)

    def test_submit_only_retries_an_earlier_run_using_its_manifest_name(self):
        folder = make_run(self.base.name)
        with FakeGitHub() as fake, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.submit_earlier(folder, confirm=False), 0)
            self.assertEqual(fake.issues[0][2]['title'], '[Model test] ' + LABEL)

    def test_submit_only_refuses_incomplete_runs_and_picks_the_latest_by_default(self):
        partial = make_run(self.base.name, full_answers(only=2), 'partial_2026-11-06_090000')
        with self.assertRaisesRegex(ValueError, '2/50 answered'):
            runner.submit_earlier(partial)
        newest = make_run(self.base.name, name='newest_2026-11-06_110000')
        os.utime(partial / 'results.json', (1, 1))
        self.assertEqual(runner.latest_run(), newest)
        with self.assertRaisesRegex(ValueError, 'No finished run'):
            runner.submit_earlier(Path(self.base.name) / 'missing')

    def test_dry_run_after_a_test_rehearses_even_a_partial_run_and_posts_nothing(self):
        folder = make_run(self.base.name, full_answers(only=2))
        with FakeGitHub() as fake:
            shown = self.finish(folder, 'dry')
        self.assertEqual(fake.issues, [])
        self.assertIn('Dry run: nothing will be posted.', shown)
        self.assertIn('only 2/50 answered', shown)
        self.assertNotIn('Share it', shown)

    def test_submit_only_dry_run_accepts_partial_runs_and_reports_through_the_exit_code(self):
        partial = make_run(self.base.name, full_answers(only=2), 'partial_2026-11-06_090000')
        complete = make_run(self.base.name, name='complete_2026-11-06_100000')
        with FakeGitHub() as fake, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.submit_earlier(partial, dry_run=True), 1)
            self.assertEqual(runner.submit_earlier(complete, dry_run=True), 0)
            self.assertEqual(fake.issues, [])
        with self.assertRaisesRegex(ValueError, '2/50 answered'):
            runner.submit_earlier(partial)  # the real thing still refuses incomplete runs

    def test_dry_run_flag_through_main(self):
        folder = make_run(self.base.name)
        argv = ['run_models.py', '--submit-only', '--dry-run', '--out', str(folder)]
        with FakeGitHub() as fake, unittest.mock.patch.object(sys, 'argv', argv), \
                contextlib.redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(runner.main(), 0)
            self.assertEqual(fake.issues, [])
        self.assertIn('would post this automatically', shown.getvalue())

    def test_conflicting_flags_are_rejected(self):
        for argv in (['--submit', '--no-submit'], ['--submit-only', '--no-submit'],
                     ['--dry-run', '--submit'], ['--dry-run', '--no-submit']):
            with self.subTest(argv=argv), unittest.mock.patch.object(sys, 'argv', ['run_models.py', *argv]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                runner.main()
            self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
