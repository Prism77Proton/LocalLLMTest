"""Submit a finished run to the public leaderboard.

Opens a "[Model test]" issue through the GitHub REST API, in exactly the format the
issue form produces, so the existing grading workflow handles it. A GitHub login is
needed because GitHub has no anonymous issue creation. The token is found in this
order: GITHUB_TOKEN / GH_TOKEN, the GitHub CLI (`gh auth login`), then a one-time-code
device login if the project has registered an app (CLIENT_ID below). It is only held in
memory, sent to GitHub over HTTPS and never written to disk. Without any of these the
answers are copied to the clipboard and the pre-filled issue form is opened instead.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import grade
import leaderboard

OWNER_REPO = leaderboard.REPOSITORY.removeprefix('https://github.com/')
API = 'https://api.github.com'
WEB = 'https://github.com'
# Public (not secret) client ID of a GitHub App or OAuth app with "Enable Device Flow"
# ticked. Empty until the project registers one; set it and `llmtest` can then log
# people in with a one-time code, with nothing for them to install or configure.
CLIENT_ID = ''
SCOPE = 'public_repo'
MAX_BODY = 60000  # GitHub rejects issue bodies over 65536 characters


class SubmitError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise SubmitError('GitHub redirected the request; the token was not sent anywhere else.')


# Environment proxies are honoured (people submit from all sorts of networks);
# redirects are refused so a token is never replayed to another host.
_OPENER = urllib.request.build_opener(_NoRedirect())


def _explain(error):
    try:
        message = json.loads(error.read(20000)).get('message', '')
    except (ValueError, AttributeError, OSError):
        message = ''
    finally:
        error.close()
    hint = {
        401: 'The token was rejected.',
        403: 'GitHub refused it: the token may lack the public_repo permission, or a rate limit was hit.',
        404: 'The token cannot write to the repository; it needs the public_repo permission.',
        410: 'Issues are turned off on the repository.',
        422: 'GitHub rejected the issue as invalid.',
    }.get(error.code, '')
    return ' '.join(part for part in (f'GitHub returned HTTP {error.code}.', hint, str(message)) if part)


def _call(url, data=None, *, token=None, form=False, timeout=30):
    """POST data (GET when there is none); returns (parsed JSON reply, response headers)."""
    headers = {'Accept': 'application/json' if form else 'application/vnd.github+json',
               'User-Agent': 'LocalLLMTest', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    request = urllib.request.Request(url, body, headers, method='GET' if data is None else 'POST')
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return json.loads(response.read(2_000_000) or b'{}'), response.headers
    except urllib.error.HTTPError as error:
        raise SubmitError(_explain(error)) from None
    except (urllib.error.URLError, OSError) as error:
        raise SubmitError(f'Could not reach GitHub: {getattr(error, "reason", error)}') from None
    except ValueError:
        raise SubmitError('GitHub sent a reply that is not JSON.') from None


def _post(url, data, **kwargs):
    return _call(url, data, **kwargs)[0]


def _without_rationale(answers):
    lines = []
    for line in answers.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            raise SubmitError('answers.jsonl is not valid JSON lines.') from None
        record.pop('rationale', None)  # preserved by the grader but never scored
        lines.append(json.dumps(record, ensure_ascii=False))
    return '\n'.join(lines)


def prepare(label, answers):
    """Return (title, body) for the issue; the body is the issue form's own format."""
    label = leaderboard.clean_name(label)
    answers = answers.strip()
    if not answers:
        raise SubmitError('There are no answers to submit.')
    if len(answers) > MAX_BODY:
        answers = _without_rationale(answers)
    if len(answers) > MAX_BODY:
        raise SubmitError('The answers are too large for one GitHub issue.')
    title = f'[Model test] {label}'
    body = f'### Model\n\n{label}\n\n### Answers\n\n```text\n{answers}\n```'
    # Prove the grading workflow will read back exactly what is about to be published.
    try:
        parsed = grade.issue_submission({'issue': {'title': title, 'body': body}})
    except grade.SubmissionError as error:
        raise SubmitError(f'The issue would not be accepted by the grader: {error}') from None
    if parsed != (answers, label):
        raise SubmitError('The issue text does not read back identically; not submitting.')
    return title, body


def find_token(environ=None):
    """(token, where it came from), or None."""
    environ = os.environ if environ is None else environ
    for name in ('GITHUB_TOKEN', 'GH_TOKEN'):
        value = environ.get(name, '').strip()
        if value:
            return value, name
    gh = shutil.which('gh')
    if gh:
        try:
            done = subprocess.run([gh, 'auth', 'token'], capture_output=True, text=True,
                                  timeout=15, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        token = done.stdout.strip()
        if done.returncode == 0 and token:
            return token, 'the GitHub CLI'
    return None


def open_browser(url):
    for opener in ('wslview', 'xdg-open', 'open'):
        path = shutil.which(opener)
        if path:
            subprocess.Popen([path, url], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


def copy_to_clipboard(text):
    for command in (['clip.exe'], ['pbcopy'], ['wl-copy'],
                    ['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
        path = shutil.which(command[0])
        if not path:
            continue
        # clip.exe reads the console code page unless the text is UTF-16 with a byte-order mark.
        data = text.encode('utf-16') if command[0] == 'clip.exe' else text.encode('utf-8')
        try:
            subprocess.run([path, *command[1:]], input=data, check=True, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def device_login(say=print, sleep=time.sleep, clock=time.monotonic):
    """One-time-code login. Returns (token, source), or None if no app is registered."""
    if not CLIENT_ID:
        return None
    start = _post(f'{WEB}/login/device/code', {'client_id': CLIENT_ID, 'scope': SCOPE}, form=True)
    try:
        device, code, page = start['device_code'], start['user_code'], start['verification_uri']
        interval, expires = int(start.get('interval', 5)), int(start.get('expires_in', 900))
    except (KeyError, TypeError, ValueError):
        raise SubmitError('GitHub sent an unexpected login reply.') from None
    say(f'Log in to GitHub: open {page} and enter the code {code}')
    open_browser(page)
    deadline = clock() + expires
    while clock() < deadline:
        sleep(interval)
        reply = _post(f'{WEB}/login/oauth/access_token',
                      {'client_id': CLIENT_ID, 'device_code': device,
                       'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'}, form=True)
        if reply.get('access_token'):
            return reply['access_token'], 'your GitHub login'
        error = reply.get('error')
        if error == 'authorization_pending':
            continue
        if error == 'slow_down':
            interval = int(reply.get('interval') or interval + 5)
            continue
        raise SubmitError({'expired_token': 'The login code expired.',
                           'access_denied': 'The login was cancelled.'}.get(error, f'GitHub login failed ({error}).'))
    raise SubmitError('The login code expired.')


def create_issue(token, title, body):
    reply = _post(f'{API}/repos/{OWNER_REPO}/issues', {'title': title, 'body': body}, token=token)
    url = reply.get('html_url')
    if not isinstance(url, str) or not url:
        raise SubmitError('GitHub accepted the issue but sent no link to it.')
    return url


def form_url(label):
    query = urllib.parse.urlencode({'template': 'model-test.yml',
                                    'title': '[Model test] ' + label, 'model': label})
    return f'{leaderboard.REPOSITORY}/issues/new?{query}'


def manual(folder, label, say=print):
    """No automatic route: copy the answers and open the pre-filled issue form."""
    answers = (folder / 'answers.jsonl').read_text(encoding='utf-8')
    url = form_url(label)
    copied = copy_to_clipboard(answers)
    opened = open_browser(url)
    say(f'Share it: {"the issue form is open" if opened else "open " + url}')
    if copied:
        say('  Your answers are on the clipboard: press Ctrl+V (or Cmd+V) in Answers, then submit.')
    else:
        say(f'  Paste the contents of {folder / "answers.jsonl"} into Answers, then submit.')


def submit_run(folder, label, *, confirm=True, interactive=None, say=print, ask=None):
    """Post a finished run's answers as a leaderboard issue and return the issue URL.

    confirm: ask first (the default). Posting is public, so without a terminal to ask on
    nothing is posted unless the caller passed confirm=False (--submit).
    Returns None when declined or when posting failed; the manual route is shown then."""
    folder = folder.resolve()
    interactive = sys.stdin.isatty() if interactive is None else interactive
    try:
        title, body = prepare(label, (folder / 'answers.jsonl').read_text(encoding='utf-8'))
    except (SubmitError, OSError) as error:
        say(f'Cannot submit: {error}')
        return None
    if confirm:
        if not interactive:
            say('Not submitted: no terminal to ask on. Add --submit to post without asking.')
            return None
        say(f'\nThis posts a PUBLIC issue on {OWNER_REPO} with the name "{label}" and all your '
            'answers. GitHub then grades it automatically.')
        try:
            reply = (ask or input)('Submit to the public leaderboard? [Y/n] ')
        except EOFError:
            reply = 'n'
        if reply.strip().lower() not in ('', 'y', 'yes'):
            say('Not submitted. To do it later: llmtest submit')
            return None
    try:
        found = find_token() or device_login(say)
        if not found:
            raise SubmitError('No GitHub login found. Run "gh auth login" (GitHub CLI) or set '
                              'GITHUB_TOKEN to a classic token with the public_repo scope.')
        token, source = found
        say(f'Posting with the login from {source} …')
        url = create_issue(token, title, body)
    except SubmitError as error:
        say(f'Could not submit automatically: {error}')
        manual(folder, label, say)
        return None
    say(f'Submitted: {url}\n  GitHub grades it within a minute and comments the score on that issue.')
    return url


def check_login(token):
    """Ask GitHub who a token belongs to (a read-only call). Returns (login, scopes);
    scopes is None for tokens that do not report any (fine-grained and app tokens)."""
    data, headers = _call(f'{API}/user', token=token)
    login = data.get('login')
    if not isinstance(login, str) or not login:
        raise SubmitError('GitHub did not say who the token belongs to.')
    reported = headers.get('X-OAuth-Scopes')
    scopes = None if reported is None else {s.strip() for s in reported.split(',') if s.strip()}
    return login, scopes


def rehearse(folder, label, *, say=print):
    """Do everything a submission does except the final POST: build and validate the exact
    issue, save it to issue-preview.md, and check the GitHub login. Nothing is posted.
    Returns True if a real submission would post automatically."""
    folder = folder.resolve()
    say('Dry run: nothing will be posted.')
    try:
        answers = (folder / 'answers.jsonl').read_text(encoding='utf-8')
        title, body = prepare(label, answers)
    except (SubmitError, OSError) as error:
        say(f'  Cannot submit: {error}')
        return False
    total = len(grade.load_suite()[0]['questions'])
    records = answers.strip().splitlines()
    preview = folder / 'issue-preview.md'
    preview.write_text(f'Title: {title}\n\n{body}\n', encoding='utf-8')
    say(f'  Repository:  {OWNER_REPO} (a public issue)')
    say(f'  Title:       {title}')
    say(f'  Answers:     {len(records)}/{total}, {len(body):,} characters; first: {records[0][:100]}')
    say(f'  Full issue:  {preview}  (first line the title, then the body exactly as it would be posted)')
    problems = []
    if len(records) != total:
        problems.append(f'only {len(records)}/{total} answered; a real submission waits for a complete run')
    found = find_token()
    if found:
        token, source = found
        try:
            login, scopes = check_login(token)
        except SubmitError as error:
            problems.append(f'the login from {source} does not work: {error}')
        else:
            if scopes is None:
                say(f'  Login:       {login} via {source}; this token type does not report its '
                    'permissions, so the real post could still be refused')
            elif scopes & {'public_repo', 'repo'}:
                say(f'  Login:       {login} via {source}; scopes: {", ".join(sorted(scopes))}')
            else:
                shown = ', '.join(sorted(scopes)) or 'none'
                problems.append(f'the login ({login}, via {source}) lacks the public_repo scope (has: {shown})')
    elif CLIENT_ID:
        say('  Login:       none found; a real submission would open a one-time-code login in your browser')
    else:
        problems.append('no GitHub login found (run "gh auth login" or set GITHUB_TOKEN to a classic token '
                        'with the public_repo scope); a real submission would fall back to the clipboard '
                        'and the pre-filled issue form')
    if problems:
        say('Dry run finished. A real submission would not post automatically:')
        for problem in problems:
            say(f'  - {problem}')
        return False
    say('Dry run finished. A real submission would post this automatically.')
    return True
