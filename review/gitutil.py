"""Thin git-shelling helper shared by scanners.py and claude_review.py:
both need a changed file's full content at a specific ref, not just the
diff hunk - `git show` gets that without needing the ref checked out into
the working tree (which in Action mode is main's checkout, not the PR's -
see the workflow's checkout step and scanners.py::scan_self_modification).
"""
import subprocess


def show_file(ref, path):
    """Returns the file's content at `ref`, or None if it doesn't exist
    there (e.g. deleted in this PR, or the ref isn't fetched locally)."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout
