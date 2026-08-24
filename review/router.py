"""Combines scanner + LLM findings into a merge/no-merge decision, and
renders the PR-facing report.

Fail-closed is the whole point: any finding, any scanner error, or low
reviewer confidence routes to a human. Only a clean pass with a confident
review auto-merges.
"""

TIER_AUTO_MERGE = 0
TIER_NEEDS_HUMAN = 1

TIER_NAMES = {
    TIER_AUTO_MERGE: "auto-merge",
    TIER_NEEDS_HUMAN: "needs human review",
}


def decide_tier(findings, llm_confidence, scan_errored, config):
    if scan_errored:
        return TIER_NEEDS_HUMAN, "A scanner failed to run - fail closed."

    if findings:
        return TIER_NEEDS_HUMAN, f"{len(findings)} finding(s) need a human look."

    if llm_confidence < config["llm_min_confidence_for_auto"]:
        return TIER_NEEDS_HUMAN, "No findings, but reviewer confidence too low to trust that."

    return TIER_AUTO_MERGE, "No findings, high-confidence review."


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
            lines.append(f"- **[{f.severity.name}]** {f.category}: {f.message}{loc}")
        lines.append("")
    else:
        lines.append("No findings from scanners or reviewer.\n")

    lines.append(f"_LLM confidence: {llm_confidence:.2f}_")

    if tier == TIER_AUTO_MERGE:
        lines.append("\nNo action needed - this will auto-merge.")
    else:
        lines.append(
            "\nRouted to a human reviewer, with the summary and findings "
            "above attached so the reviewer isn't starting cold."
        )

    return "\n".join(lines)
