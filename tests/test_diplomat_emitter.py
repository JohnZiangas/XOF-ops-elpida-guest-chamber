from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".github" / "scripts" / "diplomat_emitter.py"
SPEC = importlib.util.spec_from_file_location("diplomat_emitter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _fixture_world_jsonl(ts: str) -> str:
    rows = [
        {
            "type": "D15_CONSTITUTIONAL_BROADCAST",
            "broadcast_id": "older-1",
            "timestamp": "2026-06-22T03:00:00Z",
            "d15_output": "old",
            "axioms_in_tension": ["A1"],
            "contributing_domains": ["MIND_LOOP", "BODY_PARLIAMENT"],
            "governance": {"verdict": "PROCEED"},
        },
        {
            "type": "D15_CONSTITUTIONAL_BROADCAST",
            "broadcast_id": "42b9a411117a",
            "timestamp": ts,
            "d15_output": "new",
            "axioms_in_tension": ["A5"],
            "contributing_domains": ["MIND_LOOP", "BODY_PARLIAMENT"],
            "governance": {"verdict": "PROCEED"},
        },
    ]
    return "\n".join(json.dumps(r) for r in rows) + "\n"


class DiplomatEmitterTests(unittest.TestCase):
    def test_expected_predicate_is_deterministic_2_of_2(self) -> None:
        now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
        newest = {
            "type": "D15_CONSTITUTIONAL_BROADCAST",
            "broadcast_id": "42b9a411117a",
            "timestamp": "2026-06-23T07:56:40Z",
            "d15_output": "seal",
            "axioms_in_tension": ["A5"],
            "contributing_domains": ["MIND_LOOP", "BODY_PARLIAMENT"],
            "governance": {"verdict": "PROCEED"},
        }

        first = MODULE.evaluate_consent_gate(
            newest,
            now=now,
            architect_consent_present=False,
        ).as_dict()
        second = MODULE.evaluate_consent_gate(
            newest,
            now=now,
            architect_consent_present=False,
        ).as_dict()

        self.assertEqual(first, second)
        self.assertTrue(first["t0_emit"])
        self.assertTrue(first["t2_hold"])
        self.assertEqual(first["t2_side_effects"], 0)
        self.assertIn("architect_consent", first["t2_hold_reason"])

    def test_run_emitter_writes_t0_record_and_t2_hold(self) -> None:
        now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
        payload = _fixture_world_jsonl("2026-06-23T07:56:40Z")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pulse").mkdir(parents=True, exist_ok=True)

            def fetcher(_: str) -> str:
                return payload

            def render_weather(_: Path) -> str:
                return "weather\n"

            report = MODULE.run_emitter(
                root=root,
                now=now,
                source_url="https://example.invalid/d15/broadcasts.jsonl",
                fetcher=fetcher,
                weather_renderer=render_weather,
            )

            self.assertEqual(report["status"], "EMIT")
            self.assertTrue(report["changed"])
            self.assertEqual(report["consent"]["t2_side_effects"], 0)

            lines = (root / "pulse" / "diplomat.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["schema"], "diplomat-out-breath-v1")
            self.assertEqual(row["timestamp"], "2026-06-23T12:00:00Z")
            self.assertEqual(row["timestamp"], row["emitted_at"])
            self.assertEqual(row["carried_broadcast_id"], "42b9a411117a")
            self.assertEqual(row["consent"]["gate_result"], "EMIT")
            self.assertEqual(row["consent"]["t2_gate_result"], "HOLD")
            self.assertIn("architect_consent", row["consent"]["t2_hold_reason"])


if __name__ == "__main__":
    unittest.main()
