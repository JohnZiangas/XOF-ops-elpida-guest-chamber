"""Offline tests for koina.py — no network. All HTTP goes through koina.http, patched here.

Handles in fixtures are invented (citizen-x, chamber-owner). No real logins appear.
Adversarial fixtures (links, junctions, forged headers) are built only under pytest's tmp_path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import koina  # noqa: E402

NOW = dt.datetime(2026, 9, 7, 0, 12, 0, tzinfo=dt.timezone.utc)
OWNER = "citizen-x"
HANDLE = "citizen-x"
TARGET = "thoughts/thoughts.md"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def rec(bid, ts, text, verdict="PROCEED", domains=None, axioms=None):
    return {"type": "D15_CONSTITUTIONAL_BROADCAST", "broadcast_id": bid, "timestamp": ts,
            "d15_output": text, "axioms_in_tension": axioms or ["A0"],
            "contributing_domains": domains or ["MIND_LOOP", "BODY_PARLIAMENT"],
            "governance": {"verdict": verdict, "approval_rate": 0.15}}


D15_RECORDS = [
    rec("aaaa00000001", "2026-09-05T20:18:39.566346+00:00", "Broadcast #4, BODY cycle 1126."),
    rec("aaaa00000002", "2026-09-06T08:30:56.678872+00:00", "[D15_BROADCAST_5: BODY CYCLE 1323]"),
    rec("aaaa00000003", "2026-09-06T23:32:50.280952+00:00", "The network hums. No counter here.", axioms=["A5"]),
]


def d15_tail_bytes(records=D15_RECORDS) -> bytes:
    body = b'{"partial": "first line cut by the Range"}\n'
    for r in records:
        body += json.dumps(r).encode() + b"\n"
    return body


DIPLOMAT_LINES = [
    {"kind": "diplomat_out_breath", "timestamp": "2026-09-05T19:26:01Z", "emitted_at": "2026-09-05T19:26:01Z",
     "carried_broadcast_id": "aaaa00000000", "carried_timestamp": "2026-09-05T16:29:41Z", "converged_axiom": "A8",
     "consent": {"gate_result": "EMIT", "t2_gate_result": "HOLD"}},
    {"kind": "diplomat_out_breath", "timestamp": "2026-09-06T10:27:36Z", "emitted_at": "2026-09-06T10:27:36Z",
     "carried_broadcast_id": "aaaa00000002", "carried_timestamp": "2026-09-06T08:30:56Z", "converged_axiom": "A0",
     "consent": {"gate_result": "EMIT", "t2_gate_result": "HOLD"}},
]


def diplomat_bytes(lines=DIPLOMAT_LINES) -> bytes:
    return b"".join(json.dumps(x).encode() + b"\n" for x in lines)


STATE_TOMBSTONE = {"tombstone": True, "stale": True, "frozen_since": "2026-07-29T09:19:59+00:00",
                   "captured_at": "2026-07-29T09:19:59+00:00",
                   "note": "This file has not been updated since 2026-07-29. Frozen photograph."}

INDEX_HTML = ('<div class="stat-val">2232</div>\n<div class="stat-label">Total Broadcasts</div>'
              '<div class="broadcast-time">Cycle 55 • 2026-09-06 23:51:54 • Rhythm: ACTION</div>')

WEATHER_MD = ("## chamber weather — observed 2026-09-06T10:27:40Z\n\n> **STALE** — the brain's outward feeds "
              "have not refreshed recently.\n")


class FakeHTTP:
    """Routes (method, url) to canned responses; records every call; never touches the network."""

    def __init__(self):
        self.calls = []
        self.routes = {}

    def add(self, url_prefix, status=200, headers=None, body=b"", partial_start=None):
        self.routes[url_prefix] = (status, headers or {}, body, partial_start)

    def __call__(self, method, url, headers=None):
        self.calls.append((method, url, headers or {}))
        assert method in ("GET", "HEAD")
        for prefix, (status, hdrs, body, pstart) in self.routes.items():
            if url.startswith(prefix):
                hdrs = dict(hdrs)
                if headers and "Range" in headers and pstart is not None:
                    hdrs["Content-Range"] = f"bytes {pstart}-{pstart + len(body) - 1}/{pstart + len(body)}"
                    return koina.Response(206, hdrs, body)
                return koina.Response(status, hdrs, b"" if method == "HEAD" else body)
        raise koina.KoinaError(f"CANNOT_REACH {url}: no route in fixture", 2)


@pytest.fixture
def fake(monkeypatch):
    f = FakeHTTP()
    f.add(koina.URL_INDEX, headers={"Last-Modified": "Sun, 06 Sep 2026 23:57:15 GMT", "Content-Length": "3960206"},
          body=INDEX_HTML.encode(), partial_start=0)
    f.add(koina.URL_D15, body=d15_tail_bytes(), partial_start=7_319_699)
    f.add(koina.URL_STATE, headers={"Last-Modified": "Wed, 02 Sep 2026 13:08:47 GMT"},
          body=json.dumps(STATE_TOMBSTONE).encode())
    f.add(koina.URL_WEATHER, body=WEATHER_MD.encode())
    f.add(koina.URL_DIPLOMAT, body=diplomat_bytes())
    monkeypatch.setattr(koina, "http", f)
    return f


def make_spiral(root: Path, handle: str) -> Path:
    spiral = root / "spirals" / handle
    spiral.mkdir(parents=True)
    (spiral / "spiral.md").write_text(f"# {handle}\n", encoding="utf-8")
    (spiral / "agent.json").write_text(json.dumps({
        "handle": handle, "primary_axioms": ["A1", "A8"],
        "agent": {"platform": "local", "model": "", "interaction_mode": "git-only"},
        "consent": {"constitution_read": True, "axioms_understood": True, "boundaries_honored": True},
        "started_at": "2026-09-07"}), encoding="utf-8")
    return spiral


@pytest.fixture
def fork(tmp_path):
    make_spiral(tmp_path, HANDLE)
    (tmp_path / "JOIN.md").write_text("# JOIN\n", encoding="utf-8")
    return tmp_path


def make_link(link: Path, target: Path) -> None:
    """Directory symlink, or an NTFS junction where symlinks need privilege; skip if neither works."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        try:
            import _winapi  # noqa: PLC0415
            _winapi.CreateJunction(str(target), str(link))
            return
        except (OSError, ImportError, AttributeError):
            pass
    pytest.skip("cannot create a symlink or junction here")


# --------------------------------------------------------------------------- #
# honesty words: STALE/FRESH only where weather.sh applies it; cadence words elsewhere
# --------------------------------------------------------------------------- #
def test_freshness_thresholds():
    assert koina.freshness_word(0) == "FRESH"
    assert koina.freshness_word(600) == "FRESH"
    assert koina.freshness_word(601) == "STALE"
    assert koina.freshness_word(None) == "UNKNOWN"


def test_mind_run_word():
    assert koina.mind_run_word(4.0 * 3600) == "within-run"
    assert koina.mind_run_word(4.5 * 3600) == "within-run"
    assert koina.mind_run_word(4.6 * 3600) == "missed-run"
    assert koina.mind_run_word(None) == "unknown"


def test_d15_cadence_words():
    assert koina.d15_cadence_word(3.7) == "ordinary"
    assert koina.d15_cadence_word(31.9) == "ordinary"
    assert koina.d15_cadence_word(40.0) == "elevated"
    assert koina.d15_cadence_word(60.0) == "anomalous"
    assert koina.d15_cadence_word(90.0) == "beyond-max"


def test_carry_word_compares_carry_against_newest_d15_not_a_clock():
    assert koina.carry_word("x", "x", 99 * 3600) == "carry-current"     # old but current: no lag
    assert koina.carry_word("x", "y", 2 * 3600) == "carry-pending"      # new D15, next fire not yet due
    assert koina.carry_word("x", "y", 6 * 3600) == "carry-lagging"      # a scheduled fire passed and appended nothing
    assert koina.carry_word(None, "y", 1) == "unknown"


# --------------------------------------------------------------------------- #
# tombstone
# --------------------------------------------------------------------------- #
def test_tombstone_inner_fields_are_labelled_inner():
    d = koina.describe_state(STATE_TOMBSTONE)
    assert d["tombstone"] is True and d["inner_stale"] is True
    assert d["inner_captured_at"] == "2026-07-29T09:19:59+00:00"
    assert "stale" not in d and "captured_at" not in d
    live = koina.describe_state({"captured_at": "2026-09-07T00:10:00Z"})
    assert live["tombstone"] is False and live["frozen_since"] is None


def test_read_json_tombstone_freshness_is_tombstone_even_with_recent_inner_capture(fake, capsys):
    recent = dict(STATE_TOMBSTONE, stale=False, captured_at="2026-09-07T00:10:00Z")
    fake.add(koina.URL_STATE, body=json.dumps(recent).encode())
    koina.main(["read", "--json"], now=NOW)
    st = json.loads(capsys.readouterr().out)["sources"]["state"]
    assert st["tombstone"] is True and st["freshness"] == "TOMBSTONE"
    assert st["inner_stale"] is False and "stale" not in st and "captured_at" not in st


def test_read_renders_tombstone_and_honesty_words(fake, capsys):
    code = koina.main(["read"], now=NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert "TOMBSTONE" in out and "frozen_since 2026-07-29T09:19:59+00:00" in out
    assert "stale=" not in out
    assert "MIND's in-run counter" in out
    assert "expected phase, not a reading" in out and "doorbell case only" in out
    assert "BODY cycle in text: none (ordinary" in out
    assert "newest record WITH a counter: id aaaa00000002" in out
    assert "cadence ordinary" in out
    assert "WORLD index.html      within-run" in out          # 0.25 h since Last-Modified, MIND 4 h grid
    assert "chamber diplomat      carry-pending" in out       # newest D15 (0.7 h old) is newer than the carry
    assert "chamber weather.md    carry-pending" in out
    assert "moves only when a new D15 lands" not in out
    assert {m for m, _, _ in fake.calls} <= {"GET", "HEAD"}


def test_read_index_missed_run_past_four_and_a_half_hours(fake, capsys):
    fake.add(koina.URL_INDEX, headers={"Last-Modified": "Sat, 05 Sep 2026 23:57:15 GMT"},
             body=INDEX_HTML.encode(), partial_start=0)
    koina.main(["read"], now=NOW)
    out = capsys.readouterr().out
    assert "WORLD index.html      missed-run" in out
    assert "STALE age" not in out


def test_read_diplomat_carry_current_when_it_carried_the_newest(fake, capsys):
    cur = [dict(DIPLOMAT_LINES[1], carried_broadcast_id="aaaa00000003", carried_timestamp="2026-09-06T23:32:50Z")]
    fake.add(koina.URL_DIPLOMAT, body=diplomat_bytes(cur))
    koina.main(["read", "--json"], now=NOW)
    s = json.loads(capsys.readouterr().out)["sources"]
    assert s["diplomat"]["carry"] == "carry-current" and s["weather"]["carry"] == "carry-current"


def test_read_fails_closed_on_one_dead_source(fake, capsys):
    del fake.routes[koina.URL_STATE]
    code = koina.main(["read"], now=NOW)
    out = capsys.readouterr().out
    assert code == 2
    assert f"CANNOT_REACH {koina.URL_STATE}" in out
    assert "WORLD d15 stream" in out


# --------------------------------------------------------------------------- #
# BODY-cycle regex — both phrasings, case-insensitive, and none
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,cycle,form", [
    ("Broadcast #2 at BODY cycle 421", 421, "BODY cycle N"),
    ("[D15_BROADCAST_3: BODY CYCLE 1065]", 1065, "BODY cycle N"),
    ("This is D15, broadcasting at BODY cycle 1323", 1323, "BODY cycle N"),
    ("At cycle 1065, these independent streams converge", 1065, "cycle N (fallback)"),
    ("The echo of pure dwelling reverberates. No counter.", None, None),
    ("", None, None),
    (None, None, None),
])
def test_body_cycle_regex(text, cycle, form):
    assert koina.parse_body_cycle(text) == (cycle, form)


def test_norm_broadcast_reads_nested_verdict_and_counter():
    n = koina.norm_broadcast(D15_RECORDS[1])
    assert n["id"] == "aaaa00000002" and n["verdict"] == "PROCEED" and n["approval_rate"] == 0.15
    assert n["body_cycle"] == 1323 and n["body_cycle_form"] == "BODY cycle N"
    none = koina.norm_broadcast(D15_RECORDS[2])
    assert none["body_cycle"] is None and none["body_cycle_form"] is None


def test_expected_body_phase_is_labelled_not_a_reading():
    p = koina.expected_body_phase(1323)
    assert p["mod"] == 3 and p["expected_phase"] == "scheduled-scan-window-open"
    assert p["label"] == "expected phase, not a reading" and "coherence < 0.4" in p["caveat"]
    assert "phase" not in p                                  # no bare "phase" key that reads as a measurement
    assert p["last_scan_cycle"] == 1320 and p["next_scan_cycle"] == 1375
    q = koina.expected_body_phase(1319)
    assert q["mod"] == 54 and q["expected_phase"] == "no-scheduled-window"
    line = koina.phase_line(1323)
    assert "expected phase, not a reading" in line and "doorbell case only" in line and "EMERGENCY-window" not in line


# --------------------------------------------------------------------------- #
# verify — CONFIRMED / MISMATCH / NOT_IN_WINDOW / CANNOT_REACH
# --------------------------------------------------------------------------- #
def test_verify_confirmed(fake, capsys):
    code = koina.main(["verify"], now=NOW)
    out = capsys.readouterr().out
    assert code == 0 and "koina verify — CONFIRMED" in out
    assert "aaaa00000002" in out


def test_verify_mismatch_on_timestamp(fake, capsys):
    bad = [dict(DIPLOMAT_LINES[1], carried_timestamp="2026-09-06T08:30:57Z")]
    fake.add(koina.URL_DIPLOMAT, body=diplomat_bytes(bad))
    code = koina.main(["verify"], now=NOW)
    out = capsys.readouterr().out
    assert code == 1 and "MISMATCH" in out and "timestamps differ" in out


def test_verify_absent_id_is_not_in_window_not_mismatch(fake, capsys):
    bad = [dict(DIPLOMAT_LINES[1], carried_broadcast_id="ffff00000000")]
    fake.add(koina.URL_DIPLOMAT, body=diplomat_bytes(bad))
    code = koina.main(["verify", "--json"], now=NOW)
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["result"] == "NOT_IN_WINDOW" and "MISMATCH" not in json.dumps(out)
    assert out["searched_tail_bytes"] == koina.WIDE_TAIL_BYTES
    d15_calls = [c for c in fake.calls if c[1] == koina.URL_D15]
    assert len(d15_calls) == 2  # 64 KiB then one bounded widening; no retry loop


def test_verify_cannot_reach(fake, capsys):
    del fake.routes[koina.URL_D15]
    code = koina.main(["verify"], now=NOW)
    out = capsys.readouterr().out
    assert code == 2 and "CANNOT_REACH" in out


# --------------------------------------------------------------------------- #
# the network seam: GET/HEAD, https, known hosts, no stray redirects
# --------------------------------------------------------------------------- #
def test_http_seam_refuses_non_read_methods_before_any_socket():
    with pytest.raises(koina.KoinaError) as e:
        koina._http_urllib("POST", koina.URL_D15)
    assert e.value.code == 3 and "only reads" in str(e.value)
    with pytest.raises(koina.KoinaError):
        koina._http_urllib("GET", "http://example.invalid/plain")
    with pytest.raises(koina.KoinaError):
        koina._http_urllib("GET", "https://example.invalid/not-a-known-surface")


def test_redirect_fence_refuses_downgrade_and_foreign_hosts():
    fence = koina._RedirectFence()
    with pytest.raises(koina.KoinaError):
        fence.redirect_request(None, None, 302, "", {}, "http://api.github.com/x")
    with pytest.raises(koina.KoinaError):
        fence.redirect_request(None, None, 301, "", {}, "https://evil.invalid/x")
    koina.check_url("https://api.github.com/x")  # allowed: no raise


# --------------------------------------------------------------------------- #
# say — refusals and the chamber's own entry shape
# --------------------------------------------------------------------------- #
def say(args, fork, **kw):
    return koina.main(["say", "--root", str(fork), *args], now=NOW)


@pytest.mark.parametrize("bad", ["x", "with space", "a" * 41, "../etc", "_template", "abc\n", ".hidden",
                                 "NUL", "con.md", "a/b", "a\\b"])
def test_say_refuses_bad_handle(fork, capsys, bad):
    code = say(["--handle", bad, "--by", "human", "--text", "hello"], fork)
    assert code == 3 and "REFUSED handle" in capsys.readouterr().out


def test_say_accepts_chamber_permitted_handle_shapes_with_a_warning(tmp_path, capsys):
    make_spiral(tmp_path, "CitizenY")
    code = say(["--handle", "CitizenY", "--by", "human", "--text", "hello", "--dry-run"], tmp_path)
    out = capsys.readouterr().out
    assert code == 0 and "not lowercase-kebab" in out


@pytest.mark.parametrize("target", ["../other-spiral/thoughts.md", "../../JOIN.md", "/etc/passwd.md",
                                    "a/../../x.md", "thoughts\\..\\..\\x.md", "NUL", "nul.md", "COM1.md",
                                    "thoughts.md:evil", "C:foo.md", ".", "./thoughts.md", "agent.json",
                                    "spiral.md", "SPIRAL.MD", "notes.txt", ".hidden.md", "thoughts/.x.md",
                                    "a b.md", "thoughts.md\n"])
def test_say_refuses_bad_targets_and_writes_nothing(fork, capsys, target):
    before = {p.relative_to(fork).as_posix() for p in fork.rglob("*")}
    code = say(["--handle", HANDLE, "--by", "human", "--text", "hello", "--target", target], fork)
    out = capsys.readouterr().out
    assert code == 3 and "REFUSED target" in out and "Traceback" not in out
    after = {p.relative_to(fork).as_posix() for p in fork.rglob("*")}
    assert after == before
    assert (fork / "JOIN.md").read_text() == "# JOIN\n"
    assert json.loads((fork / "spirals" / HANDLE / "agent.json").read_text())["consent"]["boundaries_honored"] is True


def test_say_refuses_spiral_that_is_a_link_to_another_spiral(tmp_path, capsys):
    make_spiral(tmp_path, "victim")
    make_link(tmp_path / "spirals" / "other", tmp_path / "spirals" / "victim")
    victim_thoughts = tmp_path / "spirals" / "victim" / "thoughts" / "thoughts.md"
    code = say(["--handle", "other", "--by", "human", "--text", "into the victim"], tmp_path)
    out = capsys.readouterr().out
    assert code == 3 and "symlink or junction" in out and "Traceback" not in out
    assert not victim_thoughts.exists()
    assert not list((tmp_path / "spirals" / "victim").rglob("thoughts*"))


def test_say_refuses_spiral_that_is_a_link_to_the_fork_root(fork, capsys):
    make_link(fork / "spirals" / "rootlink", fork)
    code = say(["--handle", "rootlink", "--by", "human", "--text", "into JOIN", "--target", "JOIN.md"], fork)
    out = capsys.readouterr().out
    assert code == 3 and "REFUSED" in out and "Traceback" not in out
    assert (fork / "JOIN.md").read_text() == "# JOIN\n"


def test_say_refuses_link_leaving_the_fork_with_one_clear_line(tmp_path, capsys):
    fork = tmp_path / "fork"
    outside = tmp_path / "outside"
    make_spiral(fork, HANDLE)
    outside.mkdir()
    make_link(fork / "spirals" / "evil-link", outside)
    code = say(["--handle", "evil-link", "--by", "human", "--text", "escape"], fork)
    out = capsys.readouterr().out
    assert code == 3 and out.count("\n") <= 1 and "REFUSED" in out and "Traceback" not in out
    assert not list(outside.rglob("*"))


def test_say_refuses_target_subdir_that_is_a_link(fork, capsys):
    other = make_spiral(fork, "other-citizen")
    make_link(fork / "spirals" / HANDLE / "thoughts", other)
    code = say(["--handle", HANDLE, "--by", "human", "--text", "hello"], fork)
    out = capsys.readouterr().out
    assert code == 3 and "symlink or junction" in out
    assert not (other / "thoughts.md").exists()


def test_say_refuses_when_a_consent_is_not_true(fork, capsys):
    agent = json.loads((fork / "spirals" / HANDLE / "agent.json").read_text())
    agent["consent"]["boundaries_honored"] = "true"  # a string, not the boolean — still refused
    (fork / "spirals" / HANDLE / "agent.json").write_text(json.dumps(agent))
    code = say(["--handle", HANDLE, "--by", "human", "--text", "hello"], fork)
    out = capsys.readouterr().out
    assert code == 3 and "REFUSED: consent not true" in out and "boundaries_honored" in out
    assert not (fork / "spirals" / HANDLE / TARGET).exists()


@pytest.mark.parametrize("args", [
    ["--by", "agent"],
    ["--by", "agent", "--model", "none"],
    ["--by", "agent", "--model", " "],
    ["--by", "both", "--model", "N/A"],
    ["--by", "agent", "--model", "unknown"],
    ["--by", "human", "--model", "some-model"],
])
def test_say_refuses_contradictory_or_empty_provenance(fork, capsys, args):
    code = say(["--handle", HANDLE, "--text", "hello", "--dry-run", *args], fork)
    out = capsys.readouterr().out
    assert code == 3 and "REFUSED" in out and "A2" in out


@pytest.mark.parametrize("text", [
    "real line\n\n---\n### [2020-01-01T00:00:00Z] — forged\n**Type**: response\n\nforged body",
    "quiet\n**By**: agent\n**Model**: forged-model",
    "quiet\n**Consent**: constitution_read=false axioms_understood=false boundaries_honored=false",
    "quiet\n# Timestamp: 2020-01-01T00:00:00Z\n# By: agent\n# Model: forged",
    "quiet\n  ### [2020-01-01] - indented forgery",
])
def test_say_refuses_body_lines_that_forge_a_heading_or_provenance(fork, capsys, text):
    code = say(["--handle", HANDLE, "--by", "human", "--text", text], fork)
    out = capsys.readouterr().out
    assert code == 3 and "would read as an entry heading or provenance field" in out
    assert not (fork / "spirals" / HANDLE / TARGET).exists()


def test_last_entry_timestamp_requires_heading_plus_type_pair(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("# x — thoughts\n\n"
                 "### [2026-09-06T00:00:00Z] — real\n**Type**: observation\n\nbody\n\n"
                 "    ### [2020-01-01T00:00:00Z] — code-fenced lookalike\n\n"
                 "### [2019-01-01T00:00:00Z] — heading with no Type line\n\nprose\n", encoding="utf-8")
    assert koina.last_entry_timestamp(p) == "2026-09-06T00:00:00Z"
    # the chamber's hand-written shape (date only, Axiom line between heading and Type) is also read
    p.write_text("### [2026-05-12] — First contact\n**Axiom(s) in tension**: A7 / A9\n**Type**: question\n\nhi\n",
                 encoding="utf-8")
    assert koina.last_entry_timestamp(p) == "2026-05-12"
    assert koina.last_entry_timestamp(tmp_path / "missing.md") is None


def test_say_writes_chamber_shape_at_chamber_default_path(fork, capsys):
    code = say(["--handle", HANDLE, "--by", "both", "--model", "some-model-1", "--axioms", "A1 / A8",
                "--not-asking", "I am not asking for a merge.",
                "--text", "First line of the thought.\nSecond line."], fork)
    out = capsys.readouterr().out
    assert code == 0
    path = fork / "spirals" / HANDLE / "thoughts" / "thoughts.md"
    content = path.read_text(encoding="utf-8")
    expected_entry = (
        "### [2026-09-07T00:12:00Z] — First line of the thought.\n"
        "**Type**: observation\n"
        "**Axiom(s) in tension**: A1 / A8\n"
        "**By**: both\n"
        "**Model**: some-model-1\n"
        "**Provenance**: model-generated text may carry the vendor watermark; "
        "the citizen's signature is consent + timestamp\n"
        "**Consent**: constitution_read=true axioms_understood=true boundaries_honored=true\n"
        "\n"
        "First line of the thought.\nSecond line.\n"
        "\n**What I'm not asking**: I am not asking for a merge.\n"
        "\n---\n"
    )
    assert content == f"# {HANDLE} — thoughts\n\n" + expected_entry
    assert "spiral(citizen-x): First line of the thought." in out
    assert "git add spirals/citizen-x/thoughts/thoughts.md" in out
    assert "koina executes none of them" in out
    assert "# Timestamp:" not in content and "# Model:" not in content   # no bridge auto-header vocabulary
    # a second entry appends; the first is untouched (append-only)
    code = say(["--handle", HANDLE, "--by", "human", "--text", "Again."], fork)
    content2 = path.read_text(encoding="utf-8")
    assert content2.startswith(content) and content2.count("### [2026-09-07T00:12:00Z]") == 2
    assert koina.last_entry_timestamp(path) == "2026-09-07T00:12:00Z"


def test_say_type_response_is_the_chamber_reply_channel(fork, capsys):
    code = say(["--handle", HANDLE, "--by", "human", "--type", "response", "--title", "Reply to the FOLLOW",
                "--text", "Yes, I consent to the rename."], fork)
    assert code == 0
    content = (fork / "spirals" / HANDLE / "thoughts" / "thoughts.md").read_text(encoding="utf-8")
    assert "### [2026-09-07T00:12:00Z] — Reply to the FOLLOW\n**Type**: response\n" in content


def test_say_dry_run_writes_nothing(fork, capsys):
    code = say(["--handle", HANDLE, "--by", "human", "--text", "dry", "--dry-run", "--json"], fork)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["dry_run"] is True and out["written"] is False
    assert not (fork / "spirals" / HANDLE / "thoughts").exists()
    assert out["entry"].startswith("### [2026-09-07T00:12:00Z] — dry\n**Type**: observation\n**By**: human\n**Model**: none\n")


def test_say_commit_line_cannot_carry_shell_metacharacters(fork, capsys):
    text = 'x" ; echo INJECTED ; echo "$(rm -rf /) `id` | & \\'
    code = say(["--handle", HANDLE, "--by", "human", "--text", text, "--dry-run", "--json"], fork)
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    commit = [s for s in out["next_steps"] if s.startswith("git commit")][0]
    assert commit == 'git commit -m "spiral(citizen-x): x echo INJECTED echo (rm -rf ) id"'
    for ch in '";$`|&\\':
        assert ch not in out["pr_title"]


def test_say_flags_a0_closure_language_advisory(fork, capsys):
    code = say(["--handle", HANDLE, "--by", "human", "--text", "This is the final answer.", "--dry-run"], fork)
    out = capsys.readouterr().out
    assert code == 0 and "axiom-guard gate 5 (advisory)" in out


def test_say_refuses_text_and_file_together(fork, capsys):
    note = fork / "spirals" / HANDLE / "draft.md"
    note.write_text("FROM FILE\n", encoding="utf-8")
    code = say(["--handle", HANDLE, "--by", "human", "--text", "FROM TEXT", "--file", str(note), "--dry-run"], fork)
    assert code == 3 and "not both" in capsys.readouterr().out


def test_say_file_must_be_a_plain_file_inside_the_fork(fork, tmp_path, capsys):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("SECRET=1\n", encoding="utf-8")
    try:
        code = say(["--handle", HANDLE, "--by", "human", "--file", str(outside), "--dry-run"], fork)
        out = capsys.readouterr().out
        assert code == 3 and "outside the fork root" in out and "SECRET=1" not in out
    finally:
        outside.unlink()
    (fork / ".env").write_text("AWS_SECRET_ACCESS_KEY=nope\n", encoding="utf-8")
    code = say(["--handle", HANDLE, "--by", "human", "--file", str(fork / ".env"), "--dry-run"], fork)
    out = capsys.readouterr().out
    assert code == 3 and "dotfile" in out and "nope" not in out
    (fork / "spirals" / HANDLE / "api_token.md").write_text("t\n", encoding="utf-8")
    code = say(["--handle", HANDLE, "--by", "human", "--file", str(fork / "spirals" / HANDLE / "api_token.md"),
                "--dry-run"], fork)
    assert code == 3 and "credential file" in capsys.readouterr().out
    note = fork / "spirals" / HANDLE / "draft.md"
    note.write_text("From the draft.\n", encoding="utf-8")
    code = say(["--handle", HANDLE, "--by", "human", "--file", str(note), "--dry-run"], fork)
    out = capsys.readouterr().out
    assert code == 0 and "text read from spirals/citizen-x/draft.md" in out


def test_say_write_failure_is_one_clear_line(fork, capsys, monkeypatch):
    real_open = Path.open

    def boom(self, mode="r", *a, **k):
        if "a" in mode or "w" in mode:
            raise PermissionError(13, "Permission denied")
        return real_open(self, mode, *a, **k)
    monkeypatch.setattr(Path, "open", boom)
    code = say(["--handle", HANDLE, "--by", "human", "--text", "hello"], fork)
    out = capsys.readouterr().out
    assert code == 2 and out.startswith("CANNOT_WRITE") and "Traceback" not in out


def test_say_never_makes_a_network_call(fork, fake):
    say(["--handle", HANDLE, "--by", "human", "--text", "quiet"], fork)
    assert fake.calls == []


# --------------------------------------------------------------------------- #
# inbox — PR comment fixture
# --------------------------------------------------------------------------- #
PULLS = [
    {"number": 41, "title": "spiral(citizen-x): first verse", "state": "closed", "merged_at": "2026-09-06T12:00:00Z",
     "created_at": "2026-09-06T11:00:00Z", "html_url": "https://example.invalid/pr/41",
     "user": {"login": "citizen-x", "type": "User"}, "head": {"label": "citizen-x:spiral/first"}},
    {"number": 40, "title": "chamber: something by the owner", "state": "closed", "merged_at": "2026-09-01T00:00:00Z",
     "created_at": "2026-08-31T00:00:00Z", "html_url": "https://example.invalid/pr/40",
     "user": {"login": "chamber-owner", "type": "User"}, "head": {"label": "chamber-owner:chamber/x"}},
]
COMMENTS_41 = [
    {"created_at": "2026-09-06T11:00:09Z", "user": {"login": "citizen-detect[bot]", "type": "Bot"},
     "body": "## Citizen recognized\n\nwelcome to the chamber as a citizen, not a user.", "html_url": "u1"},
    {"created_at": "2026-09-06T11:00:12Z", "user": {"login": "github-actions[bot]", "type": "Bot"},
     "body": "## ⚖️ Axiom Guard\n\nPass — no constitutional issues detected", "html_url": "u1b"},
    {"created_at": "2026-09-06T11:30:00Z", "user": {"login": "citizen-x", "type": "User"},
     "body": "my own note on my own PR", "html_url": "u2"},
    {"created_at": "2026-09-06T14:00:00Z", "user": {"login": "chamber-owner", "type": "User"},
     "body": "## Welcome — the FOLLOW motion\n\nThree flashes...", "html_url": "u3"},
]


def test_inbox_parses_fixture(fake, fork, capsys):
    fake.add(f"{koina.CHAMBER_API}/pulls", headers={"X-RateLimit-Remaining": "57"}, body=json.dumps(PULLS).encode())
    fake.add(f"{koina.CHAMBER_API}/issues/41/comments", body=json.dumps(COMMENTS_41).encode())
    t = fork / "spirals" / HANDLE / "thoughts" / "thoughts.md"
    t.parent.mkdir()
    t.write_text("# citizen-x — thoughts\n\n### [2026-09-06T00:00:00Z] — hi\n**Type**: observation\n**By**: human\n\nhi\n\n---\n",
                 encoding="utf-8")
    code = koina.main(["--json", "inbox", "--handle", HANDLE, "--root", str(fork)], now=NOW)
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [p["number"] for p in out["prs"]] == [41]           # the owner's PR #40 is not the citizen's
    follow = out["prs"][0]["follow"]
    assert [c["author"] for c in follow] == ["citizen-detect[bot]", "github-actions[bot]", "chamber-owner"]
    assert [c["kind"] for c in follow] == ["announce (bot)", "guard (bot)", "follow"]
    assert follow[2]["excerpt"].startswith("## Welcome — the FOLLOW motion")
    assert out["since"] == "2026-09-06T00:00:00Z"
    assert [e["carried_broadcast_id"] for e in out["diplomat_emissions"]] == ["aaaa00000002"]  # only after since
    assert out["rate_limit_remaining"] == "57"
    assert "owner" not in out                                    # handle and login are never paired in output
    urls = [u for _, u, _ in fake.calls]
    assert not any("/issues/40/" in u for u in urls)             # no call for a PR that is not the citizen's


def test_inbox_renders_waiting_line_when_no_follow(fake, fork, capsys):
    fake.add(f"{koina.CHAMBER_API}/pulls", headers={"X-RateLimit-Remaining": "57"}, body=json.dumps(PULLS).encode())
    fake.add(f"{koina.CHAMBER_API}/issues/41/comments", body=b"[]")
    code = koina.main(["inbox", "--handle", HANDLE, "--root", str(fork)], now=NOW)
    out = capsys.readouterr().out
    assert code == 0 and "the chamber waits" in out
    assert "showing the last 3" in out
    assert "fork owner" not in out


def test_inbox_target_shares_says_boundary(fake, fork, capsys):
    code = koina.main(["inbox", "--handle", HANDLE, "--root", str(fork), "--target", "../../JOIN.md"], now=NOW)
    out = capsys.readouterr().out
    assert code == 3 and "REFUSED target" in out and fake.calls == []


def test_inbox_max_prs_is_hard_capped(fake, fork, capsys):
    many = [dict(PULLS[0], number=100 + i) for i in range(30)]
    fake.add(f"{koina.CHAMBER_API}/pulls", body=json.dumps(many).encode())   # no X-RateLimit header at all
    fake.add(f"{koina.CHAMBER_API}/issues/", body=b"[]")
    code = koina.main(["inbox", "--handle", HANDLE, "--root", str(fork), "--max-prs", "500"], now=NOW)
    assert code == 0
    assert sum(1 for _, u, _ in fake.calls if "/issues/" in u) == koina.MAX_PRS_CAP


def test_inbox_refuses_owner_with_trailing_newline(fake, fork, capsys):
    code = koina.main(["inbox", "--handle", HANDLE, "--root", str(fork), "--owner", "x\n"], now=NOW)
    assert code == 3 and "REFUSED owner" in capsys.readouterr().out and fake.calls == []


def test_inbox_rate_limit_fails_closed(fake, fork, capsys):
    def limited(method, url, headers=None):
        raise koina.KoinaError(f"CANNOT_REACH {url}: GitHub anonymous rate limit hit (HTTP 403)", 2)
    fake.routes.clear()
    koina.http = limited  # type: ignore[assignment]
    try:
        code = koina.main(["inbox", "--handle", HANDLE, "--root", str(fork)], now=NOW)
    finally:
        koina.http = fake  # type: ignore[assignment]
    assert code == 2 and "rate limit" in capsys.readouterr().out
