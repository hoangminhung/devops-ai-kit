# Release

1. Change the tag of one service: `tools/bump-tag.sh <service> <tag> --inplace`
2. Check `release/tags.yaml`: only that service's `tag:` line changed.
3. Commit: `release: <service> <tag>`.
