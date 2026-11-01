#!/usr/bin/env python3
"""Compare Kubernetes Secrets without printing their values (devops-ai-kit).

The kit never lets the AI print a secret value: it would end up in the chat, in
the session transcript on disk and at the model provider. Most of the time the
real need is to *compare* ("is the password the same on both clusters?", "does
the Secret hold the value I expect?"). This script reads the Secret itself and
prints only key names, sizes, a rough kind and match / differ results.

No hashes are printed: a hash of a short password can be guessed offline.

Usage:
  secret_fingerprint.py SPEC                     # key names, sizes, kinds
  secret_fingerprint.py SPEC OTHER_SPEC          # compare two Secrets key by key
  secret_fingerprint.py SPEC --env KEY=ENV_VAR   # compare one key with a value the user exported

SPEC is [context:]namespace/name, for example `aks-prod-ro:shop/db-credentials`.
Exit code: 0 when everything compared is equal (or nothing was compared), 1 when
something differs or is missing, 2 on errors (bad SPEC, kubectl failed).
"""
import argparse
import base64
import hmac
import json
import os
import re
import subprocess
import sys

# The context may hold ":" and "/" (EKS: arn:aws:eks:...:cluster/name); namespace and name never do.
SPEC_RE = re.compile(r"^(?:(?P<context>\S+):)?(?P<namespace>[a-z0-9-]+)/(?P<name>[a-z0-9.-]+)$")


class SpecError(Exception):
    pass


def parse_spec(text):
    match = SPEC_RE.match(text)
    if not match:
        raise SpecError(f"bad SPEC {text!r}: use [context:]namespace/name")
    return match.group("context"), match.group("namespace"), match.group("name")


def read_secret(spec):
    """Decoded data of a Secret as {key: bytes}. kubectl errors are passed on, never the values."""
    context, namespace, name = parse_spec(spec)
    cmd = ["kubectl"] + (["--context", context] if context else []) + ["-n", namespace, "get", "secret", name, "-o", "json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SpecError(f"{spec}: cannot run kubectl ({exc})")
    if out.returncode != 0:
        raise SpecError(f"{spec}: {out.stderr.strip() or 'kubectl failed'}")
    data = json.loads(out.stdout).get("data") or {}
    return {key: base64.b64decode(value or "") for key, value in data.items()}


def kind(value):
    if not value:
        return "empty"
    if value.lstrip().startswith(b"-----BEGIN"):
        return "PEM"
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    try:
        json.loads(text)
        return "JSON"
    except ValueError:
        pass
    note = " (ends with newline)" if text.endswith("\n") else ""
    return f"text{note}"


def same(a, b):
    return hmac.compare_digest(a, b)


def compare(a, b):
    """'match', 'differ', or 'differ (only a trailing newline)'."""
    if same(a, b):
        return "match"
    if same(a.rstrip(b"\r\n"), b.rstrip(b"\r\n")):
        return "differ (only a trailing newline)"
    return "differ"


def describe(spec, data):
    lines = [f"{spec}: {len(data)} key(s)"]
    for key in sorted(data):
        lines.append(f"  {key}: {len(data[key])} bytes, {kind(data[key])}")
    return lines, True


def compare_secrets(spec_a, a, spec_b, b):
    lines, ok = [f"compare {spec_a} <-> {spec_b}"], True
    for key in sorted(set(a) | set(b)):
        if key not in b:
            result, ok = f"only in {spec_a}", False
        elif key not in a:
            result, ok = f"only in {spec_b}", False
        else:
            result = compare(a[key], b[key])
            ok = ok and result == "match"
            result += f" ({len(a[key])} / {len(b[key])} bytes)"
        lines.append(f"  {key}: {result}")
    return lines, ok


def compare_env(spec, data, pairs):
    lines, ok = [], True
    for pair in pairs:
        key, sep, var = pair.partition("=")
        if not sep or not key or not var:
            raise SpecError(f"bad --env {pair!r}: use KEY=ENV_VAR")
        if var not in os.environ:
            lines.append(f"  {key}: env var {var} is not set")
            ok = False
        elif key not in data:
            lines.append(f"  {key}: not in {spec}")
            ok = False
        else:
            result = compare(data[key], os.environ[var].encode("utf-8"))
            ok = ok and result == "match"
            lines.append(f"  {key} vs ${var}: {result}")
    return lines, ok


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare Kubernetes Secrets without printing values.")
    parser.add_argument("spec")
    parser.add_argument("other", nargs="?")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=ENV_VAR")
    args = parser.parse_args(argv)
    try:
        data = read_secret(args.spec)
        lines, ok = describe(args.spec, data)
        if args.other:
            more, ok = compare_secrets(args.spec, data, args.other, read_secret(args.other))
            lines += more
        if args.env:
            more, env_ok = compare_env(args.spec, data, args.env)
            lines += more
            ok = ok and env_ok
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
