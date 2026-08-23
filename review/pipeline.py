"""Ties scanners + LLM + router together. Kept separate from main.py so it
has no GitHub-specific I/O and can be run/tested locally or in CI the same
way.
"""
from claude_review import review_with_claude
from findings import Severity
from router import decide_tier, render_report
from scanners import run_all_scanners


def run_review(diff_text, config, api_key=None):
    scan_errored = False
    scanner_findings = []
    try:
        scanner_findings = run_all_scanners(diff_text, config)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see below
        # A scanner crashing is not "no findings" - it's an unknown, and
        # unknowns fail closed to a human, same as a real finding would.
        scan_errored = True
        scanner_findings = []
        llm_findings, llm_confidence, llm_summary = [], 0.0, f"Scanner error: {exc}"
    else:
        try:
            llm_findings, llm_confidence, llm_summary = review_with_claude(
                diff_text, scanner_findings, api_key=api_key
            )
        except Exception as exc:  # noqa: BLE001 - same fail-closed logic as scanners
            # An API/network failure isn't "no findings" either - it's an
            # unknown, and it should never crash the whole check. Treat it
            # like a scanner error: zero confidence, routes to a human.
            llm_findings, llm_confidence = [], 0.0
            llm_summary = f"LLM review failed to run: {exc}"

    all_findings = scanner_findings + llm_findings
    tier, reason = decide_tier(all_findings, llm_confidence, scan_errored, config)
    report = render_report(tier, reason, all_findings, llm_summary, llm_confidence)

    return {
        "tier": tier,
        "reason": reason,
        "findings": all_findings,
        "confidence": llm_confidence,
        "report_markdown": report,
        "max_severity": max((f.severity for f in all_findings), default=Severity.NONE),
    }
