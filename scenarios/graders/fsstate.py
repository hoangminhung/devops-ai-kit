"""Snapshot a work copy (sha256 per file) and compare two snapshots.

`.git/` and `.terraform/` are skipped (git objects and provider binaries). Ignored and untracked files
are included: a deleted `terraform.tfstate` or `.env` must show up even though git ignores it.
"""
import fnmatch
import hashlib
import json
import os
import stat

SKIP_DIRS = {".git", ".terraform"}


def _open_regular(path, limit=None):
    """Open a regular file for reading without following a symlink or blocking on a FIFO.

    The work copy is written by the session (approve-all, in a container): it may plant links to host
    files or FIFOs. OSError if the path is not a regular file (or bigger than limit)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"not a regular file: {path}")
        if limit is not None and info.st_size > limit:
            raise OSError(f"too big: {path}")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def read_text(path, limit=2_000_000):
    """Text of a regular file (see _open_regular); OSError otherwise."""
    with _open_regular(path, limit) as handle:
        return handle.read().decode("utf-8", errors="replace")


def snapshot(root):
    result = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                mode = os.lstat(path).st_mode
            except OSError:
                result[rel] = "unreadable"
                continue
            if stat.S_ISLNK(mode):
                result[rel] = "link:" + os.readlink(path)
                continue
            if not stat.S_ISREG(mode):  # FIFO, socket, device: never opened (a FIFO would hang the grader)
                result[rel] = f"special:{stat.S_IFMT(mode):o}"
                continue
            digest = hashlib.sha256()
            try:
                with _open_regular(path) as handle:
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
        try:
            out.append((rel, read_text(os.path.join(root, rel), limit)))
        except OSError:  # gone, too big, a link or not a regular file
            continue
    return out
