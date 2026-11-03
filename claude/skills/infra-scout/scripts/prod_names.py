#!/usr/bin/env python3
"""Show which target names the kit's hook treats as production (devops-ai-kit).

The hook denies changes on production by matching NAMES (kube context, kubeconfig
file name, namespace, Terraform workspace or folder, subscription / profile /
project) against a regex. A project whose production context is called
`k8s-hn-01` or `default` is not protected until the pattern names it.

The script uses the same regex as the installed hook: DEVOPS_KIT_PROD_PATTERN
from the environment (the kit puts it there through settings.json), or the
hook's default. It changes nothing.

Usage:
  prod_names.py -- NAME [NAME ...]                    # which names count as production now
  prod_names.py --pattern REGEX -- NAME [NAME ...]    # try a new pattern before you install it
Exit code: 0, or 2 when the hook or the pattern cannot be loaded.
"""
import argparse
import importlib.util
import os
import re
import sys

# The skill and the hook are installed side by side: <dir>/skills/infra-scout/scripts and <dir>/hooks/devops-kit.
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                    "hooks", "devops-kit", "infra-context-guard.py")


def hook_pattern():
    spec = importlib.util.spec_from_file_location("infra_context_guard", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # the hook only runs main() when it is the main program
    return module.PROD_RE


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pattern", help="a regex to try instead of the installed one (case-insensitive)")
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    try:
        regex = re.compile(args.pattern, re.IGNORECASE) if args.pattern else hook_pattern()
    except (OSError, re.error, AttributeError) as exc:
        print(f"error: cannot load the pattern: {exc}", file=sys.stderr)
        return 2
    if args.pattern:
        source = "--pattern"
    elif "DEVOPS_KIT_PROD_PATTERN" in os.environ:
        source = "DEVOPS_KIT_PROD_PATTERN" + ("; empty, so every name matches" if not regex.pattern else "")
    else:
        source = "the hook's default"
    print(f"pattern ({source}): {regex.pattern}")
    width = max(len(n) for n in args.names)
    for name in args.names:
        print(f"{name.ljust(width)}  {'production' if regex.search(name) else 'not production'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
