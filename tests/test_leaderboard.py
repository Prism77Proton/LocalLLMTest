import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import unittest.mock

import grade
import leaderboard


def graded(model, qids):
    key = grade.load_suite()[1]
    text = '\n'.join(json.dumps({'id': q, 'answer': key[q]}) for q in qids)
    return grade.evaluate(text, model)


def issue_event(number, model, body_answers):
    body = f'### Model\n\n{model}\n\n### Answers\n\n```text\n{body_answers}\n```'
    return {'action': 'labeled', 'label': {'name': 'leaderboard'},
            'issue': {'number': number, 'title': '[Model test] ' + model, 'body': body,
                      'created_at': '2026-11-05T12:00:00Z'}}


class LeaderboardTests(unittest.TestCase):
    def test_entry_has_category_scores_and_rank_order(self):
        with tempfile.TemporaryDirectory() as d:
            board = Path(d) / 'leaderboard.json'
            leaderboard.update(board, leaderboard.make_entry(graded('small', ['Q01']), 'a', 'local', '2026-11-01'))
            leaderboard.update(board, leaderboard.make_entry(graded('big', ['Q01', 'Q02']), 'b', 'local', '2026-11-02'))
            entries = leaderboard.update(board, leaderboard.make_entry(graded('small v2', ['Q01', 'Q02', 'Q03']), 'a', 'local', '2026-11-03'))
            self.assertEqual([(e['id'], e['points']) for e in entries], [('a', 6), ('b', 4)])  # same id replaced
            self.assertEqual(sum(c['maximum'] for c in entries[0]['categories'].values()), 100)
            self.assertEqual(entries[0]['categories']['Reasoning']['points'], 6)
            self.assertEqual(json.loads(board.read_text()), entries)

    def test_invalid_submission_is_never_listed(self):
        with self.assertRaises(ValueError):
            leaderboard.make_entry(grade.evaluate('not json', 'm'), 'x', 'local', '2026-11-05')

    def test_hostile_model_names_are_inert_in_markdown_and_html(self):
        name = 'x | y <script>alert(1)</script> [click](javascript:alert(1)) `code`\n### heading'
        entry = leaderboard.make_entry(graded(name, ['Q01']), 'issue-7', 'issue', '2026-11-05',
                                       'https://github.com/o/r/issues/7')
        self.assertNotIn('\n', entry['model'])
        markdown = leaderboard.render_markdown([entry])
        row = [line for line in markdown.splitlines() if line.startswith('| 1 |')][0]
        self.assertEqual(row.count(' | '), 8)  # 9 cells: the name's pipe cannot add a column
        self.assertNotIn('<script>', markdown)
        self.assertNotIn('](javascript', markdown)
        self.assertIn('[#7](https://github.com/o/r/issues/7)', row)
        page = leaderboard.render_html([entry])
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)

    def test_labeled_issue_is_graded_and_added(self):
        key = grade.load_suite()[1]
        answers = json.dumps({'id': 'Q01', 'answer': key['Q01']})
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            d = Path(d)
            (d / 'event.json').write_text(json.dumps(issue_event(12, 'Qwen3.8 Flash Next Q8_0', answers)))
            with unittest.mock.patch.dict(os.environ, {'GITHUB_REPOSITORY': 'Prism77Proton/LocalLLMTest'}):
                code = leaderboard.main(['--event', str(d / 'event.json'), '--board', str(d / 'b.json'),
                                         '--markdown', str(d / 'LEADERBOARD.md')])
            self.assertEqual(code, 0)
            entry = json.loads((d / 'b.json').read_text())[0]
            self.assertEqual((entry['id'], entry['points'], entry['date'], entry['source']),
                             ('issue-12', 2, '2026-11-05', 'issue'))
            self.assertIn('Qwen3\\.8 Flash Next Q8\\_0', (d / 'LEADERBOARD.md').read_text())

    def test_labeled_issue_with_bad_answers_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as out:
            d = Path(d)
            (d / 'event.json').write_text(json.dumps(issue_event(13, 'm', '{"id":"Q99","answer":{}}')))
            with unittest.mock.patch.dict(os.environ, {'GITHUB_REPOSITORY': 'o/r'}):
                code = leaderboard.main(['--event', str(d / 'event.json'), '--board', str(d / 'b.json'),
                                         '--markdown', str(d / 'L.md')])
            self.assertEqual(code, 2)
            self.assertFalse((d / 'b.json').exists())
            self.assertIn('Not added', out.getvalue())

    def test_published_board_files_match_the_generator(self):
        entries = leaderboard.load(leaderboard.ROOT / 'leaderboard' / 'leaderboard.json')
        self.assertEqual((leaderboard.ROOT / 'LEADERBOARD.md').read_text(), leaderboard.render_markdown(entries))


if __name__ == '__main__':
    unittest.main()
