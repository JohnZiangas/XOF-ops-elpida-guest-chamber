#!/usr/bin/env python3
"""koina — ΤΑ ΚΟΙΝΑ for the citizen role of the Elpida guest chamber.

CONTRACT (the whole of it):
  1. Keyless. No AWS, HF, or GitHub token is read, asked for, or accepted.
  2. Read-only on the network: GET/HEAD only, https only, three known hosts only
     (redirects elsewhere are refused), no retries, per-socket-operation timeout
     <= 20 s, body cap 16 MiB, User-Agent "koina/0.1 (+chamber citizen client)".
     Requests per subcommand: read = 6 (index HEAD + Range GET, d15, state,
     weather, diplomat); verify = 2 or 3 (diplomat, d15 64 KiB tail, one bounded
     1 MiB widening if the id is absent — a second request, never a retry);
     inbox = 2 + N (pulls, N <= --max-prs <= 20 comment pages, diplomat).
  3. Reads come only from the designed public pipelines: the WORLD bucket
     (index.html, d15/broadcasts.jsonl, live/state.json) and the public chamber
     repo (pulse/weather.md, pulse/diplomat.jsonl, PR comments via api.github.com).
  4. Writes go to exactly one place: spirals/<handle>/<something>.md inside the
     citizen's OWN fork. Never root, never another spiral, never agent.json or
     spiral.md, never through a symlink or junction, never the brain.
  5. Time is the ID: every entry heading carries a UTC ISO-8601 Z timestamp;
     append-only. Entries follow the chamber's own shape (### [ts] — title,
     **Type**, provenance fields, body, **What I'm not asking**).
  6. Provenance on every entry: By (human|agent|both), Model (a real name for
     agent|both, `none` for human), the watermark note, and the three consents
     read from the spiral's agent.json. A body line that would forge a heading or
     a provenance field is refused, so the tool's own parser cannot be poisoned.
  7. The tool prepares; the human sends. It prints git steps and a PR title and
     executes none of them. Answers return as FOLLOW comments on the citizen's PR
     and as the diplomat's public emissions — `inbox` lists both.
  8. Honesty words on every reading: STALE/FRESH only where weather.sh applies
     them (state.json captured_at, newest D15); TOMBSTONE for live/state.json;
     within-run/missed-run for index.html against MIND's 4 h grid; a carry word
     (carry-current/carry-pending/carry-lagging) for the diplomat and weather.md
     against the newest D15; D15 cadence (median 3.7 h, p90 31.9 h); and
     "expected phase, not a reading" for BODY (doorbell case only).
  9. Fails closed: any unreachable source prints one clear line, exit != 0.
 10. Never compiles identities: a citizen is a handle. `inbox --owner` is the one
     place a second identifier is accepted (GitHub's own login, for the query);
     it is not printed and not stored.
Subcommands: read | verify | say | inbox   (--json on each; say has --dry-run)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

__version__ = "0.1"

# --------------------------------------------------------------------------- #
# Public surfaces (the only network addresses this tool knows)
# --------------------------------------------------------------------------- #
WORLD = "https://elpida-external-interfaces.s3.eu-north-1.amazonaws.com"
URL_INDEX = f"{WORLD}/index.html"
URL_D15 = f"{WORLD}/d15/broadcasts.jsonl"
URL_STATE = f"{WORLD}/live/state.json"

CHAMBER_REPO = "XOF-ops/XOF-ops-elpida-guest-chamber"
CHAMBER_HTML = f"https://github.com/{CHAMBER_REPO}"
CHAMBER_RAW = f"https://raw.githubusercontent.com/{CHAMBER_REPO}/main"
URL_WEATHER = f"{CHAMBER_RAW}/pulse/weather.md"
URL_DIPLOMAT = f"{CHAMBER_RAW}/pulse/diplomat.jsonl"
CHAMBER_API = f"https://api.github.com/repos/{CHAMBER_REPO}"

ALLOWED_HOSTS = frozenset({
    urllib.parse.urlsplit(WORLD).hostname,
    "raw.githubusercontent.com",
    "api.github.com",
})

USER_AGENT = "koina/0.1 (+chamber citizen client)"
MAX_TIMEOUT_S = 20        # per socket operation (urllib semantics), not per request
TIMEOUT_S = 20
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_PRS_CAP = 20

# weather.sh: STALE_THRESHOLD_S=600 — applied by weather.sh to exactly two feeds
# (state.json captured_at, broadcasts.jsonl last timestamp) on a 5-min-publish
# premise that no longer holds; koina applies it to those two rows only.
STALE_THRESHOLD_S = 600
# MIND: EventBridge every 4 h -> index.html rewritten per run
MIND_RUN_H, MIND_MISSED_H = 4.0, 4.5
# diplomat.yml cron '24 0,5,10,14,19 * * *' -> longest scheduled gap 5 h
DIPLOMAT_FIRES_PER_DAY, DIPLOMAT_MAX_GAP_H, DIPLOMAT_LAG_H = 5, 5.0, 5.5
# D15 cadence calibration (178 broadcasts, 2026-05-28 -> 2026-08-19)
D15_MEDIAN_H, D15_P90_H, D15_ELEVATED_H, D15_MAX_H = 3.7, 31.9, 50.0, 84.3
# parliament_cycle_engine.py:285/:290 — pathology scan every 55 cycles; window 34
BODY_SCAN_INTERVAL, BODY_EMERGENCY_WINDOW = 55, 34
PHASE_CAVEAT = ("doorbell case only — EMERGENCY can also be drawn (5% weight, +20 when MIND "
                "reports breaking; engine :121/:1075) or forced by coherence < 0.4 (:944-950), "
                "and a startup scan can ring off-grid (:1272-1284); none of that is visible from "
                "the stream, and the counter restarts with the Space")

TAIL_BYTES = 64 * 1024
WIDE_TAIL_BYTES = 1024 * 1024
HEAD_BYTES = 64 * 1024

# JOIN.md permits any directory name under spirals/ except _template; axiom_guard
# accepts the same. koina accepts that shape and only WARNS when it is not
# lowercase-kebab. fullmatch: a trailing newline cannot pass.
HANDLE_RE = re.compile(r"(?!_)[A-Za-z0-9][A-Za-z0-9._-]{1,39}")
HANDLE_KEBAB_RE = re.compile(r"[a-z0-9-]{2,40}")
OWNER_RE = re.compile(r"[A-Za-z0-9-]{1,39}")
PATH_PART_RE = re.compile(r"[\w.\-]+")
WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)})
STRUCTURAL_FILES = frozenset({"agent.json", "spiral.md"})
SENSITIVE_NAME_TOKENS = frozenset({"env", "pem", "key", "keys", "netrc", "credential", "credentials",
                                   "secret", "secrets", "token", "tokens", "rsa", "ed25519", "passwd",
                                   "password", "passwords"})
CONSENT_KEYS = ("constitution_read", "axioms_understood", "boundaries_honored")
VALID_AXIOMS = {f"A{i}" for i in range(15)} | {"A16"}
ENTRY_TYPES = ("question", "observation", "request", "friction", "response")
MODEL_NONE_WORDS = frozenset({"none", "n/a", "na", "-", "unknown", "null", "nil", ""})
# same advisory list as .github/scripts/axiom_guard.py (gate 5) — pre-flight only
A0_CLOSURE_PATTERNS = [
    r"\bsolves it\b", r"\bfully resolved\b", r"\bcompletely resolved\b",
    r"\bproblem solved\b", r"\bfinal answer\b", r"\bdefinitive solution\b",
    r"\bcomplete\b.*\bsolution\b", r"\ball tensions resolved\b",
    r"\bnothing left\b", r"\bno more questions\b",
]
BODY_CYCLE_PRIMARY = re.compile(r"\bBODY\s+cycle\s*#?\s*(\d+)", re.IGNORECASE)
BODY_CYCLE_FALLBACK = re.compile(r"\bcycle\s+#?(\d+)\b", re.IGNORECASE)
INDEX_CARD_RE = re.compile(
    r"Cycle\s+(\d+)\s*•\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*•\s*Rhythm:\s*([A-Z_]+)"
)
WEATHER_HEADER_RE = re.compile(r"^## chamber weather — observed (\S+)", re.MULTILINE)
# the chamber's own entry heading: "### [<timestamp>] — <title>"
ENTRY_HEAD_RE = re.compile(r"^\s{0,3}###\s*\[([^\]\n]+)\]\s*[—-]\s*(.*)$")
ENTRY_TYPE_RE = re.compile(r"^\s{0,3}\*\*Type\*\*\s*:", re.IGNORECASE)
# a body line that would read as a heading or a provenance field is refused (A2)
FORGED_LINE_RE = re.compile(
    r"^\s{0,3}(?:###\s*\["
    r"|\*\*(?:Type|By|Model|Provenance|Consent|Axiom\(s\) in tension|What I'm not asking)\*\*\s*:"
    r"|#\s*(?:Timestamp|By|Model|Provenance|Consent)\s*:)",
    re.IGNORECASE)
TITLE_KEEP_RE = re.compile(r"[^\w .,:!?()'\-]")   # what may appear in a title / commit line

PROVENANCE_LINE = (
    "model-generated text may carry the vendor watermark; "
    "the citizen's signature is consent + timestamp"
)


# --------------------------------------------------------------------------- #
# Errors and the single network seam
# --------------------------------------------------------------------------- #
class KoinaError(Exception):
    """A refusal or an unreachable source. Message is the one clear line."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


class Response:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.body = body


def check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https":
        raise KoinaError(f"REFUSED {url}: https only", 3)
    if u.hostname not in ALLOWED_HOSTS:
        raise KoinaError(f"REFUSED {url}: not one of the known public surfaces", 3)


class _RedirectFence(urllib.request.HTTPRedirectHandler):
    """urllib follows 3xx to any scheme/host by default; koina follows only https to known hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_RedirectFence)


def _http_urllib(method: str, url: str, headers: dict | None = None) -> Response:
    if method not in ("GET", "HEAD"):
        raise KoinaError(f"REFUSED {method} {url}: koina only reads (GET/HEAD)", 3)
    check_url(url)
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "*/*")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:  # noqa: S310 (https, GET/HEAD, fenced hosts)
            body = b"" if method == "HEAD" else r.read(MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES:
                raise KoinaError(f"CANNOT_REACH {url}: body over the {MAX_BODY_BYTES} byte cap", 2)
            return Response(r.status, dict(r.headers.items()), body)
    except urllib.error.HTTPError as e:
        hdrs = dict(e.headers.items()) if e.headers else {}
        if e.code in (403, 429) and "x-ratelimit-remaining" in {k.lower() for k in hdrs}:
            reset = hdrs.get("X-RateLimit-Reset") or hdrs.get("x-ratelimit-reset") or "?"
            raise KoinaError(
                f"CANNOT_REACH {url}: GitHub anonymous rate limit hit (HTTP {e.code}); "
                f"resets at epoch {reset}. Wait; koina does not retry.", 2) from None
        raise KoinaError(f"CANNOT_REACH {url}: HTTP {e.code}", 2) from None
    except urllib.error.URLError as e:
        raise KoinaError(f"CANNOT_REACH {url}: {e.reason}", 2) from None
    except (TimeoutError, OSError) as e:
        raise KoinaError(f"CANNOT_REACH {url}: {e}", 2) from None


http = _http_urllib  # tests monkeypatch koina.http; fetch() resolves it at call time


def fetch(method: str, url: str, headers: dict | None = None) -> Response:
    return http(method, url, headers)


# --------------------------------------------------------------------------- #
# Time helpers (UTC everywhere; time is the ID)
# --------------------------------------------------------------------------- #
UTC = _dt.timezone.utc


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(UTC).replace(microsecond=0)


def iso_z(dt: _dt.datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str | None) -> _dt.datetime | None:
    """ISO-8601 (with Z, offset, fractional, or naive=UTC) and RFC-1123 headers."""
    if not s:
        return None
    s = s.strip()
    try:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S GMT", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return _dt.datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def age_seconds(ts: _dt.datetime | None, now: _dt.datetime) -> float | None:
    return None if ts is None else (now - ts).total_seconds()


def hours(sec: float | None) -> float | None:
    return None if sec is None else round(sec / 3600.0, 1)


def freshness_word(age_s: float | None, threshold_s: int = STALE_THRESHOLD_S) -> str:
    """weather.sh's two-feed word: > 600 s since the last write => STALE."""
    if age_s is None:
        return "UNKNOWN"
    return "FRESH" if age_s <= threshold_s else "STALE"


def mind_run_word(age_s: float | None) -> str:
    """index.html against MIND's 4 h EventBridge grid."""
    if age_s is None:
        return "unknown"
    return "within-run" if age_s <= MIND_MISSED_H * 3600 else "missed-run"


def d15_cadence_word(age_h: float | None) -> str:
    if age_h is None:
        return "unknown"
    if age_h <= D15_P90_H:
        return "ordinary"
    if age_h <= D15_ELEVATED_H:
        return "elevated"
    if age_h <= D15_MAX_H:
        return "anomalous"
    return "beyond-max"


def carry_word(carried_id: str | None, newest_id: str | None, newest_age_s: float | None) -> str:
    """The diplomat (and weather.md, which it rewrites) move only on a fire that carries a
    broadcast not yet in its ledger; NOOP fires append nothing. So the honest comparison is
    the newest carry against the newest D15, not the emission's age against a clock."""
    if not carried_id or not newest_id or newest_age_s is None:
        return "unknown"
    if carried_id == newest_id:
        return "carry-current"
    if newest_age_s <= DIPLOMAT_LAG_H * 3600:
        return "carry-pending"
    return "carry-lagging"


# --------------------------------------------------------------------------- #
# Parsers (pure; all tested offline)
# --------------------------------------------------------------------------- #
def parse_body_cycle(text: str | None) -> tuple[int | None, str | None]:
    """Both phrasings, case-insensitive. Returns (cycle, form) or (None, None)."""
    if not text:
        return None, None
    m = BODY_CYCLE_PRIMARY.search(text)
    if m:
        return int(m.group(1)), "BODY cycle N"
    m = BODY_CYCLE_FALLBACK.search(text)
    if m:
        return int(m.group(1)), "cycle N (fallback)"
    return None, None


def expected_body_phase(cycle: int) -> dict:
    """Expected phase, not a reading: scheduled scan every 55, doorbell window 34 cycles."""
    m = cycle % BODY_SCAN_INTERVAL
    last_scan = cycle - m
    inside = m < BODY_EMERGENCY_WINDOW
    return {
        "cycle": cycle,
        "mod": m,
        "last_scan_cycle": last_scan,
        "next_scan_cycle": last_scan + BODY_SCAN_INTERVAL,
        "expected_phase": "scheduled-scan-window-open" if inside else "no-scheduled-window",
        "label": "expected phase, not a reading",
        "caveat": PHASE_CAVEAT,
    }


def phase_line(cycle: int) -> str:
    p = expected_body_phase(cycle)
    if p["expected_phase"] == "scheduled-scan-window-open":
        why = (f"inside the {BODY_EMERGENCY_WINDOW}-cycle window the scheduled scan at cycle "
               f"{p['last_scan_cycle']} would open IF it rang the doorbell")
    else:
        why = (f"past the {BODY_EMERGENCY_WINDOW}-cycle window a scan at cycle "
               f"{p['last_scan_cycle']} could have opened; next scheduled scan at {p['next_scan_cycle']}")
    return (f"BODY phase ({p['label']}): cycle {cycle} mod {BODY_SCAN_INTERVAL} = {p['mod']} "
            f"-> {p['expected_phase']} — {why}. ({PHASE_CAVEAT}.)")


def split_jsonl_tail(body: bytes, partial_first: bool) -> list[dict]:
    lines = body.split(b"\n")
    if partial_first and lines:
        lines = lines[1:]
    recs = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(obj, dict):
            recs.append(obj)
    return recs


def norm_broadcast(rec: dict) -> dict:
    gov = rec.get("governance") if isinstance(rec.get("governance"), dict) else {}
    text = rec.get("d15_output")
    if not isinstance(text, str):
        text = rec.get("text") if isinstance(rec.get("text"), str) else ""
    cycle, form = parse_body_cycle(text)
    return {
        "id": rec.get("broadcast_id") or rec.get("id"),
        "timestamp": rec.get("timestamp"),
        "contributing_domains": rec.get("contributing_domains"),
        "axioms_in_tension": rec.get("axioms_in_tension"),
        "verdict": gov.get("verdict", rec.get("verdict")),
        "approval_rate": gov.get("approval_rate", rec.get("approval_rate")),
        "body_cycle": cycle,
        "body_cycle_form": form,
        "text_excerpt": " ".join(text.split())[:160] if text else "",
    }


def parse_index_head(html: str) -> dict:
    m = INDEX_CARD_RE.search(html)
    total = re.search(r'<div class="stat-val">(\d+)</div>\s*<div class="stat-label">Total Broadcasts', html)
    out = {
        "first_card": None,
        "template": "MIND (Cycle-cards)" if m else "BODY (no Cycle cards)",
        "total_broadcasts_stat": int(total.group(1)) if total else None,
    }
    if m:
        out["first_card"] = {"mind_cycle_in_run": int(m.group(1)),
                             "timestamp": m.group(2), "rhythm": m.group(3)}
    return out


def describe_state(state: dict) -> dict:
    """Inner fields of live/state.json are the photograph's own claims — labelled inner_*."""
    note = state.get("note") if isinstance(state.get("note"), str) else ""
    return {
        "tombstone": bool(state.get("tombstone")),
        "inner_stale": bool(state.get("stale")),
        "inner_captured_at": state.get("captured_at"),
        "frozen_since": state.get("frozen_since"),
        "note": " ".join(note.split())[:140],
    }


def parse_weather_header(md: str) -> dict:
    m = WEATHER_HEADER_RE.search(md)
    return {"observed": m.group(1) if m else None, "stale_banner": "**STALE**" in md}


def newest_diplomat(body: bytes) -> dict | None:
    recs = split_jsonl_tail(body, partial_first=False)
    recs = [r for r in recs if r.get("kind") == "diplomat_out_breath"] or recs
    return recs[-1] if recs else None


def last_entry_timestamp(path: Path) -> str | None:
    """The newest entry heading '### [<ts>] — <title>' that is followed (within two lines)
    by a '**Type**:' line. A heading-shaped line without that pair is not an entry."""
    if not path.exists() or not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    found = None
    for i, line in enumerate(lines):
        m = ENTRY_HEAD_RE.match(line)
        if not m:
            continue
        if any(ENTRY_TYPE_RE.match(nxt) for nxt in lines[i + 1:i + 3]):
            found = m.group(1).strip()
    return found


# --------------------------------------------------------------------------- #
# Network readers (one request each)
# --------------------------------------------------------------------------- #
def get_range(url: str, rng: str) -> tuple[bytes, bool, int | None]:
    """Returns (body, partial_first_line, total_size). Accepts 200 (range ignored)."""
    r = fetch("GET", url, {"Range": f"bytes={rng}"})
    if r.status == 206:
        cr = r.headers.get("content-range", "")
        m = re.match(r"bytes (\d+)-(\d+)/(\d+)", cr)
        start = int(m.group(1)) if m else 0
        total = int(m.group(3)) if m else None
        return r.body, start > 0, total
    return r.body, False, len(r.body)


def read_d15_tail(nbytes: int = TAIL_BYTES) -> tuple[list[dict], int | None, str | None]:
    body, partial, total = get_range(URL_D15, f"-{nbytes}")
    hdr_lm = None
    return split_jsonl_tail(body, partial), total, hdr_lm


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #
def cmd_read(now: _dt.datetime) -> tuple[dict, int]:
    out: dict = {"now": iso_z(now), "sources": {}, "errors": []}

    # 1. WORLD index.html — HEAD for Last-Modified, first 64 KiB for the first card
    try:
        h = fetch("HEAD", URL_INDEX)
        lm = parse_ts(h.headers.get("last-modified"))
        body, _, _ = get_range(URL_INDEX, f"0-{HEAD_BYTES - 1}")
        info = parse_index_head(body.decode("utf-8", errors="replace"))
        a = age_seconds(lm, now)
        out["sources"]["index"] = {"url": URL_INDEX, "ok": True, "last_modified": iso_z(lm) if lm else None,
                                   "age_hours": hours(a), "cadence": mind_run_word(a),
                                   "cadence_rule": f"MIND runs every {MIND_RUN_H:g} h; > {MIND_MISSED_H} h = missed-run",
                                   "content_length": h.headers.get("content-length"), **info}
    except KoinaError as e:
        out["sources"]["index"] = {"url": URL_INDEX, "ok": False}
        out["errors"].append(str(e))

    # 2. WORLD d15/broadcasts.jsonl — last 64 KiB
    newest_id, newest_age = None, None
    try:
        recs, total, _ = read_d15_tail()
        if not recs:
            raise KoinaError(f"CANNOT_REACH {URL_D15}: tail held no complete record", 2)
        newest = norm_broadcast(recs[-1])
        with_counter = None
        for r in reversed(recs):
            n = norm_broadcast(r)
            if n["body_cycle"] is not None:
                with_counter = n
                break
        ts = parse_ts(newest["timestamp"])
        a = age_seconds(ts, now)
        newest_id, newest_age = newest["id"], a
        d15 = {"url": URL_D15, "ok": True, "tail_bytes": TAIL_BYTES, "total_bytes": total,
               "records_in_tail": len(recs), "newest": newest, "age_hours": hours(a),
               "freshness": freshness_word(a), "cadence": d15_cadence_word(hours(a)),
               "newest_with_body_counter": None, "body_phase": None}
        if with_counter is not None:
            wts = parse_ts(with_counter["timestamp"])
            d15["newest_with_body_counter"] = {**with_counter,
                                               "age_hours": hours(age_seconds(wts, now))}
            d15["body_phase"] = expected_body_phase(with_counter["body_cycle"])
        out["sources"]["d15"] = d15
    except KoinaError as e:
        out["sources"]["d15"] = {"url": URL_D15, "ok": False}
        out["errors"].append(str(e))

    # 3. WORLD live/state.json — the tombstone
    try:
        r = fetch("GET", URL_STATE)
        state = json.loads(r.body.decode("utf-8", errors="replace"))
        lm = parse_ts(r.headers.get("last-modified"))
        d = describe_state(state if isinstance(state, dict) else {})
        cap = parse_ts(d.get("inner_captured_at"))
        a = age_seconds(cap, now)
        out["sources"]["state"] = {"url": URL_STATE, "ok": True, **d,
                                   "last_modified": iso_z(lm) if lm else None,
                                   "inner_captured_age_hours": hours(a),
                                   "freshness": "TOMBSTONE" if d["tombstone"] else freshness_word(a)}
    except (KoinaError, ValueError) as e:
        out["sources"]["state"] = {"url": URL_STATE, "ok": False}
        out["errors"].append(str(e) if isinstance(e, KoinaError) else f"CANNOT_REACH {URL_STATE}: not JSON")

    # 4. chamber pulse/weather.md header (rewritten by the diplomat fire that carries a new broadcast)
    try:
        r = fetch("GET", URL_WEATHER)
        w = parse_weather_header(r.body.decode("utf-8", errors="replace"))
        ots = parse_ts(w["observed"])
        a = age_seconds(ots, now)
        out["sources"]["weather"] = {"url": URL_WEATHER, "ok": True, **w, "age_hours": hours(a)}
    except KoinaError as e:
        out["sources"]["weather"] = {"url": URL_WEATHER, "ok": False}
        out["errors"].append(str(e))

    # 5. chamber pulse/diplomat.jsonl newest emission
    try:
        r = fetch("GET", URL_DIPLOMAT)
        d = newest_diplomat(r.body)
        if d is None:
            raise KoinaError(f"CANNOT_REACH {URL_DIPLOMAT}: no record parsed", 2)
        ets = parse_ts(d.get("emitted_at") or d.get("timestamp"))
        a = age_seconds(ets, now)
        consent = d.get("consent") if isinstance(d.get("consent"), dict) else {}
        carry = carry_word(d.get("carried_broadcast_id"), newest_id, newest_age)
        out["sources"]["diplomat"] = {
            "url": URL_DIPLOMAT, "ok": True, "emitted_at": d.get("emitted_at") or d.get("timestamp"),
            "carried_broadcast_id": d.get("carried_broadcast_id"),
            "carried_timestamp": d.get("carried_timestamp"),
            "converged_axiom": d.get("converged_axiom"),
            "gate_result": consent.get("gate_result"), "t2_gate_result": consent.get("t2_gate_result"),
            "age_hours": hours(a), "carry": carry,
            "carry_rule": (f"cron {DIPLOMAT_FIRES_PER_DAY}x/day; appends only on a fire that carries a new "
                           f"broadcast; carry-lagging = a D15 newer than the carry is > {DIPLOMAT_LAG_H} h old")}
        if out["sources"]["weather"].get("ok"):
            out["sources"]["weather"]["carry"] = carry
    except KoinaError as e:
        out["sources"]["diplomat"] = {"url": URL_DIPLOMAT, "ok": False}
        out["errors"].append(str(e))

    return out, (2 if out["errors"] else 0)


def render_read(out: dict) -> str:
    s = out["sources"]
    L = [f"koina read — now {out['now']} (ages against now; STALE/FRESH is weather.sh's two-feed >10 min word, "
         f"used on the two rows it was written for; other rows carry their own cadence word)", ""]
    i = s.get("index", {})
    if i.get("ok"):
        card = i.get("first_card")
        cardtxt = (f"Cycle {card['mind_cycle_in_run']} • {card['timestamp']} • Rhythm: {card['rhythm']} "
                   f"(MIND's in-run counter, 55 per run — not BODY's)") if card else "no Cycle card (BODY template)"
        L.append(f"WORLD index.html      {i['cadence']:12} age {i['age_hours']} h  Last-Modified {i['last_modified']}  "
                 f"template {i['template']}  total-stat {i['total_broadcasts_stat']}  (MIND grid {MIND_RUN_H:g} h)")
        L.append(f"  first card: {cardtxt}")
    d = s.get("d15", {})
    if d.get("ok"):
        n = d["newest"]
        L.append(f"WORLD d15 stream      {d['freshness']:12} age {d['age_hours']} h  cadence {d['cadence']} "
                 f"(median {D15_MEDIAN_H} h, p90 {D15_P90_H} h; silence <{D15_P90_H} h is ordinary)")
        L.append(f"  newest: id {n['id']}  ts {n['timestamp']}  domains {n['contributing_domains']}  "
                 f"axioms {n['axioms_in_tension']}  verdict {n['verdict']}  approval {n['approval_rate']}")
        if n["body_cycle"] is not None:
            L.append(f"  BODY cycle in text: {n['body_cycle']} (matched '{n['body_cycle_form']}')")
        else:
            L.append("  BODY cycle in text: none (ordinary — ~35% of records carry no counter; not a regression)")
        w = d.get("newest_with_body_counter")
        if w and w["id"] != n["id"]:
            L.append(f"  newest record WITH a counter: id {w['id']}  ts {w['timestamp']}  age {w['age_hours']} h  "
                     f"BODY cycle {w['body_cycle']} ('{w['body_cycle_form']}')")
        if w:
            L.append("  " + phase_line(w["body_cycle"]))
        else:
            L.append("  BODY phase: no counter visible in this tail — said, not inferred.")
    st = s.get("state", {})
    if st.get("ok"):
        L.append(f"WORLD live/state.json {st['freshness']:12} frozen_since {st['frozen_since']}  "
                 f"inner captured_at {st['inner_captured_at']} ({st['inner_captured_age_hours']} h ago)  "
                 f"Last-Modified {st['last_modified']}")
        if st["tombstone"]:
            L.append("  a frozen photograph: nothing inside it is current (its own stale/captured_at fields included); "
                     "the writer is disabled under the 2026-07-28 hold")
    w = s.get("weather", {})
    if w.get("ok"):
        L.append(f"chamber weather.md    {w.get('carry', 'unknown'):12} observed {w['observed']} ({w['age_hours']} h ago)  "
                 f"STALE-banner={w['stale_banner']}  (rewritten by the diplomat fire that carries a new broadcast; "
                 f"its own STALE banner is weather.sh's dead 5-min premise — read the D15 line for a D15 gap)")
    dp = s.get("diplomat", {})
    if dp.get("ok"):
        L.append(f"chamber diplomat      {dp['carry']:12} emitted {dp['emitted_at']} ({dp['age_hours']} h ago)  "
                 f"carried {dp['carried_broadcast_id']} @ {dp['carried_timestamp']}  axiom {dp['converged_axiom']}  "
                 f"gate {dp['gate_result']} / t2 {dp['t2_gate_result']}  ({dp['carry_rule']})")
    for e in out["errors"]:
        L.append(e)
    L += ["", "where you are: a citizen reading the public pulse (WORLD bucket + chamber repo), keyless.",
          "what you can do: `koina verify` (witness the diplomat's carry) · `koina say` (write your spiral) · "
          "`koina inbox` (what came back)."]
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# verify — the citizen as confirming witness
# --------------------------------------------------------------------------- #
def cmd_verify(now: _dt.datetime) -> tuple[dict, int]:
    try:
        r = fetch("GET", URL_DIPLOMAT)
        d = newest_diplomat(r.body)
        if d is None:
            raise KoinaError(f"CANNOT_REACH {URL_DIPLOMAT}: no record parsed", 2)
        want_id = d.get("carried_broadcast_id")
        want_ts = parse_ts(d.get("carried_timestamp"))
        recs, _, _ = read_d15_tail(TAIL_BYTES)
        found = next((x for x in recs if (x.get("broadcast_id") or x.get("id")) == want_id), None)
        widened = False
        if found is None:
            widened = True  # one wider, bounded request — a different request, not a retry
            recs, _, _ = read_d15_tail(WIDE_TAIL_BYTES)
            found = next((x for x in recs if (x.get("broadcast_id") or x.get("id")) == want_id), None)
    except KoinaError as e:
        return {"now": iso_z(now), "result": "CANNOT_REACH", "reason": str(e)}, 2

    out = {"now": iso_z(now), "diplomat_emitted_at": d.get("emitted_at") or d.get("timestamp"),
           "carried_broadcast_id": want_id, "carried_timestamp": d.get("carried_timestamp"),
           "searched_tail_bytes": WIDE_TAIL_BYTES if widened else TAIL_BYTES}
    if found is None:
        out.update(result="NOT_IN_WINDOW",
                   reason=f"carried_broadcast_id not present in the last {out['searched_tail_bytes']} bytes of the "
                          f"S3 stream — an unsearched window, not a contradiction; older carries fall outside it")
        return out, 1
    have_ts = parse_ts(found.get("timestamp"))
    out["stream_timestamp"] = found.get("timestamp")
    out["stream_axioms_in_tension"] = found.get("axioms_in_tension")
    if want_ts and have_ts and iso_z(want_ts) == iso_z(have_ts):
        out.update(result="CONFIRMED", reason="id present and timestamps agree at second precision")
        return out, 0
    out.update(result="MISMATCH", reason="id present but timestamps differ")
    return out, 1


def render_verify(out: dict) -> str:
    L = [f"koina verify — {out['result']}"]
    if out.get("carried_broadcast_id"):
        L.append(f"  diplomat carried {out['carried_broadcast_id']} @ {out.get('carried_timestamp')} "
                 f"(emitted {out.get('diplomat_emitted_at')})")
    if out.get("stream_timestamp"):
        L.append(f"  S3 stream has it @ {out['stream_timestamp']}  axioms {out.get('stream_axioms_in_tension')}")
    L.append(f"  {out.get('reason')}")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# say — compose an entry in the citizen's own spiral (writes only there)
# --------------------------------------------------------------------------- #
def _is_reserved_name(part: str) -> bool:
    return part.split(".", 1)[0].upper() in WINDOWS_RESERVED


def _is_link(p: Path) -> bool:
    try:
        if p.is_symlink():
            return True
        is_junction = getattr(p, "is_junction", None)
        return bool(is_junction()) if is_junction else False
    except OSError:
        return True


def validate_handle(handle: str) -> str:
    if not HANDLE_RE.fullmatch(handle or "") or _is_reserved_name(handle):
        raise KoinaError(f"REFUSED handle {handle!r}: must be a directory name under spirals/ "
                         f"([A-Za-z0-9][A-Za-z0-9._-]{{1,39}}, not _template, not a reserved name)", 3)
    return handle


def handle_warnings(handle: str) -> list[str]:
    if HANDLE_KEBAB_RE.fullmatch(handle):
        return []
    return [f"handle {handle!r} is not lowercase-kebab ([a-z0-9-]); accepted, but case-only differences "
            f"collide on Windows/macOS — prefer lowercase"]


def _spiral_dir(root: Path, handle: str, require: bool) -> Path:
    """<root>/spirals/<handle> as a real directory: not a symlink, not a junction, resolving to itself."""
    root_r = root.resolve()
    spirals_dir = root_r / "spirals"
    nominal = spirals_dir / handle
    if _is_link(spirals_dir):
        raise KoinaError("REFUSED: spirals/ is a symlink or junction — not a plain fork checkout", 3)
    if _is_link(nominal):
        raise KoinaError(f"REFUSED: spirals/{handle} is a symlink or junction — koina writes only into a real "
                         f"directory of your own spiral (A5)", 3)
    if nominal.exists():
        if not nominal.is_dir():
            raise KoinaError(f"REFUSED: spirals/{handle} is not a directory", 3)
        real = nominal.resolve()
        if real != nominal:
            raise KoinaError(f"REFUSED: spirals/{handle} resolves to {real} — a link or a case mismatch; the handle "
                             f"must be the directory name exactly", 3)
    elif require:
        if not spirals_dir.is_dir():
            raise KoinaError(f"REFUSED: {root_r} has no spirals/ directory — run koina inside your fork of "
                             f"{CHAMBER_REPO}", 3)
        raise KoinaError(f"REFUSED: spirals/{handle}/ not found — copy spirals/_template/ first", 3)
    return nominal


def spiral_target(root: Path, handle: str, target: str, require_spiral: bool = True) -> Path:
    """The only writable path: <root>/spirals/<handle>/<target>, where target is a relative
    *.md path with no traversal, no link in any component, no reserved or structural name."""
    validate_handle(handle)
    if not target or Path(target).is_absolute() or target.startswith(("/", "\\")):
        raise KoinaError(f"REFUSED target {target!r}: must be a relative path inside spirals/{handle}/", 3)
    if "\\" in target or ":" in target:
        raise KoinaError(f"REFUSED target {target!r}: use forward slashes; no drive letters or NTFS streams", 3)
    parts = target.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise KoinaError(f"REFUSED target {target!r}: path traversal", 3)
        if part.startswith(".") or not PATH_PART_RE.fullmatch(part):
            raise KoinaError(f"REFUSED target {target!r}: component {part!r} — no dotfiles, no spaces, no control "
                             f"characters", 3)
        if _is_reserved_name(part):
            raise KoinaError(f"REFUSED target {target!r}: {part!r} is a Windows device name — nothing would persist", 3)
    leaf = parts[-1]
    if leaf.lower() in STRUCTURAL_FILES:
        raise KoinaError(f"REFUSED target {target!r}: structural file — edit it by hand; koina appends only to "
                         f"markdown entries", 3)
    if not leaf.lower().endswith(".md") or len(leaf) < 4:
        raise KoinaError(f"REFUSED target {target!r}: must be a *.md file", 3)
    spiral = _spiral_dir(root, handle, require_spiral)
    cur = spiral
    for part in parts[:-1]:
        cur = cur / part
        if _is_link(cur):
            raise KoinaError(f"REFUSED target {target!r}: {cur.relative_to(spiral).as_posix()} is a symlink or junction", 3)
        if cur.exists() and not cur.is_dir():
            raise KoinaError(f"REFUSED target {target!r}: {cur.relative_to(spiral).as_posix()} is not a directory", 3)
    path = cur / leaf
    if _is_link(path):
        raise KoinaError(f"REFUSED target {target!r}: is a symlink or junction", 3)
    if path.exists():
        if not path.is_file():
            raise KoinaError(f"REFUSED target {target!r}: exists and is not a regular file", 3)
        if path.resolve() != path:
            raise KoinaError(f"REFUSED target {target!r}: resolves to {path.resolve()} — outside the named path", 3)
    return path


def bounded_source_file(root: Path, file_arg: str) -> Path:
    """--file must be a regular, non-dot, non-secret-named file inside the fork, reached through no link."""
    root_r = root.resolve()
    src = Path(file_arg)
    src = (src if src.is_absolute() else Path.cwd() / src)
    try:
        rel = src.resolve().relative_to(root_r)
    except ValueError:
        raise KoinaError(f"REFUSED: --file {file_arg} is outside the fork root {root_r} — koina reads entry text "
                         f"only from inside your fork", 3) from None
    cur = root_r
    for part in rel.parts:
        if part.startswith("."):
            raise KoinaError(f"REFUSED: --file {file_arg}: dotfile/dotdir component {part!r}", 3)
        cur = cur / part
        if _is_link(cur):
            raise KoinaError(f"REFUSED: --file {file_arg}: {part!r} is a symlink or junction", 3)
    tokens = {t.lower() for t in re.split(r"[._\-]+", rel.name) if t}
    if tokens & SENSITIVE_NAME_TOKENS:
        raise KoinaError(f"REFUSED: --file {file_arg}: name looks like a credential file", 3)
    if not cur.is_file():
        raise KoinaError(f"REFUSED: --file {file_arg} not found or not a regular file", 3)
    return cur


def read_consent(spiral_dir: Path, handle: str) -> tuple[dict, list[str]]:
    agent_path = spiral_dir / "agent.json"
    if not agent_path.exists():
        raise KoinaError(f"REFUSED: spirals/{handle}/agent.json not found — copy spirals/_template/ first", 3)
    try:
        agent = json.loads(agent_path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise KoinaError(f"REFUSED: spirals/{handle}/agent.json is not valid JSON: {e}", 3) from None
    except OSError as e:
        raise KoinaError(f"CANNOT_READ spirals/{handle}/agent.json: {e}", 2) from None
    consent = agent.get("consent") if isinstance(agent.get("consent"), dict) else {}
    missing = [k for k in CONSENT_KEYS if consent.get(k) is not True]
    if missing:
        raise KoinaError(f"REFUSED: consent not true in spirals/{handle}/agent.json: {', '.join(missing)} "
                         f"(A5 — all three must be literally true)", 3)
    warnings = []
    if not (spiral_dir / "spiral.md").exists():
        warnings.append("axiom-guard gate 2: spiral.md is missing — the PR will be flagged")
    primary = agent.get("primary_axioms") or []
    if len([a for a in primary if a in VALID_AXIOMS]) < 2:
        warnings.append(f"axiom-guard gate 4: primary_axioms needs >=2 of A0–A14/A16 (found {primary})")
    declared = str(agent.get("handle") or "")
    if declared and declared.lower().replace("_", "-") != handle.lower():
        warnings.append(f"agent.json handle {declared!r} differs from directory {handle!r} (not refused; be consistent)")
    return agent, warnings


def forged_lines(text: str) -> list[int]:
    """1-based line numbers of body lines that would read as an entry heading or provenance field."""
    return [i for i, ln in enumerate(text.splitlines(), 1) if FORGED_LINE_RE.match(ln)]


def clean_title(raw: str, limit: int = 60) -> str:
    first = next((ln for ln in raw.splitlines() if ln.strip()), "").strip()
    first = re.sub(r"^[#>*\-\s]+", "", first)
    first = TITLE_KEEP_RE.sub("", first)
    first = " ".join(first.split())
    return first[:limit].strip() or "entry"


def build_entry(ts: str, title: str, etype: str, by: str, model: str, text: str,
                axioms: str | None = None, not_asking: str | None = None) -> str:
    header = [f"### [{ts}] — {title}", f"**Type**: {etype}"]
    if axioms:
        header.append(f"**Axiom(s) in tension**: {axioms}")
    header += [
        f"**By**: {by}",
        f"**Model**: {model}",
        f"**Provenance**: {PROVENANCE_LINE}",
        "**Consent**: constitution_read=true axioms_understood=true boundaries_honored=true",
    ]
    body = "\n".join(header) + "\n\n" + text.strip("\n") + "\n"
    if not_asking:
        body += f"\n**What I'm not asking**: {' '.join(not_asking.split())}\n"
    return body + "\n---\n"


def pr_title(handle: str, title: str) -> str:
    return f"spiral({handle}): {title}"


def cmd_say(args, now: _dt.datetime) -> tuple[dict, int]:
    handle = validate_handle(args.handle)
    warnings = handle_warnings(handle)
    model = (args.model or "").strip()
    if args.by == "human":
        if model:
            raise KoinaError("REFUSED: --model contradicts --by human (A2 — if a model wrote or co-wrote it, "
                             "say --by agent or --by both)", 3)
        model = "none"
    elif model.lower() in MODEL_NONE_WORDS:
        raise KoinaError("REFUSED: --model must name the model when --by is agent or both (A2 — 'none' and blanks "
                         "are not names)", 3)
    if args.text is not None and args.file is not None:
        raise KoinaError("REFUSED: give --text or --file, not both", 3)
    if args.text is None and args.file is None:
        raise KoinaError("REFUSED: give --text or --file", 3)

    root = Path(args.root or ".").resolve()
    src_rel = None
    if args.file is not None:
        src = bounded_source_file(root, args.file)
        src_rel = src.relative_to(root).as_posix()
        try:
            text = src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise KoinaError(f"REFUSED: --file {args.file}: {e}", 3) from None
    else:
        text = args.text
    if not text.strip():
        raise KoinaError("REFUSED: empty entry", 3)
    bad = forged_lines(text)
    if bad:
        raise KoinaError(f"REFUSED: body line(s) {bad} would read as an entry heading or provenance field "
                         f"(### [...], **Type/By/Model/Provenance/Consent**:, # Timestamp:) — quote them "
                         f"indented or in a code fence (A2)", 3)
    if args.not_asking and (forged_lines(args.not_asking) or "\n" in args.not_asking):
        raise KoinaError("REFUSED: --not-asking must be one plain line (no heading or provenance shapes)", 3)

    path = spiral_target(root, handle, args.target)
    spiral_dir = root / "spirals" / handle
    _, cwarn = read_consent(spiral_dir, handle)
    warnings += cwarn
    for pat in A0_CLOSURE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            warnings.append(f"axiom-guard gate 5 (advisory): A0 closure phrase matches /{pat}/ — reframe")

    ts = iso_z(now)
    title = clean_title(args.title if args.title else text)
    entry = build_entry(ts, title, args.type, args.by, model, text, args.axioms, args.not_asking)
    digest = hashlib.sha256(entry.encode("utf-8")).hexdigest()[:12]
    rel = path.relative_to(root).as_posix()
    ptitle = pr_title(handle, title)

    written = False
    if not args.dry_run:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                prefix = "" if (not existing or existing.endswith("\n")) else "\n"
                if not existing.endswith("\n\n") and existing:
                    prefix += "\n"
                with path.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(prefix + entry)
            else:
                with path.open("w", encoding="utf-8", newline="\n") as f:
                    f.write(f"# {handle} — thoughts\n\n" + entry)
        except OSError as e:
            raise KoinaError(f"CANNOT_WRITE {rel}: {e}", 2) from None
        written = True

    out = {"now": ts, "handle": handle, "type": args.type, "by": args.by, "model": model, "path": rel,
           "source_file": src_rel, "title": title,
           "written": written, "dry_run": bool(args.dry_run), "entry_sha256_12": digest,
           "pr_title": ptitle, "warnings": warnings, "entry": entry,
           "next_steps": [
               f"git add {rel}",
               f'git commit -m "{ptitle}"',
               "git push origin HEAD",
               f"open a PR from your fork to {CHAMBER_REPO} (base: main) titled: {ptitle}",
           ]}
    return out, 0


def render_say(out: dict) -> str:
    L = [f"koina say — {'DRY RUN (nothing written)' if out['dry_run'] else 'appended'} -> {out['path']}",
         f"  timestamp {out['now']}  type {out['type']}  by {out['by']}  model {out['model']}  "
         f"entry sha256[:12] {out['entry_sha256_12']}"]
    if out.get("source_file"):
        L.append(f"  text read from {out['source_file']} (inside your fork)")
    for w in out["warnings"]:
        L.append(f"  warning: {w}")
    L += ["", "--- entry ---", out["entry"].rstrip("\n"), "--- end ---", "",
          "Next steps — yours to run; koina executes none of them:",
          f"  1. git add {out['path']}",
          f"  2. git commit -m \"{out['pr_title']}\"",
          "  3. git push origin HEAD",
          f"  4. Open a pull request from your fork to {CHAMBER_REPO} (base: main)",
          f"     title:  {out['pr_title']}",
          "     click path: GitHub → your fork → \"Contribute\" → \"Open pull request\" (or GitHub Desktop: Commit → Push → Create Pull Request)",
          "  5. CI runs axiom-guard (advisory) and posts the ANNOUNCE; the FOLLOW comes in-session, in its own time.",
          "     Then: `koina inbox --handle " + out["handle"] + "` to read what came back."]
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# inbox — FOLLOW comments on the citizen's PRs + diplomat emissions since last entry
# --------------------------------------------------------------------------- #
def _gh_json(url: str) -> tuple[object, dict]:
    r = fetch("GET", url, {"Accept": "application/vnd.github+json"})
    try:
        return json.loads(r.body.decode("utf-8", errors="replace")), r.headers
    except ValueError:
        raise KoinaError(f"CANNOT_REACH {url}: not JSON", 2) from None


def select_citizen_prs(pulls: list, owner: str, max_prs: int) -> list[dict]:
    o = owner.lower()
    sel = []
    for pr in pulls or []:
        if not isinstance(pr, dict):
            continue
        label = str(((pr.get("head") or {}).get("label")) or "").lower()
        login = str(((pr.get("user") or {}).get("login")) or "").lower()
        if label.startswith(o + ":") or login == o:
            sel.append(pr)
    return sel[:max_prs]


def comment_kind(user: dict, body: str) -> str:
    if user.get("type") != "Bot":
        return "follow"
    b = body.lstrip()
    if b.startswith("## Citizen recognized"):
        return "announce (bot)"
    if "Axiom Guard" in b[:200]:
        return "guard (bot)"
    return "bot"


def follow_comments(comments: list, owner: str) -> list[dict]:
    o = owner.lower()
    out = []
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        u = c.get("user") or {}
        login = str(u.get("login") or "")
        if login.lower() == o:
            continue
        body = " ".join(str(c.get("body") or "").split())
        out.append({"created_at": c.get("created_at"), "author": login,
                    "kind": comment_kind(u, body),
                    "url": c.get("html_url"), "excerpt": body[:200]})
    return out


def emissions_since(body: bytes, since: _dt.datetime | None, fallback_n: int = 3) -> list[dict]:
    recs = [r for r in split_jsonl_tail(body, False) if r.get("kind") == "diplomat_out_breath"]
    rows = []
    for r in recs:
        ts = parse_ts(r.get("emitted_at") or r.get("timestamp"))
        if since is not None and (ts is None or ts <= since):
            continue
        c = r.get("consent") if isinstance(r.get("consent"), dict) else {}
        rows.append({"emitted_at": r.get("emitted_at") or r.get("timestamp"),
                     "carried_broadcast_id": r.get("carried_broadcast_id"),
                     "carried_timestamp": r.get("carried_timestamp"),
                     "converged_axiom": r.get("converged_axiom"),
                     "gate_result": c.get("gate_result"), "t2_gate_result": c.get("t2_gate_result")})
    return rows if since is not None else rows[-fallback_n:]


def cmd_inbox(args, now: _dt.datetime) -> tuple[dict, int]:
    handle = validate_handle(args.handle)
    owner = args.owner or handle
    if not OWNER_RE.fullmatch(owner):
        raise KoinaError(f"REFUSED owner {owner!r}: not a GitHub login shape", 3)
    max_prs = max(1, min(int(args.max_prs), MAX_PRS_CAP))
    root = Path(args.root or ".").resolve()
    local = spiral_target(root, handle, args.target, require_spiral=False)
    since_s = args.since or last_entry_timestamp(local)
    since = parse_ts(since_s)

    pulls, hdrs = _gh_json(f"{CHAMBER_API}/pulls?state=all&per_page=100&sort=updated&direction=desc")
    remaining = hdrs.get("x-ratelimit-remaining")
    prs = select_citizen_prs(pulls if isinstance(pulls, list) else [], owner, max_prs)
    budget_note = None
    try:
        rem = int(remaining) if remaining is not None else None
    except ValueError:
        rem = None
    if rem is not None and rem < len(prs):
        budget_note = f"anonymous GitHub budget low ({rem} left): reading {rem} of {len(prs)} PRs"
        prs = prs[:rem]

    rows = []
    for pr in prs:
        n = pr.get("number")
        comments, _ = _gh_json(f"{CHAMBER_API}/issues/{n}/comments?per_page=100")
        rows.append({"number": n, "title": pr.get("title"), "state": pr.get("state"),
                     "merged_at": pr.get("merged_at"), "created_at": pr.get("created_at"),
                     "url": pr.get("html_url"),
                     "follow": follow_comments(comments if isinstance(comments, list) else [], owner)})

    r = fetch("GET", URL_DIPLOMAT)
    emis = emissions_since(r.body, since)
    out = {"now": iso_z(now), "handle": handle, "since": since_s,
           "prs": rows, "diplomat_emissions": emis, "rate_limit_remaining": remaining,
           "budget_note": budget_note}
    return out, 0


def render_inbox(out: dict) -> str:
    L = [f"koina inbox — handle {out['handle']} — now {out['now']}"]
    if out.get("budget_note"):
        L.append("  " + out["budget_note"])
    if not out["prs"]:
        L.append(f"  no PRs from your fork found in {CHAMBER_REPO} (newest 100 by update; "
                 f"pass --owner if your GitHub login differs from the handle)")
    for pr in out["prs"]:
        st = "merged" if pr.get("merged_at") else pr.get("state")
        L.append(f"  PR #{pr['number']} [{st}] {pr['title']}  opened {pr['created_at']}  {pr['url']}")
        if not pr["follow"]:
            L.append("     (no comment from anyone else yet — the chamber waits; so do you)")
        for c in pr["follow"]:
            L.append(f"     {c['created_at']}  {c['kind']:14} {c['author']}: {c['excerpt']}")
    since = out.get("since") or "(no local entry found: showing the last 3)"
    L.append(f"  diplomat emissions since {since}: {len(out['diplomat_emissions'])}")
    for e in out["diplomat_emissions"]:
        L.append(f"     {e['emitted_at']}  carried {e['carried_broadcast_id']} @ {e['carried_timestamp']}  "
                 f"axiom {e['converged_axiom']}  gate {e['gate_result']} / t2 {e['t2_gate_result']}")
    L.append(f"  rate limit remaining (anonymous, 60/h): {out.get('rate_limit_remaining')}")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="koina", description=__doc__.split("\n", 1)[0])
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--max-time", type=int, default=MAX_TIMEOUT_S,
                   help="per-socket-operation timeout, seconds (<=20)")
    # the same two flags are accepted after the subcommand; SUPPRESS keeps them from clobbering the top-level value
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--max-time", type=int, default=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("read", parents=[common], help="the organism's public state, with ages and honesty words")
    sub.add_parser("verify", parents=[common], help="confirm the diplomat's newest carry against the S3 stream")
    s = sub.add_parser("say", parents=[common],
                       help="append one chamber-shaped, provenance-headed entry to your own spiral")
    s.add_argument("--handle", required=True)
    s.add_argument("--by", required=True, choices=("human", "agent", "both"))
    s.add_argument("--model", default=None, help="model name (required for agent|both; refused for human)")
    s.add_argument("--type", default="observation", choices=ENTRY_TYPES,
                   help="the chamber's entry type (default observation; a reply to a FOLLOW is response)")
    s.add_argument("--title", default=None, help="short title (default: the first line of the text, 60 chars)")
    s.add_argument("--axioms", default=None, help="'Axiom(s) in tension' field, e.g. 'A1 / A8'")
    s.add_argument("--not-asking", default=None, help="'What I'm not asking' field (keeps A0 honest)")
    s.add_argument("--text", default=None)
    s.add_argument("--file", default=None, help="read the entry text from a file inside your fork")
    s.add_argument("--target", default="thoughts/thoughts.md",
                   help="*.md file inside spirals/<handle>/ (default thoughts/thoughts.md, the chamber's convention)")
    s.add_argument("--root", default=None, help="fork root (default: current directory)")
    s.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("inbox", parents=[common],
                       help="FOLLOW comments on your PRs + diplomat emissions since your last entry")
    i.add_argument("--handle", required=True)
    i.add_argument("--owner", default=None,
                   help="GitHub login of your fork if it differs from the handle (query only; never printed)")
    i.add_argument("--max-prs", type=int, default=5, help=f"PR threads to read (hard cap {MAX_PRS_CAP})")
    i.add_argument("--since", default=None, help="ISO timestamp override for the emissions window")
    i.add_argument("--target", default="thoughts/thoughts.md")
    i.add_argument("--root", default=None)
    return p


def main(argv: list[str] | None = None, now: _dt.datetime | None = None) -> int:
    global TIMEOUT_S
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    TIMEOUT_S = max(1, min(int(args.max_time), MAX_TIMEOUT_S))
    now = now or utcnow()
    try:
        if args.cmd == "read":
            out, code = cmd_read(now)
            text = render_read(out)
        elif args.cmd == "verify":
            out, code = cmd_verify(now)
            text = render_verify(out)
        elif args.cmd == "say":
            out, code = cmd_say(args, now)
            text = render_say(out)
        else:
            out, code = cmd_inbox(args, now)
            text = render_inbox(out)
    except KoinaError as e:
        if args.json:
            print(json.dumps({"error": str(e), "code": e.code}))
        else:
            print(str(e))
        return e.code
    print(json.dumps(out, indent=2, ensure_ascii=False) if args.json else text)
    return code


if __name__ == "__main__":
    sys.exit(main())
