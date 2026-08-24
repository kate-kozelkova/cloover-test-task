"""GitHub-side effects for Action mode: PR comment, commit status, label.

Isolated from pipeline.py on purpose - the review logic doesn't need to
know it's running in GitHub Actions, and this module doesn't need to know
how a verdict was reached.
"""
import requests

API = "https://api.github.com"

TIER_LABELS = {
    0: "review:auto-merge",
    1: "review:needs-human",
}

TIER_STATUS_STATE = {
    0: "success",
    1: "failure",
}


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def post_comment(repo, pr_number, token, body):
    url = f"{API}/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.post(url, headers=_headers(token), json={"body": body}, timeout=15)
    resp.raise_for_status()


def set_commit_status(repo, sha, token, tier, description):
    url = f"{API}/repos/{repo}/statuses/{sha}"
    payload = {
        "state": TIER_STATUS_STATE[tier],
        "description": description[:140],
        "context": "pr-review/data-safety",
    }
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    resp.raise_for_status()


def add_label(repo, pr_number, token, tier):
    url = f"{API}/repos/{repo}/issues/{pr_number}/labels"
    resp = requests.post(
        url, headers=_headers(token), json={"labels": [TIER_LABELS[tier]]}, timeout=15
    )
    resp.raise_for_status()
