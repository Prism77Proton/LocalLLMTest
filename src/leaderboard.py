#!/usr/bin/env python3
"""Rank graded runs by exact score, with per-category totals. Standard library only.

Local runs are recorded by run_models.py into results/. The public board in
src/leaderboard/ is updated by GitHub Actions when a maintainer labels a graded issue.
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
from pathlib import Path

import grade

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'https://github.com/Prism77Proton/LocalLLMTest'
_MD_SPECIAL = re.compile(r'([\\`*_{}\[\]()#+\-.!|<>~])')


def clean_name(name):
    """One printable line of at most 120 characters; never trusted as Markdown or HTML."""
    name = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(name))
    name = ' '.join(name.split())[:120]
    return name or 'Unnamed model'


def md(text):
    return _MD_SPECIAL.sub(r'\\\1', text)


def categories():
    """Category names in suite order, so every board shows the same columns."""
    seen = []
    for q in grade.load_suite()[0]['questions']:
        if q['category'] not in seen:
            seen.append(q['category'])
    return seen


def make_entry(result, entry_id, source, date, link=''):
    if result.get('status') != 'valid':
        raise ValueError('Only a valid graded submission can be listed.')
    return dict(id=entry_id, model=clean_name(result['model']), points=result['points'],
                maximum=result['maximum'], answered=result['answered'],
                questions=len(result['questions']),
                categories={name: dict(points=c['points'], maximum=c['maximum'])
                            for name, c in result['categories'].items()},
                version=result['version'], suite_sha256=result['suite_sha256'],
                submission_sha256=result['submission_sha256'], source=source, date=date, link=link)


def load(board):
    board = Path(board)
    if not board.exists():
        return []
    entries = json.loads(board.read_text(encoding='utf-8'))
    if not isinstance(entries, list):
        raise ValueError(f'{board} must contain a JSON list.')
    return entries


def ranked(entries):
    return sorted(entries, key=lambda e: (-e['points'], -e['answered'], e['date'], e['model'], e['id']))


def update(board, entry):
    """Add the entry, replacing an earlier one with the same id, and save the ranked list."""
    entries = ranked([e for e in load(board) if e['id'] != entry['id']] + [entry])
    board = Path(board)
    board.parent.mkdir(parents=True, exist_ok=True)
    temp = board.with_suffix(board.suffix + '.tmp')
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(board)
    return entries


def _fraction(c):
    return f'{c["points"]}/{c["maximum"]}' if c else '–'


def render_markdown(entries, title='Leaderboard'):
    names = categories()
    lines = [f'# {title}', '',
             'Exact scores on the 50-question deterministic test: 100 typed field checks, no AI judge.',
             'Entries are self-reported answers graded by `grade.py`. The answer key is public, so this is',
             'a practice board, not a verified benchmark. Partial runs score zero for missing questions.', '']
    if not entries:
        return '\n'.join(lines + ['No entries yet.', ''])
    lines += ['| # | Model | Score | ' + ' | '.join(names) + ' | Answered | Date | Source |',
              '|---:|---|---:|' + '---:|' * len(names) + '---:|---|---|']
    for rank, e in enumerate(ranked(entries), 1):
        cells = [_fraction(e['categories'].get(n)) for n in names]
        partial = '' if e['answered'] == e['questions'] else ' (partial)'
        if e['source'] == 'issue' and e['link']:
            source = f'[#{e["id"].removeprefix("issue-")}]({e["link"]})'
        elif e['link']:
            source = f'[report]({e["link"]})'
        else:
            source = e['source']
        lines.append(f'| {rank} | {md(e["model"])}{partial} | **{e["points"]}**/{e["maximum"]} | '
                     + ' | '.join(cells) + f' | {e["answered"]}/{e["questions"]} | {e["date"]} | {source} |')
    return '\n'.join(lines + [''])


def render_html(entries, title='Leaderboard'):
    esc = html.escape
    names = categories()
    rows = []
    for rank, e in enumerate(ranked(entries), 1):
        bars = []
        for n in names:
            c = e['categories'].get(n)
            pct = round(100 * c['points'] / c['maximum']) if c and c['maximum'] else 0
            bars.append(f'<td><div class="bar"><span style="width:{pct}%"></span></div>{esc(_fraction(c))}</td>')
        link = e['link']
        model = esc(e['model'])
        if link and (link.startswith('https://github.com/') or not re.match(r'^[a-z]+:', link)):
            model = f'<a href="{esc(link)}">{model}</a>'
        partial = '' if e['answered'] == e['questions'] else ' <small>partial</small>'
        rows.append(f'<tr><td>{rank}</td><td>{model}{partial}</td><td class="score">{e["points"]}<small>/{e["maximum"]}</small></td>'
                    f'{"".join(bars)}<td>{e["answered"]}/{e["questions"]}</td><td>{esc(e["date"])}</td></tr>')
    body = (f'<table><thead><tr><th>#</th><th>Model</th><th>Score</th>{"".join(f"<th>{esc(n)}</th>" for n in names)}'
            f'<th>Answered</th><th>Date</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
            if rows else '<p>No entries yet.</p>')
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{esc(title)}</title><style>
:root{{color-scheme:dark}}body{{font:16px/1.5 system-ui,sans-serif;background:#080e1a;color:#e2e8f0;max-width:1180px;margin:auto;padding:32px 16px}}
h1{{font-size:clamp(28px,5vw,44px);margin:0 0 6px}}p{{color:#94a3b8}}.wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{text-align:left;padding:10px 8px;border-bottom:1px solid #334155;vertical-align:middle;white-space:nowrap}}td:nth-child(2){{white-space:normal;min-width:180px}}
th{{color:#94a3b8;font-weight:600}}.score{{font-size:20px;font-weight:700}}small{{color:#94a3b8}}a{{color:#7dd3fc}}
.bar{{width:90px;height:6px;background:#1e293b;border-radius:3px;margin-bottom:4px}}.bar span{{display:block;height:100%;background:#38bdf8;border-radius:3px}}
@media print{{body{{background:white;color:black}}}}</style>
<h1>{esc(title)}</h1><p>Exact scores on the 50-question deterministic test (100 typed field checks, no AI judge). Partial runs score zero for missing questions.</p>
<div class="wrap">{body}</div></html>'''


def write_board(directory, entries, title='Leaderboard'):
    directory = Path(directory)
    (directory / 'leaderboard.md').write_text(render_markdown(entries, title), encoding='utf-8')
    (directory / 'leaderboard.html').write_text(render_html(entries, title), encoding='utf-8')


def record_local(run_folder, result, board_dir):
    """Called by run_models.py after a run; one entry per run folder, updated on resume."""
    run_folder, board_dir = Path(run_folder), Path(board_dir)
    link = os.path.relpath(run_folder / 'report.html', board_dir).replace(os.sep, '/')
    entry = make_entry(result, run_folder.name, 'local', datetime.date.today().isoformat(), link)
    entries = update(board_dir / 'leaderboard.json', entry)
    write_board(board_dir, entries, 'Local leaderboard')
    return entries


def entry_from_issue_event(event, repository):
    """Grade the labeled issue's current text and turn it into a public entry."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository name.')
    issue = event.get('issue') or {}
    number = issue.get('number')
    if type(number) is not int or number <= 0:
        raise ValueError('Invalid issue number.')
    created = str(issue.get('created_at') or '')[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', created):
        created = datetime.date.today().isoformat()
    text, model = grade.issue_submission(event)
    result = grade.evaluate(text, model)
    if result['status'] != 'valid':
        raise grade.SubmissionError(result['error'])
    return make_entry(result, f'issue-{number}', 'issue', created,
                      f'https://github.com/{repository}/issues/{number}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', type=Path, help='GitHub issues "labeled" event JSON to grade and add.')
    parser.add_argument('--board', type=Path, default=ROOT / 'leaderboard' / 'leaderboard.json')
    parser.add_argument('--markdown', type=Path, default=ROOT.parent / 'LEADERBOARD.md')
    args = parser.parse_args(argv)
    entries = load(args.board)
    if args.event:
        try:
            event = grade.loads(grade.read_bounded(args.event))
            entry = entry_from_issue_event(event, os.environ.get('GITHUB_REPOSITORY', ''))
        except (grade.SubmissionError, ValueError) as error:
            print('Not added to the leaderboard:', error)
            return 2
        entries = update(args.board, entry)
        print(f'Added {entry["id"]}: {entry["points"]}/{entry["maximum"]}')
    args.markdown.write_text(render_markdown(entries), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
