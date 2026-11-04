#!/usr/bin/env python3
"""Copy a refreshed bench login from the container's config copy back to the bench config dir.

    copy_back.py <copy>/.credentials.json <bench config dir>

The copy was writable by the session (approve-all), so its content is untrusted input: it is taken only
if it is a regular file (not a symlink, FIFO or device; opened with O_NOFOLLOW), at most 64 KiB, and a
JSON object with a "claudeAiOauth" object. It replaces the bench file by an atomic rename (mode 600).
Anything else is ignored. Nothing is printed except the reason it was ignored.
"""
import json
import os
import stat
import sys
import tempfile

LIMIT = 64 * 1024


def read_untrusted(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            return None
        data = handle.read(LIMIT + 1)
    if len(data) > LIMIT:
        return None
    try:
        doc = json.loads(data)
    except ValueError:
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("claudeAiOauth"), dict):
        return None
    return data


def main(src, config):
    data = read_untrusted(src)
    if data is None:
        print("copy_back: credential copy ignored (not a plain, valid credentials file)", file=sys.stderr)
        return 0
    target = os.path.join(config, ".credentials.json")
    try:
        with open(target, "rb") as handle:
            if handle.read() == data:
                return 0
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=config, prefix=".credentials.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
