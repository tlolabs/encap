#!/usr/bin/env bash
# Check contributed commits in a pull request for DCO sign-off trailers.
set -euo pipefail
base="${1:?Pass the pull request base commit}"
head="${2:?Pass the pull request head commit}"
git rev-parse --verify "$base^{commit}" >/dev/null
git rev-parse --verify "$head^{commit}" >/dev/null
missing=0
while IFS= read -r commit; do
  if ! git show -s --format=%B "$commit" |
    grep -Eq '^Signed-off-by: [^<>]+ <[^<>[:space:]]+@[^<>[:space:]]+>$'; then
    echo "Missing DCO Signed-off-by trailer: $commit" >&2
    missing=1
  fi
done < <(git rev-list "$base..$head")
exit "$missing"
