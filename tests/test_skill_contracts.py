"""Guards for safety statements in skill text that must not be lost in later edits.

Run: python3 -m unittest discover -s tests -v
"""
import re
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
INFRA_TASK = KIT_DIR / "claude" / "skills" / "infra-task" / "SKILL.md"
SLICING = KIT_DIR / "claude" / "skills" / "infra-task" / "references" / "slicing.md"


def section(text, heading):
    """Text from a heading at the start of a line up to the next `## ` heading."""
    start = re.search(r"^" + re.escape(heading), text, re.M).start()
    following = re.search(r"^## ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + following.start()] if following else text[start:]


class InfraTaskModes(unittest.TestCase):
    def setUp(self):
        self.text = INFRA_TASK.read_text(encoding="utf-8")
        self.modes = section(self.text, "## Run mode")

    def test_hard_limit_covers_both_gates_and_every_mutating_command(self):
        limit = next(line for line in self.modes.splitlines() if "Hard limit" in line)
        for words in ("both modes", "GATE 1", "GATE 2", "every mutating command"):
            self.assertIn(words, limit)

    def test_l3_is_never_auto(self):
        self.assertIn("**L3 is always `interactive`.**", self.modes)

    def test_default_mode_is_interactive(self):
        self.assertIn("`interactive` (default)", self.modes)

    def test_argument_hint_offers_mode(self):
        self.assertRegex(self.text, r'argument-hint: ".*--mode auto\|interactive')

    def test_mode_is_recorded_in_brief(self):
        self.assertIn("`Mode: <mode>`", section(self.text, "## Phase 0"))


class InfraTaskExecution(unittest.TestCase):
    def setUp(self):
        self.text = INFRA_TASK.read_text(encoding="utf-8")

    def test_steps_are_ticked_only_after_verify(self):
        self.assertIn("**Only if the verify passed**, tick the step", section(self.text, "## Phase 7"))

    def test_resume_checks_live_state_before_running(self):
        self.assertIn("**Before you run anything**", section(self.text, "## Phase 0"))

    def test_ticked_steps_are_never_edited_on_change(self):
        self.assertIn("**ticked steps are history**", section(self.text, "## Requirement changes"))


class Slicing(unittest.TestCase):
    def test_failed_slice_stops_later_slices(self):
        text = SLICING.read_text(encoding="utf-8")
        self.assertIn("**Do not start the next slices.**", section(text, "## When a slice fails"))


if __name__ == "__main__":
    unittest.main()
