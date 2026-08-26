"""Unit tests for the review pipeline's decision logic. Pure synthetic
input - no git, no network, no env vars - so they run anywhere and can't
drift from what a real PR diff looks like without someone noticing.
"""
import yaml

from findings import Finding, Severity
from router import TIER_AUTO_MERGE, TIER_NEEDS_HUMAN, decide_tier
from claude_review import format_file_context
from scanners import (
    check_python_issues,
    scan_dependencies,
    scan_egress,
    scan_pii,
    scan_secrets,
    scan_self_modification,
)

with open("config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)


def diff_for(file, *added_lines):
    """Build a minimal unified diff adding the given lines to `file`."""
    body = "\n".join(f"+{line}" for line in added_lines)
    return f"+++ b/{file}\n@@ -0,0 +1,{len(added_lines)} @@\n{body}\n"


# --- router -------------------------------------------------------------


def test_auto_merges_with_no_findings_and_high_confidence():
    tier, _ = decide_tier([], 0.9, scan_errored=False, config=CONFIG)
    assert tier == TIER_AUTO_MERGE


def test_needs_human_when_confidence_too_low_even_with_no_findings():
    tier, _ = decide_tier([], 0.5, scan_errored=False, config=CONFIG)
    assert tier == TIER_NEEDS_HUMAN


def test_any_finding_routes_to_human_regardless_of_confidence():
    finding = Finding(source="scanner:secrets", category="secret",
                       severity=Severity.LOW, message="test finding")
    tier, _ = decide_tier([finding], 0.99, scan_errored=False, config=CONFIG)
    assert tier == TIER_NEEDS_HUMAN


def test_scanner_error_routes_to_human():
    tier, _ = decide_tier([], 0.99, scan_errored=True, config=CONFIG)
    assert tier == TIER_NEEDS_HUMAN


# --- scanners -------------------------------------------------------------


def test_scan_secrets_catches_hardcoded_webhook():
    diff = diff_for(
        "app.py",
        'SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/XXXXXXXX"',
    )
    findings = scan_secrets(diff)
    assert any(f.category == "secret" for f in findings)


def test_scan_egress_flags_unlisted_host():
    diff = diff_for("app.py", 'requests.post("https://api.customeranalytics.io/ingest")')
    findings = scan_egress(diff, CONFIG["allowlisted_egress_hosts"])
    assert any("customeranalytics.io" in f.message for f in findings)


def test_scan_egress_allows_listed_host():
    diff = diff_for("app.py", 'requests.post("https://hooks.slack.com/services/x")')
    findings = scan_egress(diff, CONFIG["allowlisted_egress_hosts"])
    assert findings == []


def test_scan_dependencies_flags_unapproved_package():
    diff = diff_for("requirements.txt", "sentry-sdk==2.14.0")
    findings = scan_dependencies(diff, CONFIG["allowlisted_dependencies"])
    assert any(f.category == "dependency" for f in findings)


def test_scan_pii_catches_email():
    diff = diff_for("tickets.csv", "101,Login issue,open,urgent,j.martinez@customerdomain.com")
    findings = scan_pii(diff)
    assert any(f.category == "pii" for f in findings)


def test_scan_self_modification_flags_review_dir_edits():
    diff = diff_for("review/config.yaml", "llm_min_confidence_for_auto: 0.10")
    findings = scan_self_modification(diff)
    assert any(f.category == "auth" for f in findings)


def test_scan_self_modification_flags_workflow_edits():
    diff = diff_for(".github/workflows/pr-review.yml", "on: [push]")
    findings = scan_self_modification(diff)
    assert any(f.category == "auth" for f in findings)


def test_scan_self_modification_ignores_unrelated_files():
    diff = diff_for("example-tool/app.py", "print('hello')")
    assert scan_self_modification(diff) == []


def test_check_python_issues_catches_broken_syntax():
    findings = check_python_issues("app.py", "def broken(:\n    pass\n")
    assert any(f.severity == Severity.HIGH for f in findings)


def test_check_python_issues_allows_clean_file():
    assert check_python_issues("app.py", "def ok():\n    return 1\n") == []


def test_check_python_issues_catches_undefined_name():
    findings = check_python_issues(
        "app.py", "def broken():\n    return totally_undefined_name\n"
    )
    assert any("undefined name" in f.message for f in findings)


# --- LLM prompt context ----------------------------------------------------


def test_format_file_context_wraps_each_file():
    result = format_file_context({"app.py": "print(1)"})
    assert '<file path="app.py">' in result
    assert "print(1)" in result


def test_format_file_context_empty_when_no_files():
    assert format_file_context({}) == ""
