#!/usr/bin/env bash
# Run all embed tests. Pass `unit` or `e2e` to scope; defaults to both.
set -euo pipefail
cd "$(dirname "$0")"

scope="${1:-all}"

if [[ "$scope" == "unit" || "$scope" == "all" ]]; then
  echo "==> unit tests"
  node --test unit/*.test.mjs
fi

if [[ "$scope" == "e2e" || "$scope" == "all" ]]; then
  echo "==> e2e tests"
  if ls e2e/*.test.mjs >/dev/null 2>&1; then
    if [[ ! -d node_modules ]]; then
      echo "  (installing test deps…)"
      npm install --no-audit --no-fund --silent
    fi
    node --test e2e/*.test.mjs
  else
    echo "  (no e2e tests yet)"
  fi
fi
