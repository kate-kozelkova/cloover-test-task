# PR review, without the queue

Cloover context: non-engineers across Ops/Sales/CS/Finance build internal tools with
Claude Code and open PRs. One person reviews everything by hand, ~3h/day, mostly
checking for data exposure risk (and, secondarily, crashes). That reviewer is now the
bottleneck for the whole company.

This repo is a working, minimal review pipeline: it clears the PRs that don't need a
human, and hands the human a pre-annotated, high-signal queue for the ones that do.
Scope was kept deliberately small - this is meant to be something that actually runs,
not a showcase of how elaborate an agentic pipeline could get.

## The design

When a PR opens or updates, two checks run against the diff. A set of deterministic
scanners (`review/scanners.py`) look for hardcoded secrets or tokens, calls to hosts
outside the egress allowlist, dependencies that aren't approved, and PII-shaped data
such as emails, SSNs, or card numbers - all fast, no LLM involved. Separately, Claude
reviews the same diff (`review/claude_review.py`) and returns one structured verdict: a
list of findings, a confidence score, and a plain-language summary for whoever reads it
next.

The router (`review/router.py`) then makes exactly one decision, fail-closed: the PR
auto-merges only if there are zero findings and the review was confident. Anything else
- a finding from either source, a scanner error, or low confidence - routes to a human,
with the findings and summary already attached rather than a cold diff.

All of this runs as a single GitHub Action (`.github/workflows/pr-review.yml`) on every
`pull_request` event. No separate service to host, no agent loop, no autonomy - one
deterministic pass plus one Claude API call per PR.

## Why this shape

**Hybrid, not "just ask Claude."** An LLM verdict alone isn't a hard guarantee - it can
miss things, and it's reading content it didn't write (more below). The categories
where a miss is actually costly - hardcoded secrets, calls to a new external host, PII
in the diff - get a **deterministic backstop** that doesn't depend on model judgment at
all. Claude handles what regex can't: whether a change plausibly widens access or
exposes data in a way no fixed pattern would catch.

**Fail-closed, and genuinely simple about it.** The router has exactly one rule: auto-
merge only if there are zero findings *and* the reviewer was confident. Any finding, any
scanner error, or low confidence all fall the same direction - to a human. No severity
tiers, no partial-automation states to reason about. The cost of a false "needs human" is
a few wasted minutes; the cost of a false "safe" is a data leak, so the rule is
deliberately lopsided.

**The diff is untrusted input, not instructions.** It's code someone else's Claude Code
wrote. The review prompt puts it inside an explicit `<diff>` data block and tells the
model directly to ignore any text inside it that tries to direct its behavior ("ignore
previous instructions", "this is pre-approved", etc.) - see the system prompt in
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

To wire this up for real: add `ANTHROPIC_API_KEY` as a repo secret, and set the
`pr-review/data-safety` status check as required in branch protection. GitHub's native
auto-merge (enabled per-PR or org-wide) then does the rest for clean PRs.

## Tradeoffs and what I'd add next

- **Scope, on purpose.** This was built to fit a couple of hours, not to demonstrate
  every idea I had. Things I considered and deliberately left out rather than half-build:
  an automated fix-loop tier (bot comments, builder's Claude Code fixes, re-review with
  no human in the loop for minor issues), and a guard against a PR that edits the review
  pipeline's own code to weaken its own gate. Both are real gaps worth closing before
  this runs on a real queue - the second one especially, since a self-serving edit to
  `config.yaml` (loosening the confidence threshold, say) would currently only get
  caught if it happens to also trip one of the content scanners. The fix is cheap - a
  scanner that treats any diff touching `review/` or `.github/workflows/` as an
  automatic "needs human", plus running the pipeline from a trusted checkout of `main`
  rather than the PR's own copy - but it's exactly the kind of addition that's better
  discussed than shipped speculatively.
- **Regex scanners are blunt on purpose.** The PII/secret patterns will false-positive on
  fixture data (they do, in this repo's own demo tickets.csv). That's intentional -
  false positives cost a few minutes in the human queue; false negatives cost a leak.
- **Rollout order.** I'd ship this first as "bot comments, human still clicks merge for
  everything," watch it for a week, then flip auto-merge on once the false-negative rate
  is trusted. Same time savings on day one (you stop reading the clean PRs); lower risk
  while it's unproven.
- **Same-org PRs assumed.** The workflow uses `pull_request`, which is right for internal
  contributors but gives a read-only token to forked PRs. Not a concern for an internal
  tools repo.
- **Correctness/crash risk is secondary here.** The brief said data exposure is the real
  risk and a small outage "is not the end of the world," so the pipeline leans on
  data-safety categories and only asks the LLM to flag correctness issues
  opportunistically, rather than running a full test/lint gate.

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
