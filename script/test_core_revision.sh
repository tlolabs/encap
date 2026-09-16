#!/usr/bin/env bash
# Exercise the helper boundary without changing the user's Core checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HOST="$WORK/EnCAP"
CORE="$WORK/AVID Core"
mkdir -p "$HOST/script" "$HOST/runtime" "$CORE"
cp "$ROOT/script/check_core_runtime.sh" "$HOST/script/"
git -C "$CORE" init -q
printf 'fixture\n' > "$CORE/source"
git -C "$CORE" add source
git -C "$CORE" -c user.name='Revision test' -c user.email='test@example.invalid' -c commit.gpgsign=false commit -qm fixture
REVISION="$(git -C "$CORE" rev-parse HEAD)"
printf '%s\n' "$REVISION" > "$HOST/runtime/core-revision"
printf 'avid-core = { git = "https://github.com/tlolabs/avid-core.git", rev = "%s", version = "=0.2.1" }\n' "$REVISION" > "$HOST/Cargo.toml"
bash "$HOST/script/check_core_runtime.sh" > "$WORK/output"
# Windows Git checkouts may use CRLF for this text file.
printf '%s\r\n' "$REVISION" > "$HOST/runtime/core-revision"
bash "$HOST/script/check_core_runtime.sh" > "$WORK/output"
printf '%s\n' "$REVISION" > "$HOST/runtime/core-revision"

authority_rejected() {
  if bash "$HOST/script/check_core_runtime.sh" > "$WORK/output" 2>&1; then
    echo 'Invalid Core authority was accepted' >&2; exit 1
  fi
  grep -F "$1" "$WORK/output" >/dev/null
}
printf 'edited\n' >> "$CORE/source"
authority_rejected 'Core checkout has local changes'
git -C "$CORE" restore source
printf 'untracked\n' > "$CORE/new-source"
authority_rejected 'Core checkout has local changes'
rm "$CORE/new-source"
printf 'mismatch\n' > "$HOST/runtime/core-revision"
authority_rejected 'Core helper revision differs from the pinned Cargo dependency'
printf '%s\n' "$REVISION" > "$HOST/runtime/core-revision"
printf 'new revision\n' >> "$CORE/source"
git -C "$CORE" add source
git -C "$CORE" -c user.name='Revision test' -c user.email='test@example.invalid' -c commit.gpgsign=false commit -qm changed
authority_rejected 'Core checkout differs from the pinned host mapping'
printf '%s\n' 'Core revision checks passed: clean LF/CRLF pin accepted; dirty, untracked, mismatched Cargo and mismatched checkout rejected.'
