#!/usr/bin/env python3
"""Exact, typed grading and offline reports. Never execute submitted answers."""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIMIT = 1_000_000


class SubmissionError(ValueError):
    pass


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise SubmissionError('Duplicate JSON object key.')
        obj[key] = value
    return obj


def reject_number(value):
    raise SubmissionError('Use integers or canonical rational strings; decimals, exponents and nonfinite numbers are forbidden.')


def loads(text):
    try:
        return json.loads(text, object_pairs_hook=unique_object,
                          parse_float=reject_number, parse_constant=reject_number)
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, SubmissionError):
            raise
        raise SubmissionError('Invalid or excessively nested JSON.') from None


def read_bounded(path):
    with Path(path).open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise SubmissionError('Submission exceeds 1 MB.')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        raise SubmissionError('Submission must be UTF-8.') from None


def unwrap(text):
    text = text.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines[0] not in ('```', '```text', '```json', '```jsonl') or lines[-1] != '```':
            raise SubmissionError('Use at most one complete outer text/json/jsonl fence.')
        text = '\n'.join(lines[1:-1]).strip()
    return text


def issue_submission(event):
    issue = event.get('issue', {})
    if not issue.get('title', '').startswith('[Model test]') or 'pull_request' in issue:
        raise SubmissionError('Not a model-test issue.')
    body = issue.get('body') or ''
    # The form always emits these exact two headings and a fenced Answers block.
    match = re.fullmatch(r'### Model\s*\n(.*?)\n### Answers\s*\n(.*)', body, re.S)
    if not match:
        raise SubmissionError('Use the Model test issue form, retaining its Model and Answers headings.')
    model = match[1].strip()
    if not model or len(model) > 120 or '\n' in model:
        raise SubmissionError('Model name must be one nonempty line of at most 120 characters.')
    return unwrap(match[2]), model


def typed_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(typed_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def load_suite():
    raw_suite = (ROOT/'suite.json').read_bytes()
    raw_key = (ROOT/'answer-key.json').read_bytes()
    suite, key = loads(raw_suite.decode()), loads(raw_key.decode())
    ids = [q['id'] for q in suite['questions']]
    assert ids == [f'Q{n:02}' for n in range(1, 51)]
    assert set(key) == set(ids)
    assert all(len(q['fields']) == 2 and q['fields'].keys() == key[q['id']].keys() for q in suite['questions'])
    digest = hashlib.sha256(raw_suite + b'\x00' + raw_key).hexdigest()
    return suite, key, digest


def parse_answers(text, suite):
    if len(text.encode()) > LIMIT:
        raise SubmissionError('Submission exceeds 1 MB.')
    text = unwrap(text)
    if not text:
        raise SubmissionError('No answer records supplied.')
    known = {q['id']: q for q in suite['questions']}
    records = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        obj = loads(line)
        if type(obj) is not dict or set(obj) not in ({'id','answer'}, {'id','answer','rationale'}):
            raise SubmissionError(f'Line {line_number}: expected id, answer and optional rationale only.')
        qid = obj['id']
        if type(qid) is not str or qid not in known:
            raise SubmissionError(f'Line {line_number}: unknown question ID.')
        if qid in records:
            raise SubmissionError(f'Line {line_number}: duplicate question ID {qid}.')
        if 'rationale' in obj and type(obj['rationale']) is not str:
            raise SubmissionError(f'{qid}: rationale must be a string.')
        answer = obj['answer']
        if type(answer) is not dict or answer.keys() != known[qid]['fields'].keys():
            raise SubmissionError(f'{qid}: answer must have exactly its two specified fields.')
        records[qid] = obj
    if not records:
        raise SubmissionError('No answer records supplied.')
    return records


def evaluate(text, model='Unspecified'):
    suite, key, digest = load_suite()
    result = dict(suite=suite['name'], version=suite['version'], suite_sha256=digest,
                  submission_sha256=hashlib.sha256(text.encode()).hexdigest(), model=model,
                  status='valid', points=0, maximum=100, answered=0, questions=[], categories={})
    try:
        answers = parse_answers(text, suite)
    except SubmissionError as error:
        result.update(status='invalid', points=None, error=str(error))
        return result
    for q in suite['questions']:
        qid = q['id']
        record = answers.get(qid)
        checks = []
        for field in q['fields']:
            received = record['answer'][field] if record else None
            passed = bool(record) and typed_equal(received, key[qid][field])
            checks.append(dict(field=field, passed=passed, expected=key[qid][field],
                               received=received, missing=record is None))
        points = sum(check['passed'] for check in checks)
        status = 'missing' if record is None else ('pass' if points == 2 else 'partial' if points == 1 else 'fail')
        result['questions'].append(dict(id=qid, title=q['title'], category=q['category'],
                                        points=points, status=status, checks=checks,
                                        rationale=record.get('rationale', '') if record else ''))
        category = result['categories'].setdefault(q['category'], dict(points=0, maximum=0, answered=0))
        category['points'] += points
        category['maximum'] += 2
        category['answered'] += record is not None
        result['points'] += points
        result['answered'] += record is not None
    result['attempted_maximum'] = result['answered'] * 2
    result['complete'] = result['answered'] == 50
    return result


def chart(result):
    colors = dict(pass_='#34d399', partial='#fbbf24', fail='#fb7185', missing='#475569')
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 390" role="img" aria-labelledby="title desc">',
             '<title id="title">Deterministic model test results</title>',
             '<desc id="desc">Per-question points and category totals. Green two, amber one, red zero, gray missing.</desc>',
             '<rect width="900" height="390" rx="20" fill="#111827"/>']
    if result['status'] != 'valid':
        parts.append('<text x="32" y="64" fill="#fb7185" font-size="28">Invalid submission — no score</text></svg>')
        return ''.join(parts)
    parts.append(f'<text x="32" y="48" fill="white" font-size="24">{result["points"]}/100 · {result["answered"]}/50 answered</text>')
    for i,q in enumerate(result['questions']):
        x, y = 32+(i%10)*84, 76+(i//10)*40
        color = colors['pass_' if q['status']=='pass' else q['status']]
        parts.append(f'<g><title>{q["id"]}: {q["status"]}, {q["points"]}/2</title><rect x="{x}" y="{y}" width="74" height="30" rx="6" fill="{color}"/><text x="{x+37}" y="{y+20}" text-anchor="middle" fill="#0f172a" font-size="14">{q["id"]} · {q["points"]}</text></g>')
    for i,(name,c) in enumerate(result['categories'].items()):
        y=302+i*26
        parts.append(f'<text x="32" y="{y}" fill="#e2e8f0" font-size="14">{html.escape(name)} {c["points"]}/{c["maximum"]}</text><rect x="240" y="{y-13}" width="600" height="14" rx="5" fill="#334155"/><rect x="240" y="{y-13}" width="{600*c["points"]/c["maximum"]}" height="14" rx="5" fill="#38bdf8"/>')
    parts.append('</svg>')
    return ''.join(parts)


def markdown(result):
    if result['status'] != 'valid':
        return '# Invalid submission\n\n'+result['error']+'\n\nNo numeric score was assigned. Correct the format and resubmit.\n'
    lines = ['# Deterministic Model Test report', '',
             f'**{result["points"]}/100** · {result["answered"]}/50 answered · v{result["version"]}', '',
             f'Attempted fields: {result["points"]}/{result["attempted_maximum"]}. Missing questions earn zero toward the full test.', '',
             '| Category | Points | Answered |', '|---|---:|---:|']
    lines += [f'| {name} | {c["points"]}/{c["maximum"]} | {c["answered"]} |' for name,c in result['categories'].items()]
    lines += ['', '| Question | Points | Status |', '|---|---:|---|']
    lines += [f'| {q["id"]} | {q["points"]}/2 | {q["status"]} |' for q in result['questions']]
    lines += ['', 'Exact field matching only. No AI judge, code execution, or prose grading.', '',
              f'Suite SHA-256: `{result["suite_sha256"]}`', f'Submission SHA-256: `{result["submission_sha256"]}`', '']
    return '\n'.join(lines)


def render_html(result):
    esc = html.escape
    cards = []
    for q in result['questions']:
        checks = []
        for c in q['checks']:
            received = '[missing]' if c['missing'] else json.dumps(c['received'],ensure_ascii=False)
            checks.append(f'<tr><td>{esc(c["field"])}</td><td>{"PASS" if c["passed"] else "MISSING" if c["missing"] else "FAIL"}</td><td><code>{esc(json.dumps(c["expected"],ensure_ascii=False))}</code></td><td><code>{esc(received)}</code></td></tr>')
        rationale = '<h4>Unscored rationale</h4><pre>'+esc(q['rationale'])+'</pre>' if q['rationale'] else ''
        cards.append(f'<details class="{q["status"]}"><summary>{q["id"]} · {esc(q["title"])} <b>{q["points"]}/2 · {q["status"]}</b></summary><div class="scroll"><table><thead><tr><th>Field</th><th>Check</th><th>Expected</th><th>Received</th></tr></thead><tbody>{"".join(checks)}</tbody></table></div>{rationale}</details>')
    error = '<p class="error">'+esc(result['error'])+'</p><p>No score assigned. Correct the format and resubmit.</p>' if result['status']=='invalid' else ''
    score = 'No score' if result['points'] is None else f'{result["points"]}/100'
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>Model test report</title><style>
:root{{color-scheme:dark}}body{{font:16px/1.6 system-ui,sans-serif;background:#080e1a;color:#e2e8f0;max-width:1080px;margin:auto;padding:32px 20px}}h1{{font-size:clamp(28px,5vw,48px);margin:10px 0}}header p{{color:#94a3b8}}.eyebrow{{color:#38bdf8;letter-spacing:.12em;text-transform:uppercase}}svg{{width:100%;height:auto;margin:20px 0}}details{{background:#111827;border:1px solid #334155;border-left:4px solid #475569;border-radius:10px;margin:12px 0;padding:14px}}.pass{{border-left-color:#34d399}}.partial{{border-left-color:#fbbf24}}.fail,.error{{border-left-color:#fb7185;color:#fda4af}}summary{{cursor:pointer}}summary b{{float:right}}table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #334155;vertical-align:top}}code,pre{{overflow-wrap:anywhere;white-space:pre-wrap}}.scroll{{overflow:auto}}footer{{font-size:12px;overflow-wrap:anywhere;color:#94a3b8;margin-top:32px}}@media(max-width:600px){{summary b{{float:none;display:block}}}}@media print{{body{{background:white;color:black}}details{{break-inside:avoid}}}}
</style><header><span class="eyebrow">Exact outputs · v{esc(result['version'])}</span><h1>{score}</h1><p>{esc(result['model'])}</p><p>{result['answered']}/50 answered. Each of 100 typed field checks earns one point. Green=2, amber=1, red=0, gray=missing.</p></header>
{chart(result)}{error}<p>This revised test measures fixed outputs and certificates. It does not assess proof prose or unrestricted code correctness. Scores cannot be compared with v1.</p>
{''.join(cards)}<footer>Suite SHA-256: {result['suite_sha256']}<br>Submission SHA-256: {result['submission_sha256']}<br>Self-contained report. No external resources, AI calls, or submitted code execution.</footer></html>'''


def write_reports(result, destination):
    destination = Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    (destination/'summary.md').write_text(markdown(result))
    (destination/'report.html').write_text(render_html(result))
    (destination/'chart.svg').write_text(chart(result))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['question','category','points','maximum','status','field','passed','expected','received'])
    for q in result['questions']:
        for c in q['checks']:
            writer.writerow([q['id'],q['category'],q['points'],2,q['status'],c['field'],c['passed'],json.dumps(c['expected']),'' if c['missing'] else json.dumps(c['received'])])
    (destination/'checks.csv').write_text(buffer.getvalue())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--answers',type=Path)
    group.add_argument('--event',type=Path,help='GitHub issues opened/edited event JSON')
    parser.add_argument('--model',default='Unspecified')
    parser.add_argument('--out',type=Path,default=ROOT/'report')
    args=parser.parse_args()
    text=''; model=args.model
    try:
        if args.event:
            text,model=issue_submission(loads(read_bounded(args.event)))
        else:
            text=read_bounded(args.answers)
        result=evaluate(text,model)
    except SubmissionError as error:
        result=evaluate('',model)
        result['error']=str(error)
    write_reports(result,args.out)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as stream:stream.write(markdown(result))
    print(f"Report: {args.out/'report.html'}; status: {result['status']}; points: {result['points']}")
    return 0 if result['status']=='valid' else 2


if __name__=='__main__':
    raise SystemExit(main())
