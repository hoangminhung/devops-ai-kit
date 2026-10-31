"""Tests for claude/skills/infra-task/scripts/plan_status.py.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = KIT_DIR / "claude" / "skills" / "infra-task" / "scripts" / "plan_status.py"
TEMPLATE = KIT_DIR / "claude" / "skills" / "infra-task" / "references" / "plan-template.md"

spec = importlib.util.spec_from_file_location("plan_status", SCRIPT)
plan_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_status)

PLAN = """# Plan: demo

## 5. Steps

- [x] Step 1: Take a backup — ✅ 2026-10-31 09:00 UTC · backup b-1 completed
  - **Verify:** `velero backup get b-1` → expected `Completed`
- [ ] Step 2: Scale the app to 0
  - **Verify:** `kubectl get deploy web` → expected `0/0`
- [ ] Step 3: Upgrade the chart
- [ ] Step 3b: Fix the values found in review

## 6. Point of no return
"""

LEGACY_PLAN = """## 5. Steps

### Step 1: Take a backup
### Step 2: Scale the app to 0
### Step 3: Upgrade
"""

LOG = """| time | step | result |
| 09:00 | Step 1 backup | pass |
| 09:10 | Step 2 scale | fail: pods still running |
| 09:20 | Step 2 scale (retry) | pass |
"""


class PlanStatusTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.task = Path(self.tmp.name)
        (self.task / "03-plan.md").write_text(PLAN, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = plan_status.main(list(args))
        return code, out.getvalue(), err.getvalue()


class Status(PlanStatusTestCase):
    def test_finds_done_and_next_step(self):
        info = plan_status.status(self.task)
        self.assertEqual(info["format"], "checkbox")
        self.assertEqual([s["id"] for s in info["steps"]], ["1", "2", "3", "3b"])
        self.assertEqual(info["done"], ["1"])
        self.assertEqual(info["next"], "2")
        self.assertEqual(info["last_done"], "1")
        self.assertEqual(info["steps"][0]["name"], "Take a backup")
        self.assertIn("backup b-1 completed", info["steps"][0]["note"])

    def test_accepts_plan_file_path(self):
        self.assertEqual(plan_status.status(self.task / "03-plan.md")["next"], "2")

    def test_all_done(self):
        text = PLAN.replace("- [ ]", "- [x]")
        (self.task / "03-plan.md").write_text(text, encoding="utf-8")
        self.assertIsNone(plan_status.status(self.task)["next"])

    def test_legacy_plan_uses_execution_log(self):
        (self.task / "03-plan.md").write_text(LEGACY_PLAN, encoding="utf-8")
        (self.task / "07-execution-log.md").write_text(LOG, encoding="utf-8")
        info = plan_status.status(self.task)
        self.assertEqual(info["format"], "legacy")
        self.assertEqual(info["done"], ["1"])  # Step 2 has a "fail" line, so it is not trusted as done
        self.assertEqual(info["next"], "2")

    def test_legacy_plan_without_log(self):
        (self.task / "03-plan.md").write_text(LEGACY_PLAN, encoding="utf-8")
        self.assertEqual(plan_status.status(self.task)["next"], "1")

    def test_cli_json_and_text(self):
        code, out, _ = self.cli("status", str(self.task), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["next"], "2")
        code, out, _ = self.cli("status", str(self.task))
        self.assertIn("Next step: 2 (last done: 1)", out)


class Tick(PlanStatusTestCase):
    def test_tick_marks_step_with_time_and_result(self):
        plan_status.tick(self.task, "2", "replicas  0/0\n after 40s", when="2026-10-31 09:30")
        text = (self.task / "03-plan.md").read_text(encoding="utf-8")
        self.assertIn("- [x] Step 2: Scale the app to 0 — ✅ 2026-10-31 09:30 UTC · replicas 0/0 after 40s\n", text)
        self.assertIn("  - **Verify:** `kubectl get deploy web`", text)  # body lines untouched
        self.assertEqual(plan_status.status(self.task)["next"], "3")

    def test_tick_letter_step(self):
        plan_status.tick(self.task, "3b", "ok", when="2026-10-31 10:00")
        self.assertIn("3b", plan_status.status(self.task)["done"])

    def test_tick_twice_is_an_error(self):
        with self.assertRaises(ValueError):
            plan_status.tick(self.task, "1", "again")

    def test_tick_unknown_step_is_an_error(self):
        code, _, err = self.cli("tick", str(self.task), "9", "--result", "x")
        self.assertEqual(code, 1)
        self.assertIn("no open checkbox line for Step 9", err)

    def test_tick_does_not_match_step_prefix(self):
        plan_status.tick(self.task, "3", "done", when="2026-10-31 10:00")
        info = plan_status.status(self.task)
        self.assertEqual(info["done"], ["1", "3"])
        self.assertEqual(info["next"], "2")


OVERVIEW = """# Plan: monitoring stack

## 5. Slices

- [x] Slice 01: Metrics — ✅ 2026-10-31 10:00 UTC · Prometheus up, targets green
- [ ] Slice 02: Logs (Alloy + Loki)
- [ ] Slice 03: Alert routing
"""

SLICE_02 = """## 5. Steps

- [x] Step 1: Install Loki — ✅ 2026-10-31 11:00 UTC · loki-0 Ready
- [ ] Step 2: Install Alloy
"""


class Slices(PlanStatusTestCase):
    def setUp(self):
        super().setUp()
        (self.task / "03-plan.md").write_text(OVERVIEW, encoding="utf-8")
        for folder, text in (("01-metrics", SLICE_02.replace("- [ ]", "- [x]")), ("02-logs", SLICE_02)):
            (self.task / "slices" / folder).mkdir(parents=True)
            (self.task / "slices" / folder / "03-plan.md").write_text(text, encoding="utf-8")

    def test_status_reports_slices_and_next_step_inside_next_slice(self):
        info = plan_status.status(self.task)
        self.assertEqual([s["id"] for s in info["slices"]], ["01", "02", "03"])
        self.assertEqual(info["next_slice"], "02")
        self.assertEqual(info["next"], "2")
        self.assertEqual(info["slices"][1]["folder"], "slices/02-logs")
        self.assertIsNone(info["slices"][2]["folder"])  # not planned in detail yet

    def test_slice_without_folder_starts_at_its_planning(self):
        plan_status.tick(self.task / "slices/02-logs", "2", "alloy ok", when="2026-10-31 12:00")
        plan_status.tick(self.task, "02", "logs flowing", when="2026-10-31 12:05", kind="Slice")
        info = plan_status.status(self.task)
        self.assertEqual(info["next_slice"], "03")
        self.assertIsNone(info["next"])

    def test_cannot_tick_slice_with_open_steps(self):
        with self.assertRaisesRegex(ValueError, "Step 2 .* not ticked"):
            plan_status.tick(self.task, "02", "too early", kind="Slice")

    def test_cli_tick_slice(self):
        plan_status.tick(self.task / "slices/02-logs", "2", "ok", when="2026-10-31 12:00")
        code, out, _ = self.cli("tick", str(self.task), "02", "--slice", "--result", "logs flowing")
        self.assertEqual(code, 0)
        self.assertIn("- [x] Slice 02: Logs (Alloy + Loki) — ✅", (self.task / "03-plan.md").read_text(encoding="utf-8"))

    def test_status_text_shows_slices(self):
        code, out, _ = self.cli("status", str(self.task))
        self.assertIn("[ ] Slice 02: Logs (Alloy + Loki) (slices/02-logs)", out)
        self.assertIn("Next: Slice 02, Step 2", out)


class Template(unittest.TestCase):
    def test_plan_template_uses_checkbox_steps(self):
        steps, legacy = plan_status.parse_steps(TEMPLATE.read_text(encoding="utf-8"))
        self.assertFalse(legacy)
        self.assertGreaterEqual(len(steps), 1)
        self.assertEqual(steps[0]["id"], "1")


if __name__ == "__main__":
    unittest.main()
