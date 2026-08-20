"""Deterministic, non-LLM checks for the categories where we want a hard
guarantee rather than a judgment call: secrets, egress, dependencies, PII.

These run first, are cheap, and never call out to a network (other than
the PR diff already being local). If a scanner itself errors, that's
treated as a HIGH-severity finding upstream - fail closed, never silent.
"""
import re

from findings import Finding, Severity
from diffutil import iter_added_lines

SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*"
            r"['\"][A-Za-z0-9/_\-\.]{12,}['\"]"
        ),
    ),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    (
        "private_key_block",
        re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
    ),
    (
        "hardcoded_slack_webhook",
        re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9/]+"),
    ),
]

URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")

DEP_FILES = {"requirements.txt", "requirements-dev.txt"}


def scan_secrets(diff_text):
    findings = []
    for file, line, content in iter_added_lines(diff_text):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(
                    Finding(
                        source="scanner:secrets",
                        category="secret",
                        severity=Severity.HIGH,
                        message=f"Looks like a hardcoded credential ({name}).",
                        file=file,
                        line=line,
                        hard_block=True,
                    )
                )
    return findings


def scan_egress(diff_text, allowlisted_hosts):
    findings = []
    allow = set(allowlisted_hosts)
    for file, line, content in iter_added_lines(diff_text):
        for host in URL_RE.findall(content):
            host = host.lower()
            if host in allow or any(host.endswith("." + a) for a in allow):
                continue
            if host in ("localhost", "127.0.0.1"):
                continue
            findings.append(
                Finding(
                    source="scanner:egress",
                    category="egress",
                    severity=Severity.HIGH,
                    message=f"New outbound call to '{host}', which is not "
                    "on the approved egress list.",
                    file=file,
                    line=line,
                    hard_block=True,
                )
            )
    return findings


def scan_dependencies(diff_text, allowlisted_deps):
    findings = []
    allow = {d.lower() for d in allowlisted_deps}
    for file, line, content in iter_added_lines(diff_text):
        base = file.rsplit("/", 1)[-1]
        if base not in DEP_FILES:
            continue
        pkg = re.split(r"[=<>~!\[; ]", content.strip())[0].strip().lower()
        if not pkg:
            continue
        if pkg not in allow:
            findings.append(
                Finding(
                    source="scanner:dependencies",
                    category="dependency",
                    severity=Severity.MEDIUM,
                    message=f"New dependency '{pkg}' is not on the "
                    "approved list - unreviewed third-party code with "
                    "full access to whatever the tool touches.",
                    file=file,
                    line=line,
                    hard_block=False,
                )
            )
    return findings


def scan_pii(diff_text):
    findings = []
    for file, line, content in iter_added_lines(diff_text):
        if EMAIL_RE.search(content):
            findings.append(
                Finding(
                    source="scanner:pii",
                    category="pii",
                    severity=Severity.MEDIUM,
                    message="Email address in a new line - confirm this "
                    "is fixture/test data, not real customer data.",
                    file=file,
                    line=line,
                    hard_block=True,
                )
            )
        if SSN_RE.search(content) or CARD_RE.search(content):
            findings.append(
                Finding(
                    source="scanner:pii",
                    category="pii",
                    severity=Severity.HIGH,
                    message="Pattern resembling an SSN or card number.",
                    file=file,
                    line=line,
                    hard_block=True,
                )
            )
    return findings


def run_all_scanners(diff_text, config):
    findings = []
    findings += scan_secrets(diff_text)
    findings += scan_egress(diff_text, config["allowlisted_egress_hosts"])
    findings += scan_dependencies(diff_text, config["allowlisted_dependencies"])
    findings += scan_pii(diff_text)
    return findings
