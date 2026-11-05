"""Post fixed-format results; submitted text never becomes shell code or Markdown."""
import json
import os
import re
import urllib.request
from pathlib import Path


def comment(result, artifact_url):
    lines = ['### Deterministic model test · v'+result['version'], '']
    if result['status']=='valid':
        lines += [f'**{result["points"]}/100** · {result["answered"]}/50 questions answered.', '',
                  '| Category | Points |', '|---|---:|']
        lines += [f'| {name} | {c["points"]}/{c["maximum"]} |' for name,c in result['categories'].items()]
        lines += ['', 'Missing answers earn zero toward the full test. Each submitted field is checked exactly.']
    else:
        # Errors contain fixed engine messages, never raw model answers.
        lines += ['**Invalid submission — no score assigned.**', '', result['error']]
    lines += ['', f'[Download HTML report, graphic, CSV and JSON]({artifact_url})', '',
              'Open `report.html` after downloading. Artifacts expire after 7 days; save a copy.', '',
              f'Suite SHA-256: `{result["suite_sha256"]}`',
              f'Submission SHA-256: `{result["submission_sha256"]}`']
    return '\n'.join(lines)


def main():
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    issue=event['issue']
    repository=os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
        raise ValueError('Invalid repository.')
    if type(issue['number']) is not int or issue['number'] <= 0:
        raise ValueError('Invalid issue number.')
    artifact_url=os.environ['REPORT_ARTIFACT_URL']
    if not artifact_url.startswith(f'https://github.com/{repository}/actions/runs/'):
        raise ValueError('Unexpected artifact URL.')
    result=json.loads(Path('report/results.json').read_text())
    request=urllib.request.Request(
        f'https://api.github.com/repos/{repository}/issues/{issue["number"]}/comments',
        data=json.dumps({'body':comment(result,artifact_url)}).encode(),
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
                 'Accept':'application/vnd.github+json','Content-Type':'application/json',
                 'User-Agent':'deterministic-model-test'},method='POST')
    with urllib.request.urlopen(request,timeout=20) as response:
        print('Report comment HTTP:',response.status)


if __name__=='__main__':
    main()
