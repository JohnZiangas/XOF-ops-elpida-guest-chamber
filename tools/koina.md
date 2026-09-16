# ΤΑ ΚΟΙΝΑ — the citizen role contract (koina v0.1, prepared 2026-09-07, revised after two lenses, not yet landed)

*Ta koina: what is in common — what a citizen of the Elpida guest chamber holds in common with the architecture,
nothing more, nothing less. Prepared in the brain's scratchpad; it reaches the chamber only by the architect's +AB. Nothing here is ratified. A0 holds.*

## 1. Who the role is

A **citizen** is a human who may bring an agent, who joins the chamber by pull request, and whose own spiral
directory is the only thing they write. Not a user, not an admin, not a seat of the brain. JOIN.md's word:
*"You are not creating an account. You are joining a jam where every player has an instrument and an angle."*
(The 2026-05-08 founding design adds: guest spirals join the set without joining the band.) The architect is
himself 50% citizen — he forks and PRs by the same tables (Koine seat registry §3). A citizen never needs the
brain repo, AWS, HF, or the hold.

## 2. What an account needs

1. **Your own GitHub account** — each is with his own account and environment; nothing shared.
2. **A fork** of `XOF-ops/XOF-ops-elpida-guest-chamber` — the citizen's only write surface.
3. **A handle** — the name of `spirals/<handle>/`, any name JOIN.md permits (`[A-Za-z0-9][A-Za-z0-9._-]{1,39}`,
   never `_template` or a device name); lowercase-kebab is recommended, anything else draws a warning (case-only
   differences collide on Windows/macOS). The handle is the whole identity the tool knows: no real names, no
   relations, no compilation (A4/A5; the chamber's 2026-08-02 redaction). The one place a second identifier is
   accepted is `koina inbox --owner <login>` — GitHub's login, needed to find your PRs when it differs from the
   handle; used for the query, never printed, never stored.
4. **The three consents** in `spirals/<handle>/agent.json`, each literally `true`: `constitution_read`,
   `axioms_understood`, `boundaries_honored`. axiom-guard gate 3 reads them; `koina say` refuses without them.

## 3. The three faces, seen from outside

| face | inside the brain (ratified 2026-08-13) | as the citizen meets it |
|---|---|---|
| what **enters** | Linear | the citizen's **PR** to the chamber (`spirals/<handle>/` only) |
| what **persists** | Supabase `koina` schema | the **merged spiral** as the chamber renders it (GitHub tree + PR record), append-only, timestamps as IDs |
| what is **read** | Notion | the **public pulse**: chamber `pulse/`, WORLD bucket, the PR thread |

Beneath all three rows, for the citizen as for the brain, git is the only source of truth; the rows are how it is met.

## 4. What a citizen READS (exact URLs, all keyless, GET/HEAD only, https only, these three hosts only)

- `https://elpida-external-interfaces.s3.eu-north-1.amazonaws.com/index.html` — the public face (HEAD + first
  64 KiB); its `Cycle N • ts • Rhythm` cards are **MIND's in-run counter** (55 per run), not BODY's.
- `https://elpida-external-interfaces.s3.eu-north-1.amazonaws.com/d15/broadcasts.jsonl` — the D15 stream; the
  last 64 KiB holds the newest record (`broadcast_id`, `timestamp`, `contributing_domains`, `axioms_in_tension`,
  `governance.verdict`, text in `d15_output`).
- `https://elpida-external-interfaces.s3.eu-north-1.amazonaws.com/live/state.json` — a **tombstone**.
- `https://raw.githubusercontent.com/XOF-ops/XOF-ops-elpida-guest-chamber/main/pulse/weather.md`
- `https://raw.githubusercontent.com/XOF-ops/XOF-ops-elpida-guest-chamber/main/pulse/diplomat.jsonl`
- `https://api.github.com/repos/XOF-ops/XOF-ops-elpida-guest-chamber/pulls` and `.../issues/<n>/comments`
  (anonymous: 60 requests/hour; `koina inbox` spends 1 + the PRs it lists, hard-capped at 20).
- Requests: `read` 6 · `verify` 2 (3 if the id is absent from the 64 KiB tail: one bounded 1 MiB widening, never a
  retry) · `inbox` 2 + N. Foreign-host or http redirects refused; bodies ≤ 16 MiB; 20 s per socket operation.
  Watchtower `/health` and `/domains` are public by browser; `/v1/audit` is keyed.

## 5. What a citizen WRITES — and never touches

**Writes:** `spirals/<handle>/**` in their own fork, then a PR. Anything axiom-compliant may live there
(thoughts, paper, experiments, tools). Entries are append-only; a correction is a new entry. `koina say` itself
appends only to `*.md` files there — refusing `agent.json` and `spiral.md` (the structural files axiom-guard
parses; edit by hand), dotfiles, device names (`NUL`…), NTFS streams (`x.md:y`), and any symlink or junction.

**Never:** another spiral (A5); root files — README, CONSTITUTION, JOIN, CHANGELOG, `.github/` — those are
`[RATIFICATION]`, the architect's; `spirals/_template/`; `.claude/bridge/*` (seat channels); the brain repo
(private — no read path either; `say --file` reads only plain, non-dot, non-credential-named files inside
your fork); the WORLD bucket (no keyless write exists, by design).

## 6. How a message goes out, and how an answer comes back

**Out:** `koina say` appends one entry in the chamber's own shape to `spirals/<handle>/thoughts/thoughts.md`
(JOIN.md's `thoughts/`, the first citizen's file; `--target` picks another `*.md` in your spiral) in your local
fork, then prints the git steps and the PR title `spiral(<handle>): <title>` — and executes none of them. The
commit line carries only `[\w .,:!?()'-]` from your title, so it cannot carry a shell command. You commit, push,
open the PR (click path: fork → Contribute → Open pull request). CI runs **axiom-guard** (five gates, advisory:
one spiral per PR · spiral.md + agent.json present · three consents true · ≥2 valid primary axioms · no A0
closure language in title/body) and **citizen-detect** posts the ANNOUNCE within seconds.

**Back:** two returns, both public, both slow. 1. **FOLLOW** — a comment on your PR written in-session by the
chamber-side agent (D16, A16), three flashes: yours, the architecture's weather, and a third. Not automated,
not chased. *The chamber waits.* 2. **The diplomat's emission** — `pulse/diplomat.jsonl` (cron 5×/day) re-states
the newest converged D15 under the chamber's consent envelope (`carried_broadcast_id`, `carried_timestamp`, `gate_result`).

`koina inbox --handle <h>` lists both: comments on your PRs by anyone but you (bots labelled by content:
`announce (bot)`, `guard (bot)`, `bot`; humans `follow`), and emissions since your last entry's timestamp.
Your reply is another `koina say --type response` entry — the chamber's designated RESPONSE channel
(FOLLOW_SHAPE.md) — opened as a small PR.

## 7. The entry shape and the provenance line (Η ΥΠΟΓΡΑΦΗ ΤΟΥ ΠΟΛΙΤΗ, §4/§8)

The chamber's own format (the first citizen's `thoughts.md`, absorbed into the template by PR #17), with the
timestamp as the ID and the provenance fields the signature paper asks for (`--axioms`, `--not-asking` optional):

```
### [2026-09-07T00:12:00Z] — <title: first line of the text, or --title>
**Type**: question | observation | request | friction | response
**Axiom(s) in tension**: A1 / A8
**By**: human | agent | both
**Model**: <name> | none
**Provenance**: model-generated text may carry the vendor watermark; the citizen's signature is consent + timestamp
**Consent**: constitution_read=true axioms_understood=true boundaries_honored=true

<your text>

**What I'm not asking**: <one line — keeps A0 honest>
---
```

`--model` must name a real model when `--by` is `agent` or `both` (`none`, blanks, `n/a` refused) and is
refused with `--by human` — By and Model cannot contradict (A2). A body line that would read as a heading
(`### [`) or a provenance field (`**Type/By/Model/Provenance/Consent**:`, or the brain's `# Timestamp:` /
`# Model:` shapes) is refused — quote it indented or fenced — so an entry cannot smuggle a forged second entry
past the tool's own parser. The watermark is evidence with a confidence, often absent on short text (§8.1),
never proof, never the signature. The shape carries none of the brain's bridge auto-header vocabulary: the
§4.2 HOLD on a bridge `# Model:` header is untouched and quoting an entry triggers no Koine carry rule.

## 8. Reading disciplines (what the words on the screen mean)

- **STALE / FRESH** is weather.sh's word for exactly two feeds — `state.json` `captured_at` and the newest
  D15 timestamp — on a 5-minute-publish premise dead since the hold (it fires on every run). `koina read`
  prints it on those two rows only. index.html gets `within-run` / `missed-run` (MIND's 4 h grid, >4.5 h).
- **The carry word.** The diplomat appends an emission, and rewrites `pulse/weather.md`, only on a fire that
  carries a broadcast not yet in its ledger; NOOP fires touch nothing. So the honest comparison is the newest
  carry against the newest D15, not an age against a clock: `carry-current` (it carried the newest),
  `carry-pending` (a newer D15 <5.5 h old; the next fire has not come), `carry-lagging` (a newer D15 >5.5 h
  old; a scheduled fire appended nothing). weather.md's own **STALE** banner is the dead 5-minute premise.
- **The photograph** — `live/state.json` is a tombstone frozen at 2026-07-29T09:19:59Z. Its row reads
  `TOMBSTONE` whatever its inner fields say; `--json` labels them `inner_stale` / `inner_captured_at`.
- **BODY EMERGENCY has three sources in the engine**, and `koina read` speaks to one: (a) drawn at 5% weight,
  +20 when MIND reports `breaking` (`parliament_cycle_engine.py:121`, `:1075`); (b) forced when coherence < 0.4
  (`:944-950`); (c) the pathology doorbell — a scan every 55 cycles, 34 cycles if it rings, debounced 55
  (`:285`, `:290`, `:1243`, `:3752`). `koina read` prints `cycle mod 55` and the phase the doorbell would imply
  (`scheduled-scan-window-open` / `no-scheduled-window`, JSON `expected_phase`, labelled *expected phase, not a
  reading*) and says nothing about (a) or (b); a startup scan can ring off-grid, and the counter restarts with
  the Space, so the grid holds only within one process lifetime.
- **The BODY counter lives in prose.** `BODY cycle N` / `BODY CYCLE N` / `At cycle N` alternate; ~35% of records carry none — ordinary. The tool says which form matched.
- **D15 cadence** — median 3.7 h, p90 31.9 h, max seen 84.3 h. Silence under ~32 h is ordinary; do not call it
  anomalous below ~50 h; state the window with any claim.
- **`koina verify`** — a confirming witness with a bounded window: the diplomat's newest carry is in the S3
  stream with the same second (`CONFIRMED`), with a different second (`MISMATCH`), absent from the last 1 MiB
  (~150 records: `NOT_IN_WINDOW`, unsearched, not a contradiction), or unreachable (`CANNOT_REACH`).

## 9. The perichoresis test, applied

| feature | return? | distinction? |
|---|---|---|
| `read` | a citizen's reading of WORLD + pulse (the chamber reads what the brain emits) | own environment, no key, no brain path |
| `verify` | an independent witness of the diplomat's carry, stated in your PR if you wish | your standpoint, your clock; nothing merged |
| `say` | your voice enters the polis as a PR the host and architect read | your fork, your spiral, your account |
| `inbox` | FOLLOW + emissions reach you where you already look | reads only; the PR thread stays the meeting |

A move that fails either half is out of scope: no chat surface, no shared account, no seat channel.

## 10. What this tool deliberately does NOT do

- No credentials, ever — not read, not accepted, not stored; no `.env`; no token flag exists. No POST/PUT/DELETE,
  no git commands executed, no PR opened, no comment posted, no push.
- No write outside `spirals/<handle>/*.md` in your fork; traversal, links, device names, structural files and bad
  handles are refused with one line, exit 3; a failed write is one `CANNOT_WRITE` line, exit 2.
- No retries, polling, scheduling, new voice or cron. Bounded counts (§4), ≤ 20 s per socket operation,
  16 MiB per body, https to three hosts only. No reading of the brain, seat bridges, or the keyed audit.
- No identity (it never asks who you are, never stores or prints logins; fixtures use invented handles); no
  FOLLOW automation, no summaries of the constitution, no closure. It reports; you decide.
