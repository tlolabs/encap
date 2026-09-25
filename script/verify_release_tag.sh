#!/usr/bin/env bash
# Require a stable tag signed by the maintainer's configured trusted key.
set -euo pipefail
tag="${1:?Pass a vMAJOR.MINOR.PATCH tag}"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "Production release requires a stable SemVer tag." >&2
  exit 1
}
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || {
  echo "Production release requires an annotated tag." >&2
  exit 1
}
[[ -n "${RELEASE_TAG_VERIFY_KEY:-}" && -n "${RELEASE_TAG_SIGNING_FINGERPRINT:-}" ]] || {
  echo "Configure RELEASE_TAG_VERIFY_KEY and RELEASE_TAG_SIGNING_FINGERPRINT." >&2
  exit 1
}
export GNUPGHOME
GNUPGHOME="$(mktemp -d)"
trap 'rm -rf "$GNUPGHOME"' EXIT
chmod 700 "$GNUPGHOME"
printf '%s\n' "$RELEASE_TAG_VERIFY_KEY" | gpg --batch --import >/dev/null
expected="${RELEASE_TAG_SIGNING_FINGERPRINT^^}"
[[ "$expected" =~ ^[A-F0-9]{40}$ ]] || {
  echo "RELEASE_TAG_SIGNING_FINGERPRINT must be a full 40-character fingerprint." >&2
  exit 1
}
status="$(git verify-tag --raw "$tag" 2>&1)"
printf '%s\n' "$status" | grep -Eq "\[GNUPG:\] VALIDSIG $expected([[:space:]]|$)" || {
  echo "Tag signature does not match the configured maintainer key." >&2
  exit 1
}
