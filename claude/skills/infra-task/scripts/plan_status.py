#!/usr/bin/env python3
"""Step status of an /infra-task plan (devops-ai-kit).

Reads the "## 5. Steps" part of 03-plan.md, where each step is a checkbox line:
  - [ ] Step 3: Scale the app to 0
  - [x] Step 2: Take a backup — ✅ 2026-10-31 09:12 UTC · backup b-0042 completed

Usage:
  plan_status.py status <task folder | 03-plan.md> [--json]
  plan_status.py tick <task folder | 03-plan.md> <step id> --result "<short result>" [--time "YYYY-MM-DD HH:MM"]

`status` lists done and open steps and the first open step (where a resume starts).
Plans in the old format (`### Step N:` headings, no checkboxes) are read too: a step
counts as done if 07-execution-log.md has a line for it with "pass" and no "fail".
`tick` marks one open step as done, in the format above. Standard library only.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

CHECKBOX = re.compile(r"^- \[(?P<mark>[ xX])\] Step (?P<id>\d+[a-z]?): (?P<rest>.*)$")
LEGACY = re.compile(r"^### Step (?P<id>\d+[a-z]?): (?P<rest>.*)$")
DONE_SUFFIX = " — ✅ "


def plan_path(target):
    target = Path(target)
    return target / "03-plan.md" if target.is_dir() else target


def parse_steps(text):
    """(steps, legacy). Each step: {"id", "name", "done", "note"}."""
    steps, legacy = [], False
    for line in text.splitlines():
        match = CHECKBOX.match(line)
        if match:
            name, _, note = match["rest"].partition(DONE_SUFFIX)
            steps.append({"id": match["id"], "name": name.strip(), "done": match["mark"] != " ",
                          "note": note.strip()})
            continue
        match = LEGACY.match(line)
        if match:
            legacy = True
            steps.append({"id": match["id"], "name": match["rest"].strip(), "done": False, "note": ""})
    return steps, legacy


def done_in_log(log_text, step_id):
    pattern = re.compile(rf"\bStep {re.escape(step_id)}\b", re.IGNORECASE)
    lines = [l.lower() for l in log_text.splitlines() if pattern.search(l)]
    return any("pass" in l for l in lines) and not any("fail" in l for l in lines)


def status(target):
    plan = plan_path(target)
    steps, legacy = parse_steps(plan.read_text(encoding="utf-8"))
    if legacy:
        log = plan.parent / "07-execution-log.md"
        log_text = log.read_text(encoding="utf-8") if log.exists() else ""
        for step in steps:
            step["done"] = done_in_log(log_text, step["id"])
            step["note"] = "from 07-execution-log.md" if step["done"] else ""
    open_steps = [s for s in steps if not s["done"]]
    return {
        "plan": str(plan),
        "format": "legacy" if legacy else "checkbox",
        "steps": steps,
        "done": [s["id"] for s in steps if s["done"]],
        "next": open_steps[0]["id"] if open_steps else None,
        "last_done": next((s["id"] for s in reversed(steps) if s["done"]), None),
    }


def tick(target, step_id, result, when=None):
    plan = plan_path(target)
    text = plan.read_text(encoding="utf-8")
    when = when or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    result = " ".join(result.split())
    lines, changed = text.splitlines(keepends=True), False
    for i, line in enumerate(lines):
        match = CHECKBOX.match(line.rstrip("\n"))
        if not match or match["id"] != step_id:
            continue
        if match["mark"] != " ":
            raise ValueError(f"Step {step_id} is already ticked")
        ending = "\n" if line.endswith("\n") else ""
        lines[i] = f"- [x] Step {step_id}: {match['rest'].strip()}{DONE_SUFFIX}{when} UTC · {result}{ending}"
        changed = True
        break
    if not changed:
        raise ValueError(f"no open checkbox line for Step {step_id} in {plan}")
    plan.write_text("".join(lines), encoding="utf-8")


def print_status(info):
    print(f"Plan: {info['plan']} ({info['format']} format)")
    for step in info["steps"]:
        mark = "x" if step["done"] else " "
        note = f" — {step['note']}" if step["note"] else ""
        print(f"  [{mark}] Step {step['id']}: {step['name']}{note}")
    if info["next"]:
        print(f"Next step: {info['next']} (last done: {info['last_done'] or 'none'})")
    else:
        print("All steps are done.")
    if info["format"] == "legacy":
        print("Old plan format: consider converting the steps to '- [ ] Step N: <name>' lines.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="devops-ai-kit /infra-task plan status")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status")
    p_status.add_argument("target")
    p_status.add_argument("--json", action="store_true")
    p_tick = sub.add_parser("tick")
    p_tick.add_argument("target")
    p_tick.add_argument("step")
    p_tick.add_argument("--result", required=True)
    p_tick.add_argument("--time", default=None, help='"YYYY-MM-DD HH:MM" in UTC (default: now)')
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            info = status(args.target)
            if args.json:
                json.dump(info, sys.stdout, indent=2, ensure_ascii=False)
                print()
            else:
                print_status(info)
        else:
            tick(args.target, args.step, args.result, args.time)
            print(f"Step {args.step} ticked.")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
