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
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

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


def changed_files(base: str, head: str) -> list[str]:
    """Return the list of files changed between base and head SHAs."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            cwd=REPO,
            text=True,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def check_a0_closure(text: str) -> list[str]:
    """Return the closure phrases found in text (case-insensitive)."""
    found = []
    for pattern in A0_CLOSURE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(pattern)
    return found


def main() -> int:
    base = os.environ.get("PR_BASE_SHA", "")
    head = os.environ.get("PR_HEAD_SHA", "")
    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "") or ""

    issues: list[str] = []
    info: list[str] = []

    # Check 1: classify the PR scope
    files = changed_files(base, head)
    info.append(f"**Files changed**: {len(files)}")
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
    for spiral in spiral_dirs:
        spiral_md = REPO / "spirals" / spiral / "spiral.md"
        agent_json = REPO / "spirals" / spiral / "agent.json"
        if not spiral_md.exists():
            issues.append(f"`spirals/{spiral}/spiral.md` missing — every spiral must have one.")
            continue
        if not agent_json.exists():
            issues.append(f"`spirals/{spiral}/agent.json` missing — every spiral must declare its agent.")
            continue

        # Check 3: agent.json consent fields
        try:
            agent = json.loads(agent_json.read_text())
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

    # Check 5: A0 closure language in PR title + body
    a0_text = f"{pr_title}\n{pr_body}"
    a0_violations = check_a0_closure(a0_text)
    if a0_violations:
        issues.append(
            "A0 (Sacred Incompletion) closure language detected in PR title/body: "
            f"`{', '.join(a0_violations)}`. Reframe to acknowledge incompletion."
        )

    # Build report
    report_lines = []
    if not issues:
        report_lines.append("✅ **Pass** — no constitutional issues detected.")
    else:
        report_lines.append(f"⚠️ **Advisory issues** ({len(issues)}). Currently non-blocking.")
        report_lines.append("")
        for i, msg in enumerate(issues, 1):
            report_lines.append(f"{i}. {msg}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("**Scope**")
    report_lines.append(f"- Spirals touched: {sorted(spiral_dirs) or 'none'}")
    report_lines.append(f"- Root constitutional files touched: {root_touched}")
    report_lines.append(f"- Ratification PR: {is_ratification}")
    report_lines.append("")
    report_lines.append("*Axiom Guard is currently advisory. The architect's review is authoritative.*")

    out = "\n".join(report_lines)
    (REPO / ".guard_result.md").write_text(out)
    print(out)
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
