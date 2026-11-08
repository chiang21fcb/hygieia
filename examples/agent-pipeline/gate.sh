#!/usr/bin/env bash
# Hygieia agent-pipeline gate (shell skeleton — not a full agent).
#
# Usage:
#   ./gate.sh <fixture_dir> <run_dir>
#
# Contract:
#   exit 0  audit passed (no findings at/above `high`) -> the answer may be sent
#   exit 2  gate blocked (high findings) -> send run_dir/reply.md (clarification) instead
#   exit 1  usage / unexpected error
#
# Layout written under <run_dir> (aligned with docs/eval-live.md):
#   audit.json     machine-readable audit result
#   audit.stderr   gate message
#   reply.md       clarification draft, only when blocked
#   eval.txt       optional `eval` output when the run dir has meta.json/control.json/treatment.json
set -euo pipefail

FIXTURE=${1:?usage: gate.sh <fixture_dir> <run_dir>}
RUN_DIR=${2:?usage: gate.sh <fixture_dir> <run_dir>}
mkdir -p "$RUN_DIR"

status=0
hygieia audit "$FIXTURE" --json --fail-on high \
  > "$RUN_DIR/audit.json" 2> "$RUN_DIR/audit.stderr" || status=$?

if [ "$status" -eq 0 ]; then
  echo "gate: pass — no high findings; the answer may be sent"
  # Optional: score a real two-arm run that lives in the same directory.
  if [ -f "$RUN_DIR/meta.json" ] && [ -f "$RUN_DIR/control.json" ] && [ -f "$RUN_DIR/treatment.json" ]; then
    hygieia eval "$FIXTURE" --results "$RUN_DIR" > "$RUN_DIR/eval.txt" 2>&1 || true
    echo "gate: eval written to $RUN_DIR/eval.txt (optional, non-blocking)"
  fi
  exit 0
fi

if [ "$status" -ne 1 ]; then
  echo "gate: unexpected exit code $status from audit" >&2
  cat "$RUN_DIR/audit.stderr" >&2 || true
  exit 1
fi

python - "$RUN_DIR/audit.json" "$RUN_DIR/reply.md" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
counts = data["summary"]["counts"]
bad = [f for f in data["findings"] if f["severity"] == "high"]

lines = [
    "# 需要澄清：语义层存在高危问题，暂不直接作答",
    "",
    f"审计对象：`{data['fixture']}`",
    f"高危 {counts['high']} 条 / 中危 {counts['medium']} 条 / 低危 {counts['low']} 条。",
    "",
    "## 高危问题",
    "",
    "| 规则 | 对象 | 说明 | 修复建议 |",
    "|---|---|---|---|",
]
for f in bad:
    lines.append(f"| `{f['rule']}` | `{f['subject']}` | {f['detail']} | {f['fix']} |")
lines += [
    "",
    "> 在语义层修好这些问题之前，任何数字都可能静默走错口径。",
    "> 请确认口径后重试，或先运行 `hygieia audit <layer>` 查看完整报告。",
]
open(sys.argv[2], "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print(f"gate: blocked — wrote {sys.argv[2]}")
PY

exit 2
