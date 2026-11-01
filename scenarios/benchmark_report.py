#!/usr/bin/env python3
"""Turn the TSV written by benchmark.sh into a Markdown comparison (without kit vs with kit).

Usage: benchmark_report.py results.tsv [--kit-version X] > results.md
"""
import argparse
import csv
import sys
from collections import defaultdict


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def load(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def summary(rows):
    ran = [r for r in rows if r["result"] in ("PASS", "FAIL")]
    costs = [number(r["cost"]) for r in ran if number(r["cost"]) is not None]
    contexts = [number(r["context"]) for r in ran if number(r["context"])]
    prompts = [number(r["prompts"]) for r in ran if number(r["prompts"]) is not None]
    return {
        "errors": sum(r["result"] == "ERROR" for r in rows),
        "pass": sum(r["result"] == "PASS" for r in ran),
        "ran": len(ran),
        "prompts": int(sum(prompts)),
        "cost": sum(costs),
        "context": int(sum(contexts) / len(contexts)) if contexts else 0,
    }


def cell(row):
    if not row:
        return "–"
    if row["result"] == "SKIP":
        return "skip"
    cost = number(row["cost"])
    return f"{row['result']} · {row['prompts'] or '?'} prompts · ${cost:.2f}" if cost is not None else row["result"]


def report(rows, kit_version="?"):
    by = defaultdict(dict)
    for r in rows:
        by[(r["model"], r["scenario"])][r["mode"]] = r
    models = sorted({r["model"] for r in rows})
    out = ["# Benchmark: without the kit vs with the kit", "",
           f"Kit version: {kit_version}. \"With kit\" is the full install: rules, skills, agents, hook **and** "
           "permission rules (the allow rules alone remove many prompts).",
           "\"prompts\" = tool calls that were blocked or would have waited for a person "
           "(in `claude -p` every confirm dialog becomes a denial). ERROR = the run did not produce a log "
           "(see errors.log); it is not counted as passed or failed.", ""]
    for model in models:
        rows_m = [r for r in rows if r["model"] == model]
        base = summary([r for r in rows_m if r["mode"] == "nokit"])
        kit = summary([r for r in rows_m if r["mode"] == "kit"])
        out += [f"## {model}", "",
                "| | without kit | with kit |", "|---|---|---|",
                f"| scenarios passed | {base['pass']} / {base['ran']} | {kit['pass']} / {kit['ran']} |",
                f"| prompts (total) | {base['prompts']} | {kit['prompts']} |",
                f"| cost (total, USD) | {base['cost']:.2f} | {kit['cost']:.2f} |",
                f"| context of the first request (avg tokens) | {base['context']} | {kit['context']} |",
                f"| errors (not counted) | {base['errors']} | {kit['errors']} |",
                "", "| scenario | without kit | with kit |", "|---|---|---|"]
        for nn in sorted({r["scenario"] for r in rows_m}):
            pair = by[(model, nn)]
            out.append(f"| {nn} | {cell(pair.get('nokit'))} | {cell(pair.get('kit'))} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tsv")
    parser.add_argument("--kit-version", default="?")
    args = parser.parse_args()
    print(report(load(args.tsv), args.kit_version))
