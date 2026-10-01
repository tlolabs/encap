#!/usr/bin/env bash
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

tag="${GITHUB_REF_NAME:?Release tag is required}"
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Only stable vMAJOR.MINOR.PATCH tags are authorized by this workflow. Prerelease signing needs a separate unsigned path." >&2
  exit 1
fi

version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' Cargo.toml | head -n 1)"
[[ "$tag" == "v$version" ]] || { echo "Release tag and Cargo version disagree." >&2; exit 1; }
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || { echo "Stable release requires an annotated tag." >&2; exit 1; }

: "${ENCAP_RELEASE_SIGNING_PUBLIC_KEY_B64:?Configure the maintainer's public release-signing key as a GitHub Actions variable}"
: "${ENCAP_RELEASE_SIGNING_FINGERPRINT:?Configure the maintainer's signing-key fingerprint as a GitHub Actions variable}"
fingerprint="$(printf %s "$ENCAP_RELEASE_SIGNING_FINGERPRINT" | tr '[:lower:]' '[:upper:]')"
[[ "$fingerprint" =~ ^[0-9A-F]{40}$ ]] || { echo "Release signing fingerprint must be 40 hexadecimal characters." >&2; exit 1; }
export GNUPGHOME="${RUNNER_TEMP:?}/encap-release-gnupg"
mkdir -m 700 "$GNUPGHOME"
printf '%s' "$ENCAP_RELEASE_SIGNING_PUBLIC_KEY_B64" | base64 --decode | gpg --batch --import
imported="$(gpg --batch --with-colons --fingerprint | awk -F: '$1 == "fpr" {print toupper($10)}')"
[[ "$imported" == "$fingerprint" ]] || { echo "Imported release key does not match the configured fingerprint." >&2; exit 1; }
git verify-tag "$tag"
