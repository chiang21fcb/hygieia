#!/usr/bin/env bash
# Hygieia one-shot check: unit tests + acceptance commands (mirrors CI).
# Usage: bash scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python -m unittest discover -s tests -v

# 显式断言验收数字（与 CI 一致），数值变了就让 check.sh 先失败
audit_out=$(python scripts/hygieia.py audit fixtures/ecom)
echo "$audit_out"
echo "$audit_out" | grep -q "Total 7 findings (high 3 / medium 4 / low 0)"

eval_out=$(python scripts/hygieia.py eval fixtures/ecom)
echo "$eval_out"
echo "$eval_out" | grep -q "65.0%" && echo "$eval_out" | grep -q "35.0%"
echo "$eval_out" | grep -q "entity: control 17/20"
echo "$eval_out" | grep -q "relation: control 13/20"
echo "$eval_out" | grep -q "manifest: model simulated"

rot_out=$(python scripts/hygieia.py rot fixtures/ecom)
echo "$rot_out"
echo "$rot_out" | grep -q "New captures: 6 (structural 4 | semantic 2)"
echo "$rot_out" | grep -q "expected_findings: all 2 captured"

python scripts/hygieia.py report fixtures/ecom

# impact 冒烟：空 diff → 无受影响指标（信息性，不失败）
printf '' | python scripts/hygieia.py impact fixtures/ecom --diff - >/dev/null

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
