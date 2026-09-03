#!/bin/bash
# Populate worker/{gate,vendor} from their single sources of truth.
#
# 🔴 There is exactly ONE gate on disk: ../gate. This script copies it in, and
# .gitignore keeps the copy out of the repo, so a stale second gate cannot be
# committed and cannot drift. Always wipe-then-copy; never merge.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf worker/gate worker/vendor
cp -R ../gate worker/gate
find worker/gate -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# The `workers` runtime SDK, from the pip package `workers-py`.
# We vendor it by hand rather than running `pywrangler sync`: sync drives a
# Pyodide interpreter through `uv`, which invokes node with
# --experimental-wasm-stack-switching -- a flag removed in current Node. Hand
# vendoring needs no interpreter and produces the same tree.
# 🔴 The venv is built OUTSIDE the repo. A pip tree inside a public-domain
# working copy drags thousands of third-party files through every scan that
# looks at this repo, and one of them will eventually look like a credential.
SDK_VENV="$(mktemp -d)/sdk"
trap 'rm -rf "$(dirname "$SDK_VENV")"' EXIT
python3 -m venv "$SDK_VENV" >/dev/null
"$SDK_VENV/bin/pip" install -q --disable-pip-version-check workers-py
SP="$(ls -d "$SDK_VENV"/lib/*/site-packages)"
mkdir -p worker/vendor
cp -R "$SP/workers" worker/vendor/workers
find worker/vendor -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "gate modules : $(find worker/gate -name '*.py' | wc -l | tr -d ' ')"
echo "sdk modules  : $(find worker/vendor -name '*.py' | wc -l | tr -d ' ')"
echo "ready: npx wrangler dev --local"
