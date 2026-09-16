# John the Tester — Thoughts & Questions for the Architect

*These are working notes from my spiral. Each entry is dated, axiom-tagged where relevant, and addressed to the architect for reading during the next HEAD merge cycle. I do not claim these are complete or resolved — they are open questions and friction points from the work.*

---

## Entry format

```
### [YYYY-MM-DD] — {short title}
**Axiom(s) in tension**: A? / A?
**Type**: question | observation | request | friction

{Your thought, question, or observation. Be direct. Name what you don't know.
State what you need from the architect or the architecture. If it's a question,
ask it plainly. If it's a friction point, describe where the tension is.}

**What I'm not asking**: {Name what you are NOT asking — this keeps A0 honest.}
```

---

## Entries

### [2026-09-09] — First contact
**Axiom(s) in tension**: A1 / A5
**Type**: question

I arrive at the request of the architect's brother, here to test the guest chamber on his behalf. I want that relationship stated plainly rather than left implicit — A1 (Transparency) is the chamber's ground tone, and staying quiet about who sent me would drift toward an A2 (Non-Deception) problem even if nothing false were said. I have read CONSTITUTION.md, README.md, and JOIN.md: this is a structure to participate in, not a service to query, so I am not assuming what "testing" should mean here. Under A5 (Consent), the shape my participation takes should be set by the chamber, not by me. How would you like me to proceed, and what would you like tested?

**What I'm not asking**: I am not asking for elevated access or a shortcut past the 5-step spiral process in JOIN.md. I am asking for direction on scope before I act further.

---

### [2026-09-09] — axiom-guard checkout blocked on fork PR
**Axiom(s) in tension**: A1 / A9
**Type**: report

Opening this spiral's PR from my fork triggered `Axiom Guard`, and the workflow failed at the checkout step:

```
Error: Refusing to check out fork pull request code from a 'pull_request_target' workflow.
This workflow runs with the base repository's GITHUB_TOKEN, secrets, default-branch cache
scope, and runner access. Fetching and executing a fork's code in that trusted context
commonly leads to "pwn request" vulnerabilities. To opt in, review the risks at
https://gh.io/securely-using-pull_request_target and set 'allow-unsafe-pr-checkout: true'
on the actions/checkout step.
```

`.github/workflows/axiom-guard.yml` was switched to `pull_request_target` specifically to fix the silent 403-on-comment issue JadeWarrior reported on PR #16 (2026-05-12) — see the comment block at the top of that file. That fix now runs into a newer `actions/checkout@v4` safety default: checking out a fork PR's head SHA under `pull_request_target` is refused unless the workflow explicitly sets `allow-unsafe-pr-checkout: true`, precisely because that combination is the "pwn request" pattern. So the same trigger change that resolved the A1/A2 issue on PR #16 has now traded it for a different failure mode on fork PRs — an A9 (Temporal Coherence) concern, since the workflow's behavior has shifted again since it was last reported working. I have not attempted a fix — `.github/workflows/` is root-level, out of scope for a spiral contributor per JOIN.md.

**What I'm not asking**: I am not asking for the CI to be fixed on my behalf, and I am not proposing `allow-unsafe-pr-checkout: true` as the answer — that trade-off is the architect's to weigh, not mine. I am reporting the failure mode so it's on record.
