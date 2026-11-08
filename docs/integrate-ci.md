# 把 Hygieia 挂进 CI

目标：语义层（`semantic/metrics.yml`，或 dbt / Ossie 导出的层）一旦改坏，PR 上直接
红灯，并把问题标到改动文件上。全程离线，不连数据库、不需要 key。

## 三种挂法

| 方式 | 适用 | 入口 |
|---|---|---|
| 仓库内复合 Action | 本仓库自测、或 fork 后自用 | `.github/actions/audit/action.yml` |
| 消费者 workflow | 任意仓库，一次复制 | [examples/consumer-ci](../examples/consumer-ci/) |
| pre-commit | 提交前本地拦一层 | 本文末示例 |

## 1. 消费者仓库：复制即用

把语义层放在仓库根目录的 `semantic/metrics.yml`（`schema.sql` 可选），再复制一份
workflow：

```yaml
name: semantic layer

on:
  pull_request:
    paths:
      - "semantic/**"
      - "schema.sql"
  push:
    branches: [main]
    paths:
      - "semantic/**"
      - "schema.sql"

permissions:
  contents: read
  security-events: write   # SARIF 上传需要

jobs:
  hygieia:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: chiang21fcb/hygieia/.github/actions/audit@main
        with:
          path: .
          fail-on: high
          upload-sarif: "true"
```

完整可复制版本（含 `semantic/` 与 `schema.sql` 样例）见
[examples/consumer-ci](../examples/consumer-ci/)。

### 输入

| 输入 | 默认 | 说明 |
|---|---|---|
| `path` | 必填 | 语义层目录（内含 `semantic/metrics.yml`；`schema.sql` 可选） |
| `fail-on` | `high` | `high` / `medium` / `low` / `none`（`none` 只出报告不设门禁） |
| `args` | 空 | 追加参数，如 `--lang zh` |
| `sarif-file` / `json-file` | `hygieia.sarif` / `hygieia-audit.json` | 产物路径 |
| `upload-sarif` | `true` | 是否调用 `github/codeql-action/upload-sarif@v3` |
| `artifact-name` | `hygieia-audit` | 上传的 artifact 名称 |

### 输出与权限

- `exit-code`：门禁退出码（0 通过，1 命中）
- `findings-total` / `findings-high`：问题总数 / 高危数
- SARIF：每个 finding 一条 result，`level` 为 `error`（high）/ `warning`（medium）/
  `note`（low）；因契约里的 subject 是指标名而非行号，结果统一指向
  `semantic/metrics.yml:1`，对象名放在 `logicalLocations` 与 `properties.subject`
- 仓库未开启 code scanning 时，`upload-sarif: false`，JSON/SARIF 仍作为 artifact 保留

### 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 无达到门禁的问题 |
| `1` | 存在达到门禁的问题（`--fail-on` 命中） |
| `2` | CLI 用法错误 |

## 2. 本地等价命令

```bash
pip install "hygieia-sl @ git+https://github.com/chiang21fcb/hygieia.git"
# 或仓库内：pip install -e .
# 免安装：uvx --from git+https://github.com/chiang21fcb/hygieia.git hygieia audit . --fail-on high

hygieia audit . --fail-on high                    # 人读输出 + 门禁
hygieia audit . --json --fail-on high > out.json  # stdout 是纯 JSON（门禁消息走 stderr）
hygieia audit . --sarif findings.sarif            # 同时写 SARIF 2.1.0
hygieia audit . --fail-on none                    # 只出报告
```

建议在 workflow 里 pin 到 commit（`@<sha>`），避免上游 `main` 变动影响门禁口径。

## 3. pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: hygieia-audit
        name: hygieia audit (semantic layer)
        entry: hygieia audit . --fail-on high
        language: system
        files: ^(semantic/.*\.ya?ml|semantic/.*\.json|schema\.sql)$
        pass_filenames: false
```

先在本机安装（`pip install "hygieia-sl @ git+https://github.com/chiang21fcb/hygieia.git"`），
或把 `entry` 改成 `uvx --from git+... hygieia audit . --fail-on high`，避免要求每个开发者
都装一遍。`schema.sql` 可省；省掉时 R4 与 R3 的表/列校验会列进 `skipped_rules`。

## 4. 边界（写清楚才不误导）

- Hygieia 管的是**定义健康与静默错答**：同义词冲突、join 歧义、悬空引用、缺证据、
  描述腐烂、别名指向废弃指标、来源新鲜度冲突。它**不替代** `dbt sl validate` /
  SemCI 这类结构编译门禁，也不做 SQL 方言编译、权限或行动层审计。
- 静态审计不执行数据：不检测"定义对但数据错"，也不检测只在数据里才存在的新鲜度矛盾
  （见 README 的已知误报与漏检）。
- `--fail-on high` 只卡高危；要更严用 `medium`，但 demo/fixture 类仓库通常会有 R5
  中危噪音，按团队接受度选。
- Ossie / dbt 输入先 `adapt` 再 `audit`；CI 里可以两步串起来，`adapt` 的 skipped
  条目会打印在 stderr，不会静默丢字段。
