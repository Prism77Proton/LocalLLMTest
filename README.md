# Deterministic Model Test 50 — v2

**How does your model score?** 50 questions. 100 exact checks. No AI judge.

[**Open the report demo**](https://prism77proton.github.io/LocalLLMTest/) ·
[**Test your model**](#quick-start) ·
[**Leaderboard**](LEADERBOARD.md) ·
[**Paste answers**](https://github.com/Prism77Proton/LocalLLMTest/issues/new?template=model-test.yml)

[![Sample model test report: per-question results and category scores](src/example-report/chart.svg)](https://prism77proton.github.io/LocalLLMTest/)

*Illustrative partial submission, not a measured model score. The full report
shows every check, the expected value, and what the model returned.*

Point it at any model server, pick a model, and it asks the 50 questions one at a
time, grades the answers deterministically and writes a report. Results can go on
the [**leaderboard**](LEADERBOARD.md) with scores for Reasoning, Mathematics, and
Code and systems. No AI judge, paid API, or external Python packages.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/Prism77Proton/LocalLLMTest/main/install.sh | bash
```

The installer checks for Python 3.12+, downloads the test to `~/LocalLLMTest`,
checks the grader, adds an `llmtest` command and offers to start a test. From a
copy of this repository, run `./install.sh` instead. Then, any time:

```bash
llmtest
```

1. Enter the server address (the last one is remembered), for example `http://localhost:1234`.
2. Pick a model from the server's list. A loaded model is marked and pre-selected; press Enter.
3. The questions are sent one at a time, each in a fresh request, with the score so far after each.
4. At the end you get the score by category, a report and a local leaderboard entry.
5. A complete run then offers to submit itself: press Enter at
   `Submit to the public leaderboard? [Y/n]` ([details](#submit-to-the-public-leaderboard)).

`llmtest board` opens the local leaderboard of every model you have tested.

## Run against your model

Start your inference server first; the test does not start one. `llmtest` is a
shortcut for `python src/run_models.py`, so either works with the options below.

- **LM Studio:** native model listing and explicit `/api/v1/models/load`.
- **Unsloth Studio:** `/v1/models` plus explicit `/api/inference/load`.
- **Other OpenAI-compatible servers:** `/v1/models` and `/v1/chat/completions`;
  the server must already serve the model, because OpenAI compatibility has no
  standard model-loading API. A standalone llama-server already serves its model.

A model the server already has loaded is tested as it is running, without loading
another copy, and keeps its own context (which must leave room for `--max-tokens`
plus a question). Choosing a model that is not loaded loads it at `--context`.
Without a terminal (in scripts), the loaded model is used without asking.

```bash
python src/run_models.py                               # interactive: address, model, run
python src/run_models.py --url http://localhost:1234 --list
python src/run_models.py --url http://localhost:1234 --model EXACT_ID --only Q01
python src/run_models.py --url http://localhost:1234 --resume   # continue that model's last run
```

For authentication use `--key-file`, the `MODEL_API_KEY` environment variable (or
`--key-env NAME`), or the hidden prompt after an authentication failure. Keys are
not stored in the run folder or sent to GitHub. Redirects are refused and
environment proxies are bypassed.

Defaults: context 32768, maximum output 8192 tokens, temperature 0, load timeout
1800 seconds, question timeout 10800 seconds. Adjust with `--context`, `--max-tokens`,
`--temperature`, `--load-timeout`, `--timeout`. Temperature 0 does not promise
bit-for-bit reproducible generation; **grading** is deterministic. Backend-specific
settings can be supplied with `--load-options private-load.json` and
`--chat-options private-chat.json` (JSON objects; chat options may include thinking
controls). The runner refuses overrides of question isolation, model identity or
transport settings, and never changes CPU limits or system services.

### What a run produces

Each run gets its own folder, `results/<model>_<date-time>/`:

| File | Contents |
|---|---|
| `report.html` | The report: score, category totals, every check with expected and received values |
| `summary.md`, `results.json`, `checks.csv`, `chart.svg` | The same results as Markdown, JSON, CSV and a graphic |
| `answers.jsonl` | The graded answers, ready to paste into a GitHub issue |
| `raw/` | Every request's streamed events, answer and reasoning text, timing, token usage and errors |

The report is rebuilt after every question, so it can be opened during a run. Only
the question prompt is sent, never the answer key. `results/` is ignored by git;
keep run folders private unless you mean to publish them.

A completed answer with malformed output, or one cut off by the token limit, is
graded as two null fields: exactly zero credit. The runner never guesses or repairs
an answer; the raw response is preserved. A transport failure stops the run and
that question stays missing until `--resume`. Resume requires the same server,
model, settings and questions; completed questions are not sent again, and failed
attempts are archived in `raw/attempts/`. Two runners cannot share a run folder.

Ctrl+C saves partial output and stops this client. It does **not** guarantee the
server cancels inference or unloads the model; use the server's Stop/Unload control.
The runner leaves the model loaded after a test.

## Leaderboard

Every run adds a row to the **local** leaderboard (`results/leaderboard.html` and
`.md`): total score, the three category scores, questions answered, and a link to
the run's report. Partial runs are listed and marked.

The **public** board is [LEADERBOARD.md](LEADERBOARD.md). GitHub Actions grades each
submission and comments with the score. A maintainer then adds the **`leaderboard`**
label, and the *Add to leaderboard* workflow re-grades the issue and commits the row.
Only people with triage or write access can add labels, so nobody else can put
entries on the board. The answer key is public, so the board is self-reported
practice data, not a verified benchmark.

### Submit to the public leaderboard

When a run has answered all 50 questions, `llmtest` offers to submit it. Press Enter
and it opens a **public** issue titled `[Model test] <model>` on this repository
through the GitHub API, with your answers in the issue form's format, and prints the
issue's link. Nothing is posted without that Enter. Only the model name and your
answers are posted (including any optional `rationale` text the model wrote), never
the questions, raw recordings or any server key.

Posting needs a GitHub login, because GitHub has no anonymous issue creation. The
runner uses the first of these it finds:

1. the `GITHUB_TOKEN` or `GH_TOKEN` environment variable (a classic personal access
   token with the `public_repo` scope),
2. the [GitHub CLI](https://cli.github.com/): run `gh auth login` once,
3. a one-time-code login in your browser, once the project has registered a GitHub
   app (`CLIENT_ID` in `src/submit.py`; it is empty until then).

The token is held in memory only and never written to disk. If none is available, or
GitHub refuses, the runner copies your answers to the clipboard and opens the
pre-filled issue form instead; press Ctrl+V and submit.

```bash
llmtest --submit        # test, then post without asking (complete runs only)
llmtest --no-submit     # test, and do not offer to post
llmtest submit          # post the latest finished run later, e.g. after logging in
llmtest submit --out results/<run-folder>   # or a specific run
```

An incomplete run is never posted automatically; resume it with `--resume` first.
Without a terminal (in scripts) nothing is posted unless `--submit` is given.

Maintainer setup, once: create a label named `leaderboard`, and make sure Actions
may push to `main` (no branch protection rule blocking `github-actions[bot]`).

## Report on the repository front page

The README embeds the example graphic and links the full report demo above.
To make that demo live, set **Settings → Pages → Build and deployment → Source →
GitHub Actions**, then run **Actions → Publish report demo**. Later changes to the
demo inputs rebuild it automatically on `main`. The Pages workflow publishes
only the illustrative demo, never files from `results/` or issue submissions.
See [GitHub Pages setup](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

Native model APIs: [LM Studio listing](https://lmstudio.ai/docs/developer/rest/list),
[LM Studio loading](https://lmstudio.ai/docs/developer/rest/load), and
[Unsloth API source](https://github.com/unslothai/unsloth/blob/main/studio/backend/routes/inference.py).

## Put it on GitHub

1. Create a repository with Issues and Actions enabled.
2. Commit this folder's **contents at the repository root**, including `.github`.
   The workflow and issue form must be on the default branch. A ZIP alone in the
   repository does not install the workflow. If uploading through a browser hides
   `.github`, create its files using GitHub's Add file editor with their full paths.
3. Go to **Issues → New issue → Model test**.
4. Enter the model name and paste the JSONL answers. Submit the issue.
5. A report comment links the download. Unzip it and open `report.html`.
   The Actions run also displays the score summary. Editing the issue regenerates
   the report and posts another comment with the new snapshot's report.

No custom secrets or model hosting are required. The workflow uses GitHub's
automatically supplied token to comment in this repository. Repository/organization
policies must allow the listed actions and the job's `issues: write` permission.

It processes issue event snapshots, so each report records the exact submitted text
hash rather than silently changing an older report when an issue is edited.

GitHub documents [issue form behavior](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms),
[issue-triggered workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues),
and [artifact downloads](https://docs.github.com/en/actions/managing-workflow-runs/downloading-workflow-artifacts).
Standard hosted runners in public repositories are free; private repositories use
the plan's included compute allowance. Artifact storage has separate allowances.
See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
This workflow retains small report artifacts for seven days. Download reports you
want to keep. Issue comments preserve the numeric summary after artifacts expire.
Downloading artifacts requires GitHub sign-in and repository read access.

## Run the model one question at a time

Give the model **only** `questions/Q01.txt`, then Q02.txt, etc., in fresh contexts.
Each file includes instructions and one question, without an answer key. Do not
give the tested model this full repository: it contains the oracle and grading code.
Concatenate the returned one-line JSON records into one text file or the issue form.
A partial run of even one question is supported. As more answers arrive, append
them to the same issue's Answers block and save the edit. Retain the form headings.

The format is one record per nonblank line:

```json
{"id":"Qnn","answer":{"first_field":"value","second_field":"value"}}
```

That is a format illustration, not a valid question/answer. Actual field names and
types appear in each question. Optional top-level `rationale` is an unscored string.
No Markdown or surrounding prose in a model response. The issue form supplies the
outer text fence automatically; paste the records without adding another fence.
The local CLI also accepts one outer `text`, `json`, or `jsonl` fence.

Use JSON integer numbers, exact reduced rational strings `n/d`, Boolean literals,
and arrays ordered as specified. Object key order does not matter. Integer-looking
decimals such as `1.0`, exponent notation, NaN, duplicate JSON keys, duplicate or
unknown question IDs, and missing/extra answer fields invalidate the submission.
A Boolean in place of an integer is a wrong typed value, not a numeric match.
Oversized (>1 MB), invalid UTF-8, and excessively nested input are rejected.

There are **100 independent field checks**, two per question. Each complete field
earns exactly 1 or 0 points; an array field must match in its entirety. Missing
questions are gray and score zero toward the full 100. The report separately shows
the score over attempted fields. Format-invalid submissions receive **no score**.
Every result includes hashes of the suite+key and submitted text. Same suite and
answers always produce the same grades; model label and GitHub timing do not affect them.

## What changed from the original test

All 50 original topics have revised tasks with finite, specified output contracts.
For example, proof obligations became exact extrema, counterexample certificates,
trace predictions, or fixed-case decisions. Open programming implementations became
code and systems analysis over fixed fixtures. No submitted code is executed.

This is a **different test**: it measures exact output correctness, structured
instruction following, and the supplied certificates. It does not establish that
an arbitrary proof is valid, an unrestricted program is correct, or a model can
implement the complete original specification. No human-review queue or semantic
grader is used. Scores are not comparable to v1 and are not calibrated percentiles.
Deterministic scoring does not establish that an answer key is infallible. Oracle
tests independently enumerate finite fixtures and check exact arithmetic; changes
to questions/keys require a version change and review. Publishing the oracle makes
this an open practice test, not a contamination-resistant hidden benchmark.

## Repository layout

The root holds what you use; the engine lives in `src/`.

| Path | What it is |
|---|---|
| `install.sh` | Installer: downloads the test and adds the `llmtest` command |
| `QUESTIONS.md`, `MODEL_INSTRUCTIONS.txt`, `questions/` | The 50 questions, for testing a chat-only model by hand |
| `LEADERBOARD.md` | The public board |
| `results/` | Your runs and local leaderboard (created on the first run; git-ignored) |
| `MANIFEST.sha256` | Checksums of every file: `sha256sum -c MANIFEST.sha256` |
| `src/` | The runner, grader, leaderboard and tests, plus the answer key and demo data |

## Local use

Python 3.12 or later, standard library only:

```bash
(cd src && python -m unittest discover -s tests -v)
python src/grade.py --answers answers.jsonl --model "Model and settings" --out report
```

`src/examples/demo-answers.jsonl` is a deliberately mixed partial submission. The
included `src/example-report/report.html` is its generated preview, not a real model result.
Exit 0 means valid submission (even a score of zero); exit 2 means invalid format.
Use `results.json` to decide score thresholds separately.

`src/build_suite.py` regenerates the public questions and oracle (the root `QUESTIONS.md`,
`MODEL_INSTRUCTIONS.txt` and `questions/`, and the two JSON files in `src/`). It is a maintenance
tool, not run against submissions. Keep the two generated JSON files versioned.
`test.yml` checks the grader on pushes and pull requests with read-only permissions;
`grade.yml` checks it again before processing issue data. Submitted code and shell
fragments remain inert strings. HTML output escapes all submitted values and uses
no scripts or external resources. Full reports contain answer-key values, so they
are for reviewing a completed attempt, not feeding back into an ongoing closed-book attempt.

No license has been selected; choose one before offering explicit reuse terms.
