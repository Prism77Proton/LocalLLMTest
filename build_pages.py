"""Build the public demo from example data only; never publish local model runs."""
import argparse
from pathlib import Path

import grade
from leaderboard import REPOSITORY

ROOT=Path(__file__).resolve().parent


def build(destination):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    result=grade.evaluate((ROOT/'examples/demo-answers.jsonl').read_text(),
        'Illustrative partial submission — not a measured model result')
    report=grade.render_html(result)
    cta=f'''<aside style="border:1px solid #38bdf8;border-radius:14px;padding:22px;margin-bottom:30px;background:#111827">
<strong style="font-size:24px">How does your model score?</strong>
<p>50 questions. 100 exact checks. No AI judge.</p>
<p><a style="color:#7dd3fc" href="{REPOSITORY}#run-against-your-model">Run against your model</a> ·
<a style="color:#7dd3fc" href="{REPOSITORY}/issues/new?template=model-test.yml">Paste answers for a report</a> ·
<a style="color:#7dd3fc" href="{REPOSITORY}">View repository</a></p>
<small>This is a deliberately mixed partial example: correct, incorrect, and missing answers. It is not a leaderboard or a real model score.</small></aside>'''
    report=report.replace('<header>',cta+'<header>',1)
    (destination/'index.html').write_text(report,encoding='utf-8')
    (destination/'chart.svg').write_text(grade.chart(result),encoding='utf-8')
    (destination/'.nojekyll').write_text('')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'_site')
    build(p.parse_args().out)
