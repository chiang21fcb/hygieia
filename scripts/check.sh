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

# A1：jaffle 形状的 dbt 输入——expr/filter 不塌成裸 measure 名，输出层可被 audit
rm -rf .tmp-check-dbt
python scripts/hygieia.py adapt dbt --in fixtures/adapt_dbt_jaffle/semantic_model.yaml --out .tmp-check-dbt >/dev/null
python scripts/hygieia.py audit .tmp-check-dbt > /dev/null
rm -rf .tmp-check-dbt
echo "✅ adapt dbt (jaffle): mapped + audited"

# A4：Ossie 公开样例——无 schema.sql 不崩，稳定检出 price/location/profit 同义冲突
rm -rf .tmp-check-ossie
python scripts/hygieia.py adapt ossie --in fixtures/ossie_tpcds/ossie_semantic_model.yaml --out .tmp-check-ossie >/dev/null
ossie_out=$(python scripts/hygieia.py audit .tmp-check-ossie)
echo "$ossie_out"
echo "$ossie_out" | grep -q "R1-synonym-conflict \[price\]"
echo "$ossie_out" | grep -q "R1-synonym-conflict \[location\]"
echo "$ossie_out" | grep -q "R1-synonym-conflict \[profit\]"
echo "$ossie_out" | grep -q "skipped R4-dangling-ref"
rm -rf .tmp-check-ossie
echo "✅ adapt ossie + audit without schema.sql: synonym conflicts detected"

# B1：SARIF 输出（机器可读，供 codeql-action/upload-sarif）
python scripts/hygieia.py audit fixtures/ecom --sarif .tmp-check.sarif > /dev/null
python - <<'PY'
import json
s = json.load(open(".tmp-check.sarif", encoding="utf-8"))
assert s["version"] == "2.1.0", s["version"]
run = s["runs"][0]
assert run["tool"]["driver"]["name"] == "Hygieia"
assert len(run["results"]) == 7, len(run["results"])
assert {r["level"] for r in run["results"]} == {"error", "warning"}
PY
rm -f .tmp-check.sarif
echo "✅ SARIF 2.1.0: 7 results, levels mapped"

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
