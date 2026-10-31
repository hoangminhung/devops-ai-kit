#!/usr/bin/env python3
"""Step status of an /infra-task plan (devops-ai-kit).

Reads 03-plan.md, where each step is a checkbox line:
  - [ ] Step 3: Scale the app to 0
  - [x] Step 2: Take a backup — ✅ 2026-10-31 09:12 UTC · backup b-0042 completed
A sliced task (references/slicing.md) has slice lines in the top 03-plan.md instead,
and one folder per slice with its own 03-plan.md of steps:
  - [ ] Slice 02: Logs (Alloy + Loki)        → slices/02-<name>/03-plan.md

Usage:
  plan_status.py status <task or slice folder | 03-plan.md> [--json]
  plan_status.py tick <task or slice folder | 03-plan.md> <id> [--slice] --result "<short result>" [--time "YYYY-MM-DD HH:MM"]

`status` lists done and open steps (and slices) and where a resume starts.
Plans in the old format (`### Step N:` headings, no checkboxes) are read too: a step
counts as done if 07-execution-log.md has a line for it with "pass" and no "fail".
`tick` marks one open step (or, with --slice, one slice whose steps are all done)
as done, in the format above. Standard library only.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

CHECKBOX = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<kind>Step|Slice) (?P<id>\d+[a-z]?): (?P<rest>.*)$")
LEGACY = re.compile(r"^### Step (?P<id>\d+[a-z]?): (?P<rest>.*)$")
DONE_SUFFIX = " — ✅ "


def plan_path(target):
    target = Path(target)
    return target / "03-plan.md" if target.is_dir() else target


def parse_steps(text, kind="Step"):
    """(items, legacy) for one kind of checkbox line. Each item: {"id", "name", "done", "note"}."""
    steps, legacy = [], False
    for line in text.splitlines():
        match = CHECKBOX.match(line)
        if match and match["kind"] == kind:
            name, _, note = match["rest"].partition(DONE_SUFFIX)
            steps.append({"id": match["id"], "name": name.strip(), "done": match["mark"] != " ",
                          "note": note.strip()})
            continue
        match = LEGACY.match(line) if kind == "Step" else None
        if match:
            legacy = True
            steps.append({"id": match["id"], "name": match["rest"].strip(), "done": False, "note": ""})
    return steps, legacy


def done_in_log(log_text, step_id):
    pattern = re.compile(rf"\bStep {re.escape(step_id)}\b", re.IGNORECASE)
    lines = [l.lower() for l in log_text.splitlines() if pattern.search(l)]
    return any("pass" in l for l in lines) and not any("fail" in l for l in lines)


def slice_folder(task_dir, slice_id):
    folders = sorted(p for p in (task_dir / "slices").glob(f"{slice_id}-*") if p.is_dir())
    return folders[0] if folders else None


def status(target):
    plan = plan_path(target)
    text = plan.read_text(encoding="utf-8")
    slices, _ = parse_steps(text, kind="Slice")
    if slices:
        return sliced_status(plan, slices)
    steps, legacy = parse_steps(text)
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


def sliced_status(plan, slices):
    task_dir = plan.parent
    for item in slices:
        folder = slice_folder(task_dir, item["id"])
        item["folder"] = folder.relative_to(task_dir).as_posix() if folder else None
        item["detail"] = status(folder) if folder and (folder / "03-plan.md").exists() else None
    open_slices = [s for s in slices if not s["done"]]
    current = open_slices[0] if open_slices else None
    return {
        "plan": str(plan),
        "format": "sliced",
        "slices": slices,
        "done": [s["id"] for s in slices if s["done"]],
        "next_slice": current["id"] if current else None,
        "next": current["detail"]["next"] if current and current["detail"] else None,
        "last_done": next((s["id"] for s in reversed(slices) if s["done"]), None),
    }


def tick(target, step_id, result, when=None, kind="Step"):
    plan = plan_path(target)
    if kind == "Slice":
        folder = slice_folder(plan.parent, step_id)
        if folder and (folder / "03-plan.md").exists():
            open_steps = [s["id"] for s in status(folder)["steps"] if not s["done"]]
            if open_steps:
                raise ValueError(f"Slice {step_id}: Step {open_steps[0]} (and {len(open_steps) - 1} more) not ticked")
    text = plan.read_text(encoding="utf-8")
    when = when or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    result = " ".join(result.split())
    lines, changed = text.splitlines(keepends=True), False
    for i, line in enumerate(lines):
        match = CHECKBOX.match(line.rstrip("\n"))
        if not match or match["id"] != step_id or match["kind"] != kind:
            continue
        if match["mark"] != " ":
            raise ValueError(f"{kind} {step_id} is already ticked")
        ending = "\n" if line.endswith("\n") else ""
        lines[i] = f"- [x] {kind} {step_id}: {match['rest'].strip()}{DONE_SUFFIX}{when} UTC · {result}{ending}"
        changed = True
        break
    if not changed:
        raise ValueError(f"no open checkbox line for {kind} {step_id} in {plan}")
    plan.write_text("".join(lines), encoding="utf-8")


def print_status(info):
    print(f"Plan: {info['plan']} ({info['format']} format)")
    if info["format"] == "sliced":
        for item in info["slices"]:
            mark = "x" if item["done"] else " "
            where = item["folder"] or "not planned yet"
            print(f"  [{mark}] Slice {item['id']}: {item['name']} ({where})")
        if info["next_slice"] is None:
            print("All slices are done.")
        elif info["next"]:
            print(f"Next: Slice {info['next_slice']}, Step {info['next']}")
        else:
            print(f"Next: Slice {info['next_slice']} (plan it, or tick it if all its steps are done)")
        return
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
    p_tick.add_argument("--slice", action="store_true", help="tick a slice line in the top plan")
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
            kind = "Slice" if args.slice else "Step"
            tick(args.target, args.step, args.result, args.time, kind=kind)
            print(f"{kind} {args.step} ticked.")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
