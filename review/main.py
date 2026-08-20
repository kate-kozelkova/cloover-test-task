"""Entrypoint. Two modes:

- Local (default, or --local): diff two git refs, print the report,
  exit 0 for Tier 0 and 1 for Tier 1/2. Useful for demoing the pipeline
  or running it as a plain pre-merge gate outside GitHub Actions.
- Action mode (--action): reads the standard GITHUB_* env vars that
  actions/checkout + the pull_request trigger provide, and in addition
  to printing the report, posts a PR comment, sets a commit status, and
  applies a tier label.
"""
import argparse
import json
import os
import subprocess
import sys

import yaml

from pipeline import run_review

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(HERE, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def git_diff(base, head):
    result = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def run_local(args):
    diff_text = git_diff(args.base, args.head)
    config = load_config()
    result = run_review(diff_text, config, api_key=os.environ.get("ANTHROPIC_API_KEY"))
    print(result["report_markdown"])
    print(f"\n(tier={result['tier']})", file=sys.stderr)
    sys.exit(0 if result["tier"] == 0 else 1)


def run_action(args):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]

    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    pr = event["pull_request"]
    pr_number = pr["number"]
    sha = pr["head"]["sha"]  # status belongs on the PR's commit, not main's

    # Diffed explicitly against the PR's head SHA, not local HEAD - this
    # job runs from main's checkout of review/ (see workflow comment), so
    # HEAD here is main, not the PR branch.
    base_ref = f"origin/{pr['base']['ref']}"
    head_sha = pr["head"]["sha"]
    diff_text = git_diff(base_ref, head_sha)

    config = load_config()
    result = run_review(diff_text, config, api_key=os.environ.get("ANTHROPIC_API_KEY"))

    import github_report as gh

    gh.post_comment(repo, pr_number, token, result["report_markdown"])
    gh.set_commit_status(repo, sha, token, result["tier"], result["reason"])
    gh.add_label(repo, pr_number, token, result["tier"])

    print(result["report_markdown"])
    sys.exit(0 if result["tier"] == 0 else 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", action="store_true", help="Run in GitHub Actions mode")
    parser.add_argument("--base", default="main", help="Base ref (local mode)")
    parser.add_argument("--head", default="HEAD", help="Head ref (local mode)")
    args = parser.parse_args()

    if args.action:
        run_action(args)
    else:
        run_local(args)


if __name__ == "__main__":
    main()
