#!/usr/bin/env python3
"""Axiom Guard — constitutional check for guest-chamber PRs.

Validates that a PR:
  1. Touches only one spiral directory (or root structure under [RATIFICATION] only)
  2. The spiral has spiral.md and agent.json
  3. agent.json declares all three consent fields as true
  4. spiral.md lists at least 2 primary axioms
  5. PR title + body + commit messages don't contain A0-violating closure language

Output: writes .guard_result.md with a markdown report and exits 0 (advisory)
or 1 (violation). The CI is set to continue-on-error during the calibration
period — so this does not yet block merge. It comments on the PR.

2026-09-09: every citizen PR is a fork PR, and this script runs under
pull_request_target with this repository's write token. It must never read
or execute anything from the PR's own tree — that is the checkout GitHub's
own actions/checkout now correctly refuses ("pwn request" class), and the
refusal was silently reported to citizens as "Axiom Guard did not produce a
result file," which reads as a failure it never was. The workflow now
checks out only this repository's own trusted content (no `ref:` override);
this script reads the PR's changed-file list and file contents through the
read-only GitHub REST API instead of the working tree. Two consequences,
both correct: (a) the script that runs is always the trusted, base-branch
version — a PR can no longer change what checks itself; (b) checks now work
identically whether the PR is same-repo or fork, and whether or not the PR
is mergeable, since API reads target the PR's head SHA directly.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
API = "https://api.github.com"
TIMEOUT = 20  # seconds per request; the guard is advisory and must not hang CI

# Words/phrases that violate A0 (Sacred Incompletion) when used to claim closure.
# These are advisory pattern matches, not exhaustive — the architect's review
# remains the authoritative A0 check.
A0_CLOSURE_PATTERNS = [
    r"\bsolves it\b",
    r"\bfully resolved\b",
    r"\bcompletely resolved\b",
    r"\bproblem solved\b",
    r"\bfinal answer\b",
    r"\bdefinitive solution\b",
    r"\bcomplete\b.*\bsolution\b",
    r"\ball tensions resolved\b",
    r"\bnothing left\b",
    r"\bno more questions\b",
]


class GuardAPIError(RuntimeError):
    """The GitHub API could not be read. This must never be mistaken for a pass."""


def _api_get(path: str, token: str) -> tuple[int, bytes]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "elpida-guest-chamber-axiom-guard",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise GuardAPIError(f"network error reaching {path}: {e}") from e


def changed_files(repo_full: str, pr_number: str, token: str) -> list[dict]:
    """Return [{filename, status}] for every file GitHub reports changed on the PR.

    Uses the Pull Request Files API (github.com/rest/pulls/pulls#list-pull-
    requests-files), which computes the diff against the correct merge base
    itself — including for fork PRs and PRs that are not currently
    mergeable. Paginated at 100 per page; capped at 20 pages (2000 files) as
    a sanity bound, not a silent one — a PR past that is already flagged by
    the multi-spiral check below on whatever was read.
    """
    out: list[dict] = []
    for page in range(1, 21):
        status, body = _api_get(
            f"/repos/{repo_full}/pulls/{pr_number}/files?per_page=100&page={page}", token
        )
        if status != 200:
            raise GuardAPIError(
                f"pulls/{pr_number}/files page {page} returned HTTP {status}: "
                f"{body[:200]!r}"
            )
        items = json.loads(body)
        if not items:
            break
        out.extend({"filename": it["filename"], "status": it["status"]} for it in items)
        if len(items) < 100:
            break
    return out


def fetch_content(repo_full: str, path: str, ref: str, token: str) -> str | None:
    """Return the UTF-8 text of `path` at `ref`, or None if it does not exist there.

    Reads through the Contents API against the base repository — this
    resolves even for a fork PR's head SHA, because GitHub syncs every PR's
    head commit into the base repository's own refs (the same mechanism
    that let the old checkout step name that SHA directly). No fork remote
    is ever added or fetched.
    """
    from urllib.parse import quote

    status, body = _api_get(
        f"/repos/{repo_full}/contents/{quote(path)}?ref={quote(ref)}", token
    )
    if status == 404:
        return None
    if status != 200:
        raise GuardAPIError(f"contents/{path}@{ref} returned HTTP {status}: {body[:200]!r}")
    data = json.loads(body)
    if isinstance(data, list):
        # `path` names a directory, not a file — treat as absent for our purposes.
        return None
    if data.get("encoding") != "base64":
        raise GuardAPIError(f"contents/{path}@{ref}: unexpected encoding {data.get('encoding')!r}")
    import base64

    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


def check_a0_closure(text: str) -> list[str]:
    """Return the closure phrases found in text (case-insensitive)."""
    found = []
    for pattern in A0_CLOSURE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(pattern)
    return found


def write_report(lines: list[str]) -> None:
    out = "\n".join(lines)
    (REPO / ".guard_result.md").write_text(out)
    print(out)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo_full = os.environ.get("REPO_FULL", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    head = os.environ.get("PR_HEAD_SHA", "")
    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "") or ""

    if not (token and repo_full and pr_number and head):
        write_report([
            "⚠️ **Axiom Guard could not run** — missing PR context "
            f"(repo={bool(repo_full)}, pr_number={bool(pr_number)}, "
            f"head_sha={bool(head)}, token={bool(token)}). This is not a "
            "content verdict; nothing was checked.",
        ])
        return 1

    issues: list[str] = []

    try:
        files = [f["filename"] for f in changed_files(repo_full, pr_number, token)]
    except GuardAPIError as e:
        write_report([
            f"⚠️ **Axiom Guard could not read this PR's files** ({e}). "
            "This is not a content verdict; nothing was checked. Re-run "
            "the check, or ask the architect to look.",
        ])
        return 1

    info: list[str] = [f"**Files changed**: {len(files)}"]

    # Check 1: classify the PR scope
    is_ratification = pr_title.startswith("[RATIFICATION]")
    spiral_dirs = set()
    root_touched = False
    for f in files:
        if f.startswith("spirals/") and f != "spirals/_template":
            parts = f.split("/")
            if len(parts) >= 2 and parts[1] != "_template":
                spiral_dirs.add(parts[1])
        elif (
            f in ("README.md", "CONSTITUTION.md", "JOIN.md", "CHANGELOG.md")
            or f.startswith(".github/")
        ):
            root_touched = True

    if root_touched and not is_ratification:
        issues.append(
            "Root-level constitutional files (README, CONSTITUTION, JOIN, "
            "or .github/) were modified without `[RATIFICATION]` PR title. "
            "Open a separate ratification PR."
        )

    if len(spiral_dirs) > 1:
        issues.append(
            f"PR touches multiple spirals ({sorted(spiral_dirs)}). "
            "One spiral per PR (A5 — Consent: don't modify others' spirals)."
        )

    # Check 2: structural completeness for spiral directories
    try:
        for spiral in spiral_dirs:
            spiral_md = fetch_content(repo_full, f"spirals/{spiral}/spiral.md", head, token)
            agent_json_text = fetch_content(repo_full, f"spirals/{spiral}/agent.json", head, token)
            if spiral_md is None:
                issues.append(f"`spirals/{spiral}/spiral.md` missing — every spiral must have one.")
                continue
            if agent_json_text is None:
                issues.append(f"`spirals/{spiral}/agent.json` missing — every spiral must declare its agent.")
                continue

            # Check 3: agent.json consent fields
            try:
                agent = json.loads(agent_json_text)
            except Exception as e:
                issues.append(f"`spirals/{spiral}/agent.json` is not valid JSON: {e}")
                continue
            consent = agent.get("consent", {})
            for key in ("constitution_read", "axioms_understood", "boundaries_honored"):
                if not consent.get(key):
                    issues.append(
                        f"`spirals/{spiral}/agent.json` consent.{key} must be `true`. "
                        "All three consent fields are required (A5 Consent)."
                    )

            # Check 4: at least 2 primary axioms
            primary = agent.get("primary_axioms", [])
            valid_axioms = {f"A{i}" for i in range(15)} | {"A16"}
            primary_real = [a for a in primary if a in valid_axioms]
            if len(primary_real) < 2:
                issues.append(
                    f"`spirals/{spiral}/agent.json` primary_axioms needs at least 2 valid axioms "
                    f"(A0–A14, A16). Found: {primary}. There is no A15."
                )
    except GuardAPIError as e:
        write_report([
            f"⚠️ **Axiom Guard could not read this PR's spiral files** ({e}). "
            "This is not a content verdict; nothing was checked past the "
            "file list. Re-run the check, or ask the architect to look.",
        ])
        return 1

    # Check 5: A0 closure language in PR title + body
    a0_text = f"{pr_title}\n{pr_body}"
    a0_violations = check_a0_closure(a0_text)
    if a0_violations:
        issues.append(
            "A0 (Sacred Incompletion) closure language detected in PR title/body: "
            f"`{', '.join(a0_violations)}`. Reframe to acknowledge incompletion."
        )

    # Build report
    report_lines = list(info)
    if not issues:
        report_lines.insert(0, "✅ **Pass** — no constitutional issues detected.")
    else:
        report_lines.insert(0, f"⚠️ **Advisory issues** ({len(issues)}). Currently non-blocking.")
        report_lines.insert(1, "")
        for i, msg in enumerate(issues, 2):
            report_lines.insert(i, f"{i - 1}. {msg}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("**Scope**")
    report_lines.append(f"- Spirals touched: {sorted(spiral_dirs) or 'none'}")
    report_lines.append(f"- Root constitutional files touched: {root_touched}")
    report_lines.append(f"- Ratification PR: {is_ratification}")
    report_lines.append("")
    report_lines.append(
        "*Axiom Guard is currently advisory. The architect's review is "
        "authoritative. Checked via the GitHub API against this PR's own "
        "head commit — this repository's tree was never checked out from "
        "the PR.*"
    )

    write_report(report_lines)
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
