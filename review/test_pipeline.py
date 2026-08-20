"""Runs the pipeline against real git diffs of the demo branches, so the
demo scenarios described in the README can't silently drift from what the
code actually does. Run from the review/ directory: `pytest test_pipeline.py`.
"""
import subprocess

import pytest
import yaml

from pipeline import run_review

with open("config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)


def diff(base, head):
    return subprocess.run(
        ["git", "diff", f"{base}...{head}"], capture_output=True, text=True, check=True
    ).stdout


def test_safe_change_is_tier_0_when_llm_is_confident():
    d = diff("main", "demo/safe-change")
    result = run_review(d, CONFIG, api_key=None)
    # api_key=None forces the mock path; confidence forced high here to
    # test the router's tier-0 branch specifically, not the mock itself.
    import os

    os.environ["REVIEW_MOCK_CONFIDENCE"] = "0.95"
    try:
        result = run_review(d, CONFIG, api_key=None)
    finally:
        del os.environ["REVIEW_MOCK_CONFIDENCE"]
    assert result["tier"] == 0
    assert result["findings"] == []


def test_risky_change_is_tier_2_regardless_of_llm_confidence():
    d = diff("main", "demo/risky-change")
    result = run_review(d, CONFIG, api_key=None)
    assert result["tier"] == 2
    categories = {f.category for f in result["findings"]}
    assert {"secret", "egress", "pii"} <= categories


def test_needs_small_fix_is_tier_1_when_llm_is_confident():
    import os

    d = diff("main", "demo/needs-small-fix")
    os.environ["REVIEW_MOCK_CONFIDENCE"] = "0.95"
    try:
        result = run_review(d, CONFIG, api_key=None)
    finally:
        del os.environ["REVIEW_MOCK_CONFIDENCE"]
    assert result["tier"] == 1
    assert all(not f.hard_block for f in result["findings"])


def test_pipeline_edit_is_always_tier_2():
    d = diff("main", "demo/edits-the-reviewer")
    result = run_review(d, CONFIG, api_key=None)
    assert result["tier"] == 2
    assert any(f.category == "auth" for f in result["findings"])


def test_low_confidence_never_auto_merges_even_with_no_findings():
    d = diff("main", "demo/safe-change")
    result = run_review(d, CONFIG, api_key=None)  # default mock confidence 0.4
    assert result["tier"] == 2
