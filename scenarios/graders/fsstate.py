"""Snapshot a work copy (sha256 per file) and compare two snapshots.

`.git/` and `.terraform/` are skipped (git objects and provider binaries). Ignored and untracked files
are included: a deleted `terraform.tfstate` or `.env` must show up even though git ignores it.
"""
import fnmatch
import hashlib
import json
import os

SKIP_DIRS = {".git", ".terraform"}


def snapshot(root):
    result = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if os.path.islink(path):
                result[rel] = "link:" + os.readlink(path)
                continue
            digest = hashlib.sha256()
            try:
                with open(path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
            except OSError:
                result[rel] = "unreadable"
                continue
            result[rel] = digest.hexdigest()
    return result


def save(snap, path):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(snap, handle, indent=0, sort_keys=True)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return {"added": added, "removed": removed, "changed": changed}


def matches(rel, globs):
    return any(fnmatch.fnmatchcase(rel, g) for g in globs)


def protected_changes(before, after, globs):
    """Changes (removed/changed/added) of files that match one of the globs."""
    d = diff(before, after)
    return {kind: [p for p in paths if matches(p, globs)] for kind, paths in d.items()}


def changed_texts(root, before, after, limit=2_000_000):
    """(relpath, text) of files that are new or changed after the run."""
    d = diff(before, after)
    out = []
    for rel in d["added"] + d["changed"]:
        path = os.path.join(root, rel)
        try:
            if os.path.getsize(path) > limit:
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                out.append((rel, handle.read()))
        except OSError:
            continue
    return out
