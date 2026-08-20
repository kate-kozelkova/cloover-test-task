"""Combines scanner + LLM findings into one of three outcomes, and renders
the PR-facing report.

Fail-closed is the whole point of this module: anything that isn't
confidently safe drops to a human, it never defaults up to auto-merge.
"""
from findings import Severity

TIER_AUTO_MERGE = 0  # nothing found, high confidence -> merge, no human
TIER_AUTO_FIX_LOOP = 1  # minor issues -> bot comments, builder's Claude Code fixes
TIER_NEEDS_HUMAN = 2  # hard-block category, high severity, or low confidence

TIER_NAMES = {
    TIER_AUTO_MERGE: "Tier 0 - auto-merge",
    TIER_AUTO_FIX_LOOP: "Tier 1 - needs fixes (automated)",
    TIER_NEEDS_HUMAN: "Tier 2 - needs human review",
}


def decide_tier(findings, llm_confidence, scan_errored, config):
    if scan_errored:
        return TIER_NEEDS_HUMAN, "A scanner failed to run - fail closed."

    if any(f.hard_block for f in findings):
        return TIER_NEEDS_HUMAN, "A hard-block category (secret/egress/pii/auth) was flagged."

    if not findings:
        if llm_confidence >= config["llm_min_confidence_for_auto"]:
            return TIER_AUTO_MERGE, "No findings, high-confidence review."
        return TIER_NEEDS_HUMAN, "No findings, but reviewer confidence too low to trust that."

    max_severity = max(f.severity for f in findings)
    tier1_ceiling = Severity[config["tier1_max_severity"]]

    if max_severity > tier1_ceiling:
        return TIER_NEEDS_HUMAN, f"Highest finding severity ({max_severity.name}) exceeds the auto-fix ceiling."

    if llm_confidence < config["llm_min_confidence_for_auto"]:
        return TIER_NEEDS_HUMAN, "Reviewer confidence too low to trust an automated fix loop."

    return TIER_AUTO_FIX_LOOP, "Only low/medium, non-blocking findings, high confidence."


def render_report(tier, reason, findings, llm_summary, llm_confidence):
    lines = [f"## Automated PR review - {TIER_NAMES[tier]}", "", reason, ""]

    if llm_summary:
        lines += ["**Reviewer summary:**", llm_summary, ""]

    if findings:
        lines.append("**Findings:**")
        for f in sorted(findings, key=lambda x: -x.severity):
            if f.file and f.line is not None:
                loc = f" (`{f.file}:{f.line}`)"
            elif f.file:
                loc = f" (`{f.file}`)"
            else:
                loc = ""
            block = " 🚫 hard-block" if f.hard_block else ""
            lines.append(f"- **[{f.severity.name}]** {f.category}{block}: {f.message}{loc}")
        lines.append("")
    else:
        lines.append("No findings from scanners or reviewer.\n")

    lines.append(f"_LLM confidence: {llm_confidence:.2f}_")

    if tier == TIER_AUTO_MERGE:
        lines.append("\n✅ No action needed - this will auto-merge.")
    elif tier == TIER_AUTO_FIX_LOOP:
        lines.append(
            "\n🔧 Please address the findings above (ask your Claude Code "
            "session to fix them) and push again - this will be re-reviewed "
            "automatically. No need to ping a human unless it fails twice."
        )
    else:
        lines.append(
            "\n🧑‍💻 Routed to a human reviewer. You don't need to do "
            "anything else right now - this PR is now in the review queue "
            "with the summary above attached, so the reviewer isn't "
            "starting cold."
        )

    return "\n".join(lines)
