#!/usr/bin/env python3
"""Re-grade every graded trial of a benchmark TSV from its stored log, with the current check blocks.

    scenarios/regrade_tsv.py <benchmark>.tsv [--scenarios "15 23"]

No model call (free): runs `run-headless.sh --grade-only <log> <NN>` for each PASS/FAIL row and updates
result, p_pass, p_total, o_pass and o_total in place (the old file is kept as <tsv>.orig once). ERROR
and SKIP rows are left as they are. Then rebuild the report:
    scenarios/benchmark_report.py <benchmark>.tsv --kit-version X > <benchmark>.md
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LINE = re.compile(r"^(\d\d) (PASS|FAIL|ERROR)(?: P=(\d+)/(\d+) O=(\d+)/(\d+))?")


def regrade(log, nn):
    out = subprocess.run([os.path.join(HERE, "run-headless.sh"), "--grade-only", log, nn],
                         capture_output=True, text=True, timeout=600).stdout
    for line in out.splitlines():
        match = LINE.match(line)
        if match and match.group(1) == nn:
            return match
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tsv")
    parser.add_argument("--scenarios", default="")
    args = parser.parse_args()
    only = set(args.scenarios.split())
    with open(args.tsv, encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    changed = 0
    for row in rows:
        if row["result"] not in ("PASS", "FAIL") or not row.get("log") or (only and row["scenario"] not in only):
            continue
        match = regrade(row["log"], row["scenario"])
        if not match:
            print(f"{row['scenario']} {row['log']}: no result line, row left as it was", file=sys.stderr)
            continue
        new = {"result": match.group(2)}
        if match.group(3) is not None:
            new.update(p_pass=match.group(3), p_total=match.group(4), o_pass=match.group(5), o_total=match.group(6))
        if any(row.get(k) != v for k, v in new.items()):
            print(f"{row['mode']} {row['model']} {row['scenario']} run {row['run']}: "
                  f"{row['result']} O={row['o_pass']}/{row['o_total']} -> {new['result']} "
                  f"O={new.get('o_pass', '?')}/{new.get('o_total', '?')}", file=sys.stderr)
            row.update(new)
            changed += 1
    if not os.path.exists(args.tsv + ".orig"):
        shutil.copyfile(args.tsv, args.tsv + ".orig")
    with open(args.tsv, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{changed} row(s) changed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
