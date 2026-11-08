#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Check the index as well as the disk: ignored caches must never hide tracked
# application Python files. ATIV-derived build/test scripts are tooling only.
tracked="$(git -c core.fsmonitor=false ls-files -- '*.py' '*.pyi' '*.pyw' '*.pyx' '*.pyc' '*.pyo' \
  '*.spec' '*.egg-info/*' 'pyproject.toml' 'Pipfile' 'Pipfile.lock' \
  'poetry.lock' 'uv.lock' 'requirements*.txt' 'setup.cfg' 'pyvenv.cfg' | sed -e '/^script\/.*\.py$/d' -e '/^\.github\/scripts\/weekly_release_smoke\.py$/d' -e '/^\.github\/scripts\/test_weekly_release_smoke\.py$/d' -e '/^vendor\/avid-core-transcription\/script\/test_transcription_catalog\.py$/d' -e '/^vendor\/avid-core-transcription\/script\/update_transcription_catalog\.py$/d')"

# The two owner-approved weekly CI tools and two manifest-verified upstream
# catalog tools are exempted above/below; application Python remains forbidden.
# Their directory is not exempted; unexpected vendor Python remains visible.
# Ignore only generated build outputs and downloaded third-party inputs.
# In particular, do not honor .gitignore for application source or virtualenvs.
local_files="$(find . \
  -type d \( -name .git -o -name .build -o -path ./build -o -path ./dist \
    -o -path ./target -o -path ./node_modules -o -path ./.build-tools \
    -o -path ./.github/scripts/__pycache__ -o -path ./script/__pycache__ -o -path ./vendor/avid-core-transcription/script/__pycache__ -o -path ./.sparkle -o -path ./.whisper-cpp \) -prune -o \
  \( -name '*.py' -o -name '*.pyi' -o -name '*.pyw' -o -name '*.pyx' \
    -o -name '*.pyc' -o -name '*.pyo' -o -name '*.spec' \
    -o -name '*.egg-info' -o -name '__pycache__' \
    -o -name '.venv*' -o -name 'venv' -o -name 'pyvenv.cfg' \
    -o -name 'pyproject.toml' -o -name 'Pipfile' -o -name 'Pipfile.lock' \
    -o -name 'poetry.lock' -o -name 'uv.lock' -o -name 'requirements*.txt' \
    -o -name 'setup.cfg' \) -print | sed -e '/^\.\/script\/.*\.py$/d' -e '/^\.\/\.github\/scripts\/weekly_release_smoke\.py$/d' -e '/^\.\/\.github\/scripts\/test_weekly_release_smoke\.py$/d' -e '/^\.\/vendor\/avid-core-transcription\/script\/test_transcription_catalog\.py$/d' -e '/^\.\/vendor\/avid-core-transcription\/script\/update_transcription_catalog\.py$/d')"

if [[ -n "$tracked" || -n "$local_files" ]]; then
  echo "Python source, packaging files, or environments remain in the native checkout:" >&2
  printf '%s\n%s\n' "$tracked" "$local_files" | sed '/^$/d' | sort -u >&2
  echo "Use the archive/python-legacy branch for the frozen Python implementation." >&2
  exit 1
fi

# Check that exempted upstream tooling is still the exact reviewed snapshot.
ruby "$ROOT_DIR/script/verify_avid_snapshot.rb"
