#!/usr/bin/env bash
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

tag="${GITHUB_REF_NAME:?Release tag is required}"
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Only stable vMAJOR.MINOR.PATCH tags are authorized by this workflow." >&2
  exit 1
fi

version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' Cargo.toml | head -n 1)"
[[ "$tag" == "v$version" ]] || { echo "Release tag and Cargo version disagree." >&2; exit 1; }
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || { echo "Stable release requires an annotated tag." >&2; exit 1; }
[[ "$(git rev-parse "refs/tags/$tag^{commit}")" == "$(git rev-parse HEAD)" ]] || { echo "Release tag does not name this checkout." >&2; exit 1; }
