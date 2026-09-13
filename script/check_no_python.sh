#!/usr/bin/env bash
set -euo pipefail

tracked="$({ git ls-files '*.py' '*.pyi' '*.pyw' '*.pyx' '*.spec' 'pyproject.toml' 'Pipfile' 'requirements*.txt'; } || true)"
if [[ -n "$tracked" ]]; then
  echo "Python source or packaging files are not allowed on the native main branch:" >&2
  echo "$tracked" >&2
  echo "Use the archive/python-legacy branch for the frozen Python implementation." >&2
  exit 1
fi
