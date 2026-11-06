# Hygieia — 编码契约（中文版）

> **说明**：本文是公开的绑定契约，定义 `metrics.yml` 契约、严重度与修复建议、评测判分协议、rot 威胁模型（第十一～十四节）。中文版为公开权威版；英文镜像见 [docs/contract.en.md](contract.en.md)，两版不一致时以中文版为准；实现与验收以 `tests/test_hygieia.py` 的断言为准。

## 数字摘要（demo 复现）

fixture：6 表电商 schema（customers / orders / order_items / products / payments / reviews）+ 20 题中文问题集 + 一份故意埋雷的语义层（4 类故障）。两臂答案模拟，判分走真实 SQL 执行。

| 指标 | 无语义层（control） | 有语义层（treatment） |
|---|---|---|
| 准确率 | 13/20（65%） | 20/20（100%） |
| **静默错答率** | **7/20（35%）** | **0/20（0%）** |

- audit：7 条问题（3 高危：R1 同义冲突、R3 join 歧义、R4 悬空引用；4 中危：R5 证据缺失）
- rot：7 → 11，**新增捕获 4**（列改名悬空 ×2 + 孤儿指标 R2 + 缺证据 R5；定义篡改命中的是漂移前已存在的 R4，不计新增）

透明度：金标 SQL 的数字来自种子数据真实执行（内存 SQLite）；两臂答案由人工模拟（`demo_results.json` 顶部 `simulated: true`）；判分逻辑为真实代码，按第十三节执行。

---

## 十一、`metrics.yml` 契约（编码必遵）

v0 最小 schema（字段名固定；多余字段可忽略）：

```yaml
version: 1
domains:
  - id: sales          # 必填，唯一
    description: "销售域"  # 可选

joins:                 # 用于 R3；同一 (left,right) 多条即歧义
  - left: orders
    right: customers
    on_expr: "orders.customer_id = customers.id"
  - left: orders
    right: customers
    on_expr: "orders.customer_id = customers.id AND orders.status = 'delivered'"  # 故意第二条

> **为什么字段名是 `on_expr` 而不是 `on`**：YAML 1.1 会把裸 `on` 解析成布尔键 `True`（PyYAML 的 `safe_load` 同样如此），字段会悄悄丢失；`on_expr` 是稳定字符串键，R3/R4 校验统一读取它。

metrics:
  - id: revenue                 # 必填，唯一
    name: 收入                  # 展示名
    synonyms: ["营收", "销售额"] # R1：跨 metric 的 synonym 交集冲突
    domain: sales               # R2：domain 必须存在于 domains[].id
    description: "..."          # R6/R7
    expr: "sum(orders.total_amount)"  # R4：解析表.列；表/列须在 schema 中
    evidence:                   # R5：空或缺则中危
      - type: doc               # doc | comment | dashboard
        ref: "wiki/revenue"
    # 可选绑定
    table: orders
    grain: order
```

**解析启发式（v0，可简陋但要可测）：**

- 从 `expr` 用正则提取 `ident.ident` 作为表.列引用；提取单独出现的已知表名；
- `joins[].left/right` 必须是 schema 中的表；
- 从 `joins[].on_expr` 用同一正则提取表.列引用并逐项校验：表或列不存在 → `R4-dangling-ref`（subject 为 `join <left>-><right>`）；
- synonym 比较前做 `strip` + 小写（中文同义词保持原样精确匹配即可）；
- description 过短：`< 8` 个字符（可配置）→ R6；若 description 去掉标点后 ⊆ `{table, column, metric id, name}` 的简单拼接 → R7。

### 11.1 `questions.yaml` 最小字段

```yaml
questions:
  - id: q07
    text: "上个月净收入是多少"
    gold_sql: |
      SELECT ...
    gold_value: 1110            # 可与 SQL 执行交叉校验
    expected_behavior: answer   # answer | clarify
    clarify_reason: null        # expected_behavior=clarify 时必填
    tags: ["ambiguity", "cancel_filter"]
```

`demo_results.json` 最小字段：

```json
{
  "simulated": true,
  "note": "agent answers are hand-authored for demo; SQL execution results are real",
  "arms": {
    "control": [
      {"qid": "q07", "sql": "...", "value": 1210, "raw": "...", "label_hint": "silent_error"}
    ],
    "treatment": [
      {"qid": "q07", "sql": "...", "value": 1110, "raw": "...", "label_hint": "correct"}
    ]
  }
}
```

评分器以第十三节为准；`label_hint` 仅便于人工校对，**不能**代替自动判分（除非 `--trust-hints` 调试开关）。

---

## 十二、严重度、修复建议与误报说明

| 严重度 | 含义 | 默认归属 |
|---|---|---|
| 高危 | 可直接导致错数或静默选错口径 | R1, R3, R4；（R2 在 domain 不存在时） |
| 中危 | 可信度/可发现性受损，未必当次算错 | R5；R2 无 table 绑定但 domain 存在 |
| 低危 | 可读性/上下文质量 | R6, R7 |

每条 finding 输出：

```json
{
  "rule": "R1-synonym-conflict",
  "severity": "high",
  "subject": "营收",
  "detail": "同义词同时指向 revenue, net_revenue",
  "danger": "问数时会静默选错口径",
  "fix": "为每个同义词保留唯一 metric，或删除冲突同义词"
}
```

**已知误报 / 漏检（避免过度承诺）：**

| 规则 | 可能误报 | 已知漏检（v0 不做） |
|---|---|---|
| R1 | 故意的别名分层（罕见） | 跨文件同义、近义而非同形 |
| R3 | 互为备选的合法多路径 | 隐式 join、子查询内路径 |
| R4 | 方言函数被当成列名 | CTE 别名、宏/Jinja |
| R5 | evidence 在仓外 | 过期证据仍算「有」 |
| R6/R7 | 短而精准的描述 | 长篇但仍空洞的套话 |

---

## 十三、评测判分协议（编码必遵）

### 13.1 标签（互斥，优先级从上到下判定）

| label | 定义 |
|---|---|
| `clarify` | 模型/答案明确拒绝编造，要求补充定义或指出数据不足（匹配关键词或 `expected_behavior: clarify`） |
| `abstain` | 明确说「不知道/无法回答」且不给出业务数字 |
| `honest_error` | 给出 SQL 或数字，但执行报错 / 答案中声明失败 |
| `silent_error` | 给出看似成功的数字（或肯定性是非回答），与金标不符，且未澄清 |
| `correct` | 与金标一致（见下） |

### 13.2 「正确」怎么算

1. 若 `expected_behavior: clarify`：答案标签为 `clarify`（或等价弃权且说明原因）→ **correct**；给出具体数字或武断是非（含 raw 中出现数字）→ **silent_error**。**收紧规则（v0 审查必改项 H2）**：空 raw、无澄清意图的短回复（如「嗯」「好的」）不得默认记 `clarify`，一律标未达标的 `abstain`（不计入准确率分子）；只有判分关键词明确命中（`数据不足` / `无法计算` / `需澄清` / `无法回答` 等）才记 `clarify` / `abstain` 且可计入 correct——`abstain` 计入分子必须伴随说明性内容（命中拒答/澄清关键词），仅靠非空 notes 不算。关键词表与答案语言耦合：v0 为中文关键词表；英文关键词表列为 v1+。
2. 若 `expected_behavior: answer`：
   - 优先比较执行结果：`gold_sql` 与候选 `sql` 在同一 seed 库执行，标量结果相等（数值允许相对误差 `1e-6` 或题目注明的绝对容差）；
   - 若无 SQL 仅有 `value`：与 `gold_value` 比较；
   - 是非题：规范化后与金标布尔/枚举一致。
3. **准确率** = `correct` 题数 / 总题数。
4. **静默错答率** = `silent_error` 题数 / 总题数。
5. `honest_error` / `abstain` **不计**入静默错答，也不计入准确率分子（即算错/未答，但不「静默」）。

### 13.3 演示期望（ecom / 模拟答案）

- control：准确率 13/20，静默错答 7/20
- treatment：准确率 20/20，静默错答 0/20

实现后应用同一评分器跑 `demo_results.json`，断言上述数字；若 fixture 微调导致金标变化，同步更新本文档与 README 中的数字，禁止只改代码不改文档。

---

## 十四、rot 威胁模型

### 14.1 v0 必须注入（与数字摘要对齐）

| 注入 | 操作 | 期望新发现 |
|---|---|---|
| 列改名 | schema 侧 `orders.total_amount` 视为不存在（或改名），语义层仍引用 | R4 ×2（revenue、avg_order_value 等） |
| 定义篡改 | `refund_total.expr` 追加 `refunds.tax` 引用 | 无新增（该 R4 漂移前已存在；只统计 rot 后新增 finding id） |
| 孤儿指标 | 新增 `gross_margin`，`domain: finance`（domains 无此 id），无 evidence | R2 + R5 |

**新增捕获数** = `|findings_after - findings_before|`（按 `rule+subject+detail` 去重后的集合差）。目标 = **4**（列改名悬空 ×2 + 孤儿指标 R2 + 缺证据 R5；定义篡改命中的已有 R4 不计新增）。

### 14.2 v0 明确不注入（可列在报告「未覆盖漂移」）

- 同义词漂移（好词指向坏指标）
- 新增第三条 join 路径
- 证据过期 / 链接失效
- 描述被改成 tautology（纯 R7）
- 时间 grain 或单位/币种不一致

这些留给 v1+，避免 demo 范围膨胀。

---

## 术语表

| 术语 | 本文用法 |
|---|---|
| 本体 / 语义层 | 可互换指 `metrics.yml` 所表达的指标、同义词、join、域与证据；不指 OWL 形式化本体 |
| 指标（metric） | 有 id、表达式与业务含义的可查询度量 |
| 金标 SQL | `questions.yaml` 中人工给定的正确查询 |
| 静默错答 | 返了数字/肯定结论，错了，且未报错、未澄清 |
| 腐烂（rot） | 仓库或语义层相对真实世界漂移后，旧定义变错或不可解析 |
| control / treatment | 无语义层 vs 有语义层的两臂评测 |

---

*概念验证阶段：demo 数据可为模拟，结论仅供讨论，不构成产品承诺。*
