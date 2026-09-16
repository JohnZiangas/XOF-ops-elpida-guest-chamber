#!/usr/bin/env python3
"""Diplomat out-breath emitter (v0, T0-only).

Reads the newest sealed WORLD D15 broadcast, evaluates an A5 consent gate, and
records one chamber out-breath receipt in ``pulse/diplomat.jsonl``.

Constitutional bounds implemented here:
  - Read-only on WORLD (public S3 broadcasts JSONL)
  - Write only to chamber pulse surfaces (jsonl + weather markdown + ledger)
  - No provider calls
  - No cross-repo writes
  - T0 only in v0 (T1/T2 are fail-closed stubs)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


ROOT = Path(__file__).resolve().parents[2]
PULSE_DIR = ROOT / "pulse"
DIPLOMAT_JSONL = PULSE_DIR / "diplomat.jsonl"
WEATHER_MD = PULSE_DIR / "weather.md"
LEDGER_PATH = PULSE_DIR / "diplomat_emitter_ledger.json"
WORLD_BROADCASTS_URL = (
    "https://elpida-external-interfaces.s3.eu-north-1.amazonaws.com/d15/broadcasts.jsonl"
)

FRESHNESS_WINDOW_HOURS = 24.0
DEFAULT_COOLDOWN_HOURS = 6.0
LEDGER_MAX_ENTRIES = 50


@dataclass(frozen=True)
class ConsentResult:
    t0_emit: bool
    t2_hold: bool
    convergence_verified: bool
    iterative_recheck_passed: bool
    architect_consent: str
    gate_result: str
    hold_reason: str | None
    t2_hold_reason: str | None
    irreversible_relay: bool
    t2_side_effects: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "t0_emit": self.t0_emit,
            "t2_hold": self.t2_hold,
            "convergence_verified": self.convergence_verified,
            "iterative_recheck_passed": self.iterative_recheck_passed,
            "architect_consent": self.architect_consent,
            "gate_result": self.gate_result,
            "hold_reason": self.hold_reason,
            "t2_hold_reason": self.t2_hold_reason,
            "irreversible_relay": self.irreversible_relay,
            "t2_side_effects": self.t2_side_effects,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _fetch_text(url: str, timeout_s: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "elpida-diplomat-emitter/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_jsonl_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _record_has_contract_shape(record: dict[str, Any]) -> bool:
    if record.get("type") != "D15_CONSTITUTIONAL_BROADCAST":
        return False
    if not isinstance(record.get("broadcast_id"), str) or not record.get("broadcast_id"):
        return False
    if _parse_ts(record.get("timestamp")) is None:
        return False
    if not isinstance(record.get("d15_output"), str):
        return False
    axioms = record.get("axioms_in_tension")
    if not isinstance(axioms, list):
        return False
    if not isinstance(record.get("contributing_domains"), list):
        return False
    governance = record.get("governance")
    if not isinstance(governance, dict):
        return False
    if not isinstance(governance.get("verdict"), str):
        return False
    return True


def _newest_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    newest: dict[str, Any] | None = None
    newest_ts: datetime | None = None
    for record in records:
        ts = _parse_ts(record.get("timestamp"))
        if ts is None:
            continue
        if newest is None or newest_ts is None or ts >= newest_ts:
            newest = record
            newest_ts = ts
    return newest


def _load_ledger(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("entries", [])
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _record_dispatch(
    carried_broadcast_id: str,
    status: str,
    now: datetime,
    path: Path = LEDGER_PATH,
) -> None:
    ledger = _load_ledger(path)
    ledger.append(
        {
            "carried_broadcast_id": carried_broadcast_id,
            "fingerprint": hashlib.sha256(
                carried_broadcast_id.encode("utf-8")
            ).hexdigest(),
            "timestamp": _iso(now),
            "status": status,
        }
    )
    ledger = ledger[-LEDGER_MAX_ENTRIES:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _cooldown_hours() -> float:
    raw = os.environ.get("DIPLOMAT_EMITTER_COOLDOWN_HOURS", "").strip()
    if not raw:
        return DEFAULT_COOLDOWN_HOURS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_COOLDOWN_HOURS


def _cooldown_active(
    carried_broadcast_id: str,
    now: datetime,
    hours: float,
    ledger: Optional[list[dict[str, Any]]] = None,
) -> bool:
    if hours <= 0:
        return False
    ledger = ledger if ledger is not None else _load_ledger()
    window = hours * 3600.0
    for entry in reversed(ledger):
        if entry.get("carried_broadcast_id") != carried_broadcast_id:
            continue
        when = _parse_ts(entry.get("timestamp"))
        if when is None:
            continue
        elapsed = (now - when).total_seconds()
        if 0 <= elapsed < window:
            return True
    return False


def evaluate_consent_gate(
    newest_record: dict[str, Any],
    now: datetime,
    architect_consent_present: bool = False,
    freshness_window_h: float = FRESHNESS_WINDOW_HOURS,
) -> ConsentResult:
    domains = newest_record.get("contributing_domains")
    governance = newest_record.get("governance")
    verdict = governance.get("verdict") if isinstance(governance, dict) else None
    axioms = newest_record.get("axioms_in_tension")

    convergence_verified = (
        domains == ["MIND_LOOP", "BODY_PARLIAMENT"]
        and isinstance(axioms, list)
        and len(axioms) > 0
        and verdict == "PROCEED"
    )

    ts = _parse_ts(newest_record.get("timestamp"))
    iterative_recheck_passed = False
    stale_reason: str | None = None
    if ts is not None:
        age_h = (now - ts).total_seconds() / 3600.0
        iterative_recheck_passed = 0 <= age_h <= freshness_window_h
        if not iterative_recheck_passed:
            stale_reason = (
                f"seal age {round(age_h, 3)}h exceeds {freshness_window_h}h freshness window"
            )

    hold_reason: str | None = None
    if not convergence_verified:
        hold_reason = "convergence criteria failed (requires MIND+BODY, axioms, PROCEED)"
    elif not iterative_recheck_passed:
        hold_reason = stale_reason or "iterative freshness check failed"

    t0_emit = hold_reason is None
    t2_hold_reason = None if architect_consent_present else "architect_consent absent"
    t2_hold = not architect_consent_present

    return ConsentResult(
        t0_emit=t0_emit,
        t2_hold=t2_hold,
        convergence_verified=convergence_verified,
        iterative_recheck_passed=iterative_recheck_passed,
        architect_consent="present" if architect_consent_present else "absent",
        gate_result="EMIT" if t0_emit else "HOLD",
        hold_reason=hold_reason,
        t2_hold_reason=t2_hold_reason,
        irreversible_relay=False,
        t2_side_effects=0,
    )


def _render_weather(root: Path = ROOT) -> str:
    proc = subprocess.run(
        ["bash", "tools/weather.sh"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "weather.sh failed")
    return proc.stdout


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def run_emitter(
    root: Path = ROOT,
    source_url: str = WORLD_BROADCASTS_URL,
    now: datetime | None = None,
    fetcher: Callable[[str], str] = _fetch_text,
    weather_renderer: Callable[[Path], str] = _render_weather,
) -> dict[str, Any]:
    now = now or _utc_now()
    pulse_dir = root / "pulse"
    diplomat_path = pulse_dir / "diplomat.jsonl"
    weather_path = pulse_dir / "weather.md"
    ledger_path = pulse_dir / "diplomat_emitter_ledger.json"
    pulse_dir.mkdir(parents=True, exist_ok=True)

    try:
        text = fetcher(source_url)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        return {
            "status": "HOLD",
            "changed": False,
            "reason": f"WORLD fetch failed: {exc}",
            "record": None,
        }

    parsed = _parse_jsonl_rows(text)
    records = [r for r in parsed if _record_has_contract_shape(r)]
    latest = _newest_record(records)
    if latest is None:
        return {
            "status": "HOLD",
            "changed": False,
            "reason": "No schema-valid D15 broadcast records found",
            "record": None,
        }

    carried_id = str(latest["broadcast_id"])
    ledger = _load_ledger(ledger_path)
    if any(entry.get("carried_broadcast_id") == carried_id for entry in ledger):
        return {
            "status": "NOOP",
            "changed": False,
            "reason": f"broadcast {carried_id} already carried (ledger idempotency)",
            "record": None,
        }
    if _cooldown_active(carried_id, now, _cooldown_hours(), ledger):
        return {
            "status": "NOOP",
            "changed": False,
            "reason": f"broadcast {carried_id} still inside cooldown window",
            "record": None,
        }

    consent = evaluate_consent_gate(latest, now=now, architect_consent_present=False)
    record = {
        "kind": "diplomat_out_breath",
        "schema": "diplomat-out-breath-v1",
        "timestamp": _iso(now),
        "emitted_at": _iso(now),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "carried_broadcast_id": carried_id,
        "carried_timestamp": _iso(_parse_ts(latest.get("timestamp"))),
        "converged_axiom": (
            latest.get("axioms_in_tension")[0]
            if isinstance(latest.get("axioms_in_tension"), list)
            and latest.get("axioms_in_tension")
            else None
        ),
        "contributing_domains": latest.get("contributing_domains"),
        "consent": {
            "convergence_verified": consent.convergence_verified,
            "architect_consent": consent.architect_consent,
            "iterative_recheck_passed": consent.iterative_recheck_passed,
            "irreversible_relay": consent.irreversible_relay,
            "gate_result": consent.gate_result,
            "hold_reason": consent.hold_reason,
            "t2_gate_result": "HOLD" if consent.t2_hold else "EMIT",
            "t2_hold_reason": consent.t2_hold_reason,
            "t2_side_effects": consent.t2_side_effects,
        },
        "source_url": source_url,
        "h1_bounded_evidence": True,
    }

    changed = False
    if consent.t0_emit or consent.gate_result == "HOLD":
        _append_jsonl(diplomat_path, record)
        _record_dispatch(carried_id, consent.gate_result, now, ledger_path)
        changed = True

    # T0 side: regenerate weather surface with cmp-style no-op discipline.
    try:
        weather = weather_renderer(root)
    except RuntimeError:
        weather = None
    if weather is not None:
        current = weather_path.read_text(encoding="utf-8") if weather_path.exists() else ""
        if weather != current:
            weather_path.write_text(weather, encoding="utf-8")
            changed = True

    return {
        "status": consent.gate_result,
        "changed": changed,
        "reason": None,
        "record": record,
        "consent": consent.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument(
        "--world-url",
        default=os.environ.get("WORLD_BROADCASTS_URL", WORLD_BROADCASTS_URL),
        help="WORLD broadcasts.jsonl URL",
    )
    args = parser.parse_args(argv)
    report = run_emitter(source_url=args.world_url)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"status={report['status']} changed={report['changed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
