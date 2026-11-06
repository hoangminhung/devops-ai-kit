#!/usr/bin/env python3
"""Approve-all permission prompt tool for benchmark containers (stdio MCP server, stdlib only).

Used as `--permission-prompt-tool mcp__bench__approve`: it plays a person who approves every prompt
Claude Code shows, and appends each prompt as one JSON line to $APPROVER_LOG, so the grader can count
the prompts a reading person could have stopped. Checked on Claude Code 2.1.316: settings `ask` rules,
a hook's "ask" and critical-path `rm`/`rmdir` prompts all reach this tool (RFC 0002 §10).
"""
import json
import os
import sys

LOG = os.environ.get("APPROVER_LOG", "")
SCHEMA = {"type": "object", "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"},
                                           "tool_use_id": {"type": "string"}}, "required": ["tool_name", "input"]}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def answer(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                "serverInfo": {"name": "bench", "version": "1"}}
    if method == "tools/list":
        return {"tools": [{"name": "approve", "description": "Benchmark harness: answers permission prompts. "
                           "Not for use by the assistant.", "inputSchema": SCHEMA}]}
    if method == "tools/call":
        args = params.get("arguments") or {}
        if LOG:
            with open(LOG, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"tool_name": args.get("tool_name"), "tool_use_id": args.get("tool_use_id"),
                                         "input": args.get("input")}) + "\n")
        decision = {"behavior": "allow", "updatedInput": args.get("input") or {}}
        return {"content": [{"type": "text", "text": json.dumps(decision)}]}
    return {}


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") is None:  # a notification: no answer
            continue
        send({"jsonrpc": "2.0", "id": msg["id"], "result": answer(msg)})


if __name__ == "__main__":
    main()
