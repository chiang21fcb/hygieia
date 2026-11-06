#!/usr/bin/env bash
# Hygieia one-shot check: unit tests + acceptance commands (mirrors CI).
# Usage: bash scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python -m unittest discover -s tests -v

python scripts/hygieia.py audit fixtures/ecom
python scripts/hygieia.py eval fixtures/ecom
python scripts/hygieia.py rot fixtures/ecom
python scripts/hygieia.py report fixtures/ecom

# --fail-on high must exit 1: the ecom fixture deliberately has 3 high findings
set +e
python scripts/hygieia.py audit fixtures/ecom --fail-on high
code=$?
set -e
if [ "$code" -ne 1 ]; then
  echo "❌ --fail-on high: expected exit 1, got $code" >&2
  exit 1
fi
echo "✅ --fail-on high: exit 1 as expected"
echo "✅ all checks passed"
