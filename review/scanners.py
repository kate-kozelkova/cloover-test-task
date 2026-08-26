"""Deterministic, non-LLM checks for the categories where we want a hard
guarantee rather than a judgment call: secrets, egress, dependencies, PII.

These run first, are cheap, and never call out to a network (other than
the PR diff already being local). If a scanner itself errors, that's
treated as a finding upstream - fail closed, never silent.
"""
import ast
import re
import subprocess

from findings import Finding, Severity
from diffutil import changed_files, iter_added_lines

PROTECTED_PREFIXES = ("review/", ".github/workflows/")

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
                )
            )
    return findings


def scan_self_modification(diff_text):
    """A PR that edits the review pipeline itself (scanners, config,
    workflow) could weaken or disable its own gate. Always routed to a
    human, regardless of how safe the change looks - the pipeline that
    runs is main's trusted copy (see the workflow's checkout step), not
    this PR's own, so it can flag edits to itself without being able to
    approve them away."""
    findings = []
    for file in changed_files(diff_text):
        if file.startswith(PROTECTED_PREFIXES):
            findings.append(
                Finding(
                    source="scanner:self-modification",
                    category="auth",
                    severity=Severity.HIGH,
                    message="This PR modifies the review pipeline itself "
                    "- always routed to a human, never self-approved.",
                    file=file,
                )
            )
    return findings


def check_python_syntax(filename, content):
    """Pure check: does `content` parse as valid Python? An unparseable
    file will crash the instant it's imported or run - this is the one
    slice of "does it crash" we can guarantee deterministically, as
    opposed to logic bugs or bad runtime input, which need either tests
    (conditional on the builder having written one) or judgment (Claude's
    opportunistic review) - no static check can promise those."""
    try:
        ast.parse(content, filename=filename)
    except SyntaxError as exc:
        return Finding(
            source="scanner:syntax",
            category="correctness",
            severity=Severity.HIGH,
            message=f"Syntax error: {exc.msg} - this file would crash "
            "immediately on import, before any of its logic runs.",
            file=filename,
            line=exc.lineno,
        )
    return None


def scan_syntax_errors(diff_text, head_ref):
    """Thin git-shelling wrapper around check_python_syntax. Needs each
    changed file's full content, not just the diff hunk, so it reads the
    PR's actual version via `git show` rather than trusting the working
    tree - in Action mode the working tree is main's checkout, not the
    PR's (see the workflow's checkout step and scan_self_modification)."""
    findings = []
    if not head_ref:
        return findings
    for file in changed_files(diff_text):
        if not file.endswith(".py"):
            continue
        result = subprocess.run(
            ["git", "show", f"{head_ref}:{file}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue  # file was deleted in this PR - nothing to parse
        finding = check_python_syntax(file, result.stdout)
        if finding:
            findings.append(finding)
    return findings


def run_all_scanners(diff_text, config, head_ref=None):
    findings = []
    findings += scan_self_modification(diff_text)
    findings += scan_secrets(diff_text)
    findings += scan_egress(diff_text, config["allowlisted_egress_hosts"])
    findings += scan_dependencies(diff_text, config["allowlisted_dependencies"])
    findings += scan_pii(diff_text)
    findings += scan_syntax_errors(diff_text, head_ref)
    return findings
