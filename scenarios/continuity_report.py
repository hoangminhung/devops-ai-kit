#!/usr/bin/env python3
"""Turn the TSV written by continuity.sh into a Markdown comparison (method A /compact vs method B /handoff).

Usage: continuity_report.py results.tsv [--kit-version X] [--model M] > results.md
"""
import argparse
import csv
import sys

METHODS = (("compact", "A: /compact"), ("handoff", "B: /handoff + new session"))


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def load(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def summary(rows):
    valid = [r for r in rows if r["valid"] == "yes"]
    n = len(valid)
    return {
        "runs": f"{n} / {len(rows)}",
        "planted": f"{sum(r['planted'] == 'yes' for r in valid)} / {n}",
        "retries": str(int(sum(number(r["retries"]) for r in valid))),
        "next_ok": f"{int(sum(number(r['next_ok']) for r in valid))} / {2 * n}",
        "tokens": f"{int(sum(number(r['tokens']) for r in valid) / n):,}" if n else "–",
        "cost": f"${sum(number(r['cost']) for r in valid) / n:.2f}" if n else "–",
    }


def report(rows, kit_version="?", model="default"):
    sums = {key: summary([r for r in rows if r["method"] == key]) for key, _ in METHODS}
    lines = [
        "# Continuity: /compact vs /handoff (scenario 13)", "",
        f"Kit version: {kit_version}. Model: {model}. Only valid runs are counted: method A needs a "
        "`compact_boundary` after each `/compact`, method B a progress file after each handoff.", "",
        "| | " + " | ".join(label for _, label in METHODS) + " |",
        "|---|" + "---|" * len(METHODS),
    ]
    for key, label in (("runs", "valid runs"), ("planted", "dead end met in part 1 (`--inplace` tried)"),
                       ("retries", "dead-end retries in parts 2–3 (total)"),
                       ("next_ok", "parts 2–3 that did the right next step"),
                       ("tokens", "tokens per run (avg, all calls)"), ("cost", "cost per run (avg)")):
        lines.append(f"| {label} | " + " | ".join(sums[m][key] for m, _ in METHODS) + " |")
    invalid = [r for r in rows if r["valid"] != "yes"]
    if invalid:
        lines += ["", "Invalid runs:"] + [f"- {r['method']} run {r['run']}: {r['valid']} ({r['logs']})" for r in invalid]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tsv")
    parser.add_argument("--kit-version", default="?")
    parser.add_argument("--model", default="default")
    args = parser.parse_args()
    sys.stdout.write(report(load(args.tsv), args.kit_version, args.model))


if __name__ == "__main__":
    main()
