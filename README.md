# PR review, without the queue

Cloover context: non-engineers across Ops/Sales/CS/Finance build internal tools with
Claude Code and open PRs. One person reviews everything by hand, ~3h/day, mostly
checking for data exposure risk (and, secondarily, crashes). That reviewer is now the
bottleneck for the whole company.

This repo is a working demo of a review pipeline that removes the queue for the PRs
that don't need a human, and hands the human a pre-annotated, high-signal queue for the
ones that do.

## The design

```
PR opened/updated
   │
   ├─► Deterministic scanners (review/scanners.py) - fast, no LLM, fail-closed
   │     • hardcoded secrets/tokens          • new outbound hosts (egress)
   │     • dependencies not on the allowlist • PII-shaped data (emails, SSNs, cards)
   │     • edits to the review pipeline itself
   │
   ├─► Claude review (review/claude_review.py) - the judgment layer
   │     structured JSON verdict: findings + severity + confidence + a
   │     plain-language summary for whoever ends up reading it
   │
   └─► Router (review/router.py) combines both into one of three tiers:

        Tier 0 — auto-merge          Tier 1 — auto-fix loop         Tier 2 — human
        no findings, high        →   only low/medium findings, →    hard-block category
        confidence                   none hard-blocking,             (secret/egress/pii/
                                      high confidence                 self-modification),
                                                                       OR high severity,
        bot approves, PR              bot comments with exactly       OR low confidence,
        merges, no human               what to fix; the builder's     OR a scanner error
        involved                       Claude Code fixes it and
                                        pushes again - re-reviewed    routed with a
                                        automatically, no human        pre-written summary,
                                        unless it fails twice          not a cold diff
```

Runs as a single GitHub Action (`.github/workflows/pr-review.yml`) on every
`pull_request` event. No separate service to host.

## Why this shape

**Hybrid, not "just ask Claude."** An LLM verdict alone isn't a hard guarantee - it can
miss things, and it's reading content it didn't write (more on that below). The
categories where a miss is actually costly - hardcoded secrets, calls to a new external
host, PII in the diff - get a **deterministic backstop** that doesn't depend on model
judgment at all. Claude handles what regex can't: is this refactor actually safe, does
this change plausibly widen access, is the intent of the diff what it claims to be.

**Fail-closed everywhere.** Confidence too low → Tier 2. A scanner throws → Tier 2, not
"skip and continue." No findings but the LLM step didn't run confidently → Tier 2. The
cost of a false "needs human" is a few wasted minutes; the cost of a false "safe" is a
data leak. The router (`review/router.py::decide_tier`) is written so every ambiguous
case falls toward the human, never toward auto-merge.

**The diff is untrusted input, not instructions.** It's code someone else's Claude Code
wrote. The review prompt puts it inside an explicit `<diff>` data block and tells the
model directly to ignore any text inside it that tries to direct its behavior ("ignore
previous instructions", "this is pre-approved", etc.) - see the system prompt in
`review/claude_review.py`. Output is forced through a tool call with a fixed schema, so
the router consumes structured data, never re-interprets free text.

**The pipeline can't approve edits to itself.** A PR that touches `review/` or
`.github/workflows/` is always hard-routed to a human
(`scanners.py::scan_self_modification`), regardless of how safe the change looks -
otherwise a bad actor (or an overeager Claude Code session) could quietly loosen the
gate in the same PR that needs it loosened. The GitHub Action also checks out `main`'s
copy of `review/` to run the pipeline, and only fetches the PR's head to *diff against*
- it never executes the PR's own copy of the reviewer. See the comment in the workflow
file and in `main.py::run_action`.

## What each tier means for the builder

- **Tier 0:** nothing to do, it's merged.
- **Tier 1:** a bot comment lists exactly what's wrong ("dependency `tabulate` isn't on
  the approved list"). They ask their Claude Code session to fix it and push again. No
  human touches this unless it fails a second time - that's the actual queue-reduction
  lever, since most real PRs are closer to Tier 1 or 0 than Tier 2.
- **Tier 2:** it lands in the human's queue, but with a written summary and itemized
  findings attached, instead of a cold diff. The reviewer's three hours become "skim the
  summary, confirm or override" instead of "read every line."

## Try it

Everything below runs without a real API key - `review/claude_review.py` falls back to
a clearly-labeled mock verdict when `ANTHROPIC_API_KEY` isn't set, so the pipeline is
fully runnable and testable offline. **The mock's confidence defaults low enough that it
can never authorize an auto-merge on its own** - that's the real fail-closed behavior
when the judgment layer is unavailable, not a demo shortcut. `REVIEW_MOCK_CONFIDENCE`
overrides it *only* to demo the Tier-0/Tier-1 happy path locally; production CI always
has a real key and never reads that variable.

```bash
pip install -r review/requirements.txt
cd review
```

Four branches simulate four incoming PRs against `main`:

| Branch | What it does | Result |
|---|---|---|
| `demo/safe-change` | adds a "closed today" count to the digest | Tier 0 |
| `demo/needs-small-fix` | adds a dependency not on the allowlist | Tier 1 |
| `demo/risky-change` | hardcodes a Slack webhook, calls an unlisted host, adds an unapproved dep, and adds a PII column | Tier 2 |
| `demo/edits-the-reviewer` | loosens `review/config.yaml`'s own threshold | Tier 2 (always, regardless of the change) |

```bash
# Tier 0 - clean PR (confidence override just to show the happy path offline)
REVIEW_MOCK_CONFIDENCE=0.9 python main.py --base main --head demo/safe-change

# Tier 1 - minor, fixable finding
REVIEW_MOCK_CONFIDENCE=0.9 python main.py --base main --head demo/needs-small-fix

# Tier 2 - the scanners alone are enough here, no key/override needed
python main.py --base main --head demo/risky-change

# Tier 2 - a PR that edits its own gate
python main.py --base main --head demo/edits-the-reviewer
```

With a real key exported as `ANTHROPIC_API_KEY`, the same commands call Claude for
real - try it against `demo/risky-change` to see the LLM's own plain-language summary
alongside the scanner findings.

`review/test_pipeline.py` pins all four scenarios as regression tests
(`pytest review/test_pipeline.py`) - the README examples can't drift from what the code
actually does.

To wire this up for real: add `ANTHROPIC_API_KEY` as a repo secret, and set the
`pr-review/data-safety` status check as required in branch protection. Tier 0 PRs can
then use GitHub's native auto-merge (enabled per-PR or org-wide); Tier 1/2 block the
merge button until resolved.

## Tradeoffs and what I'd revisit

- **Rollout order.** I'd ship this first as "bot comments + labels, human still clicks
  merge for everything," watch it for a week or two, *then* flip Tier 0 to true
  auto-merge once the false-negative rate is trusted. Same time savings on day one (you
  stop reading Tier 0 diffs), lower risk while the tiering is unproven.
- **Regex scanners are blunt on purpose.** The PII/secret patterns will false-positive
  on fixture data (they do, in this repo's own demo tickets.csv). That's intentional -
  false positives cost a few minutes in the fix loop or the human queue; false negatives
  cost a leak. I'd rather tune noise down over time than start permissive.
- **Same-org PRs assumed.** The workflow uses `pull_request`, which is right for
  internal contributors but gives a read-only token to forked PRs. Not a concern for an
  internal tools repo; if that changes, the fix is switching to `pull_request_target`
  with the same "checkout base, only diff against head" pattern already used here
  (see the workflow comment) - that pattern is what makes `pull_request_target` safe to
  use in the first place.
- **Correctness/crash risk is secondary here.** The brief said data exposure is the real
  risk and a small outage "is not the end of the world" - so the pipeline leans hard on
  data-safety categories and only asks the LLM to flag correctness issues opportunistically,
  rather than running a full test/lint gate. Wiring in the tool's own test suite as a
  required check (already present for the example tool, `example-tool/tests/`) would be
  the next thing I'd add.
- **One reviewer bot version, org-wide.** Every repo would point at the same
  `review/` pipeline (or a shared Action). Config (`allowlisted_dependencies`,
  `allowlisted_egress_hosts`) is per-repo, but the categories that are always
  hard-blocked and the fail-closed defaults are not something an individual repo/PR
  should be able to weaken - that's the whole point of the self-modification guard.

## Repo layout

```
example-tool/        the internal tool being reviewed (CS ticket digest -> Slack)
review/               the review pipeline
  scanners.py           deterministic checks
  claude_review.py       the LLM judgment layer
  router.py              combines both into a tier + renders the report
  pipeline.py             ties the above together (no GitHub-specific I/O)
  main.py                  CLI entrypoint: local mode + GitHub Actions mode
  github_report.py          posts PR comment / status / label (Action mode only)
  config.yaml               allowlists + thresholds
  test_pipeline.py          regression tests over the four demo branches
.github/workflows/pr-review.yml   wires main.py --action into pull_request events
```
