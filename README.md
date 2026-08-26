# PR Review Pipeline

## The design

When a PR opens/updates, two checks run against the difference. A set of
scanners (`review/scanners.py`) look for included credentials, calls to hosts
outside the allowed list, unapproved dependencies, and PII-shaped data
such as emails, SSNs, or card numbers. Separately, Claude
reviews the same diff (`review/claude_review.py`) and returns one outcome: a
list of findings, a confidence score, and a plain summary.

The router (`review/router.py`) then makes exactly one decision, fail-closed: the PR
auto-merges only if there are zero findings and the review was confident (>0.84). Anything else
is routed for a review, with the findings and summary attached.

All of this runs as a single GitHub Action (`.github/workflows/pr-review.yml`) on every `pull_request` event.

## Decision Justification

**Hybrid > Only LLM** An LLM verdict alone isn't a 100% guarantee - it still might miss things. Instead, PRs where a miss is actually costly get a check that doesn't depend on model judgment. Then, LLM handles the rest: whether a change exposes access or data in a way the first pattern wouldn't catch.

**Simple and fail-closed** There's only one rule: auto-merge only if there are zero findings *and* the reviewer was confident. Any finding or low confidence - to a human. Even if the flagged PR doesn't expose anything, the human approval/rejection won't take that long thanks to the context provided.

**The diff is untrusted input, not instructions.** Since the input is the code someone else wrote, it might include `<>` data blocks or explicitly tell to ignore any text inside it that tries to direct its behavior ("ignore previous instructions", "this is pre-approved", etc.) - see the system prompt in
`review/claude_review.py`. Output is forced through a tool call with a fixed schema, so
the router consumes structured data, never re-interprets free text.

## Try it

Everything below runs without a real API key - `review/claude_review.py` falls back to
a clearly-labeled mock verdict when `ANTHROPIC_API_KEY` isn't set, with confidence fixed
low enough that a mock review can never authorize an auto-merge on its own. That means
offline runs will always show the "needs human" path - to see an actual auto-merge,
export a real key or let CI (which always has one) run it for real.

```bash
pip install -r review/requirements.txt
cd review
```

Two branches simulate two incoming PRs against `main`:

| Branch | What it does | Result |
|---|---|---|
| `demo/safe-change` | adds a "closed today" count to the digest | auto-merge (with a real key; offline mock always says needs-human) |
| `demo/risky-change` | hardcodes a Slack webhook, calls an unlisted host, adds an unapproved dep, and adds a PII column | needs human - caught by the scanners alone, no key needed |

```bash
python main.py --base main --head demo/safe-change
python main.py --base main --head demo/risky-change
```

`review/test_pipeline.py` covers the router's decision logic and each scanner against
synthetic diffs (`pytest review/test_pipeline.py`) - no git state, no network, no env
vars, so the tests can't drift from what the code actually does.

## Deployment

Three one-time settings turn this from a demo into something that actually gates
merges:

1. **Add the API key.** Repo → Settings → Secrets and variables → Actions → New
   repository secret → `ANTHROPIC_API_KEY`. Without this, the reviewer falls back to
   the offline mock described above, and nothing can ever auto-merge.
2. **Make the check block merges.** Repo → Settings → Branches → branch protection
   rule for `main` → require status checks to pass → add `pr-review/data-safety`.
   Without this, the check still runs and reports, but nothing stops a PR from being
   merged by hand regardless of the result.
3. **(Optional) Name a human to notify.** Settings → Secrets and variables → Actions →
   Variables tab → New repository variable → `REVIEWER_GITHUB_USERNAME` → your GitHub
   username. When a PR needs a human, the pipeline formally requests a review from
   this person - a real GitHub notification, not just a comment someone might miss.
   Leave it unset to skip this step.

Once those are set, every PR triggers `.github/workflows/pr-review.yml` on its own. A
clean, confident review passes the check, and GitHub's native auto-merge (enable it
per-PR, or repo-wide in Settings → General) merges it with no one involved. Anything
else fails the check and blocks the merge button, with the findings and Claude's
summary already posted as a PR comment - and, if step 3 is set, a formal review
request waiting in the named reviewer's queue.

## Repo layout

```
example-tool/        the internal tool being reviewed (CS ticket digest -> Slack)
review/               the review pipeline
  scanners.py           deterministic checks
  claude_review.py       the LLM judgment layer
  router.py               combines both into a decision + renders the report
  pipeline.py               ties the above together (no GitHub-specific I/O)
  main.py                    CLI entrypoint: local mode + GitHub Actions mode
  github_report.py            posts PR comment / status / label (Action mode only)
  config.yaml                  allowlists + confidence threshold
  test_pipeline.py              unit tests over synthetic diffs
.github/workflows/pr-review.yml   wires main.py --action into pull_request events
```
