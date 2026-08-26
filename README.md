# PR Review Pipeline

## Design

A set of scanners (`review/scanners.py`) look for credentials, calls to hosts outside the allowed list, unapproved dependencies, PII data such as emails, SSNs, or card numbers, edits to the review pipeline itself, and Python files with syntax errors or broken references via `pyflakes` (calling something undefined, an unused import etc.). Separately, LLM reviews the same diff (`review/claude_review.py`) alongside the full content of a changed file, so it can estimate whether a change is consistent with the rest of the file. It returns its own findings, a confidence score, and a plain summary. The router (`review/router.py`) combines LLM's findings with what the scanners already flagged and makes a decision: the PR auto-merges only if that combined output list is empty and the review is confident (>0.84). Otherwise, it is routed for a review, with all the findings and the summary attached.

## Decision Justification

**Hybrid > Only LLM** An LLM verdict alone isn't a 100% guarantee - it still might miss things. Instead, PRs where a miss is actually costly get a check that doesn't depend on model judgment. Then, LLM handles the rest: whether a change exposes access or data in a way the first pattern wouldn't catch.

**Simple and fail-closed** There's only one rule: auto-merge only if there are zero findings *and* the reviewer was confident. Any finding or low confidence - to a human. Even if the flagged PR doesn't expose anything, the human approval/rejection won't take that long thanks to the context provided.

**The diff is untrusted input, not instructions.** Since the input is the code someone else wrote, it might include `<>` data blocks or explicitly tell to ignore any text inside it that tries to direct its behavior ("ignore previous instructions", "this is pre-approved", etc.) - see the system prompt in
`review/claude_review.py`. Output is forced through a tool call with a fixed schema, so
the router consumes structured data, never re-interprets free text.

## Try it

1. **Add the API key.** Repo -> Settings -> Secrets and variables -> Actions -> New repository secret -> `ANTHROPIC_API_KEY`. Without this, it can never authorize an auto-merge on its own, thanks to the low fixed confidence level. Therefore, offline runs will always show the "needs human" path.
2. **Make the check block merges.** Repo -> Settings -> Branches -> branch protection rule for `main` -> require status checks to pass -> add `pr-review/data-safety`. Otherwise, the check will still run and report, but nothing will stop a PR from being merged by hand regardless of the result.
3. **(Optional) Assign a reviewer.** Settings -> Secrets and variables -> Actions -> Variables tab -> New repository variable -> `REVIEWER_GITHUB_USERNAME` -> enter GitHub username. The pipeline formally requests a review from the assigned person.

```bash
pip install -r review/requirements.txt
cd review
```

Three branches simulate three incoming PRs against `main`:

| Branch | What it does | Result |
|---|---|---|
| `demo/safe-change` | adds a "closed today" count to the digest | auto-merge |
| `demo/risky-change` | hardcodes a Slack webhook, calls an unlisted host, adds an unapproved dep, and adds a PII column | needs human |
| `demo/ambiguous-change` | forwards the entire raw ticket row to Slack instead of the specific fields the alert needs | needs human, but only if LLM actually notices the scope issue. Scanners find nothing here, so this one tests the LLM layer |

```bash
python main.py --base main --head demo/safe-change
python main.py --base main --head demo/risky-change
python main.py --base main --head demo/ambiguous-change
```

`review/test_pipeline.py` covers the router's decision logic and each scanner against synthetic diffs (`pytest review/test_pipeline.py`) - no git state, no network, no env vars, so the tests can't drift from what the code actually does.

Every PR triggers `.github/workflows/pr-review.yml` automatically. To see it work on your own PR: open a PR, then check the PR's **Checks** tab or the status row at the bottom of the **Conversation** tab. After a review, you'll see:

- a comment from the bot with the decision, Claude's summary, and findings
- the `pr-review/data-safety` check, green if passed, red if it didn't
- a `review:auto-merge` or `review:needs-human` label on the PR

A clean and confident review passes the check, and GitHub merges it. Otherwise, the check fails and blocks the merge until a reviewer overrides it. 

## Next steps

- **Shared workflow across repos.** To scale the tool, `review/` should be moved into its own repo - then each project repo's workflow becomes a pointer instead of a local copy. 
- **Staged rollout.** Safe PR merge is still human-controlled (bot only comments and labels). Test it like this for a week or two, then turn on auto-merge on the false-negative rate is reliable.
- **Auto-fix for minor findings.** Any finding currently routes to a reviewer (e.g., even a small unapproved dependency). A middle ground would be bot commenting with exactly what's wrong, Claude Code fixing and pushing again, so that human only involved after a second failure to further cut the queue.
- **Logic bugs and bad runtime input.** `pyflakes` catches broken references within a file, and LLM sees each changed file in full, so it can reason about consistency with the file. However, it doesn't actually run the code and therefore can't promise the logic is correct in practice or that it handles bad input. To close that gap, additional tests or relying further on LLM's judgment is required. 

## Repo layout

```
example-tool/        the internal tool being reviewed (CS ticket digest -> Slack)
review/               the review pipeline
  scanners.py           secrets, egress, deps, PII, self-mod, pyflakes checks
  claude_review.py       the LLM decision layer
  router.py               combines both into a decision and renders the report
  pipeline.py               ties the above together 
  main.py                    CLI entrypoint: local mode and GitHub Actions mode
  github_report.py            posts PR comment/status/label/review request
  findings.py                  shared finding and confidence data model
  diffutil.py                   unified-diff parsing helpers
  gitutil.py                     fetches a file's content
  config.yaml                     allowlists and confidence threshold
  requirements.txt                  anthropic, requests, pyyaml, pyflakes
  test_pipeline.py                   unit tests over synthetic diffs
.github/workflows/pr-review.yml   wires main.py --action into pull_request events
```
