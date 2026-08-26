"""Minimal unified-diff parser: yields only added lines, with file + line number.

We only ever scan *added* lines. Removing a secret isn't a risk; the
review pipeline cares about what's newly introduced.
"""
import re

_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def iter_added_lines(diff_text):
    current_file = None
    current_line = None
    for raw in diff_text.splitlines():
        m = _FILE_RE.match(raw)
        if m:
            current_file = m.group(1)
            continue
        m = _HUNK_RE.match(raw)
        if m:
            current_line = int(m.group(1))
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            if current_file is not None and current_line is not None:
                yield current_file, current_line, raw[1:]
                current_line += 1
        elif raw.startswith("-"):
            continue
        else:
            if current_line is not None:
                current_line += 1


def changed_files(diff_text):
    return sorted({f for f, _, _ in iter_added_lines(diff_text)})
