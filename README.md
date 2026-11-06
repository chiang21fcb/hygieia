# Hygieia（许癸厄亚）

> 不造本体，只养本体：语义层的体检、评测与防腐，全程本地离线。

🌐 [English](README.en.md) ｜ 状态：概念验证（demo），非产品，商业价值未验证

Hygieia 是一个完全在本地运行的 Python 命令行工具，负责给语义层做体检：静态诊断（`audit`）、两臂对照评测（`eval`）、腐烂模拟（`rot`），最后产出一份 Markdown 体检报告（`report`）。它不建本体——只检查、评测和压力测试已有的语义层，让「口径腐烂」在坑到用户之前先被看见。

- Python 3.10+，唯一依赖 `pyyaml`；全程不联网，不需要账号，也不需要任何 API key
- 以 coding-agent skill 的形式交付，原名 ontology-doctor（本体医生）
- 编码契约见 [docs/contract.md](docs/contract.md)（第十一～十四节）

---

## 它能测出什么：三组关键数字

语义层（指标、同义词、join、域与证据）是数据 agent 问数时唯一的口径来源。口径一旦漂移，agent 就会给出「看起来很自信的错误数字」。在 ecom 示例数据（6 表电商 + 20 题中文问题集）上跑 **demo 复现**——两臂答案由人工模拟，判分由真实 SQL 执行：

| 指标 | 无语义层 | 有语义层 |
|---|---|---|
| 准确率 | 13/20（65%） | 20/20（100%） |
| **静默错答率** | **7/20（35%）** | **0/20（0%）** |

静默错答指的是：返回了数字、没报错、也没澄清——用户无从察觉。这是 `eval` 的核心指标。对照组答错的 7 道题里，比较有代表性的几道：

| 题 | 问题 | 无语义层答 | 正确口径 |
|---|---|---|---|
| q07 | 上个月净收入是多少 | 1210（没扣取消单） | 1110 |
| q08 | 总收入是多少 | 1860（含取消单） | 1760 |
| q09 | 有多少活跃客户 | 6（直接数客户表） | 5（30 天内下过单） |
| q10 | 营收是多少 | 1860（走了错误口径） | 1760（net_revenue） |
| q11 | 下单转化率是多少 | 编造 0.25 | 没有访问数据，应澄清 |
| q12 | 平均客单价是多少 | 155（含取消单） | 176 |
| q20 | 净收入是否含运费 | 直接答「包含」 | 未定义运费，应澄清 |

`audit` 在同一份语义层上检出 7 条问题（3 高危：R1 同义冲突、R3 join 歧义、R4 悬空引用；4 中危：R5 证据缺失）。`rot` 模拟三类常见漂移（列改名、定义篡改、新增孤儿指标）后重跑 audit，新增捕获 4 条——其中定义篡改命中的是漂移前就存在的 R4（refund_total 引用不存在的 refunds 表），按「新增捕获 = 前后集合差」的规则不计新增。

透明度说明：本 demo 的评测是**「模拟两臂答案 + 真实 SQL 判分」**——两臂答案由人工模拟（`demo_results.json` 顶部标注 `simulated: true`），不是现场 LLM 跑出来的；金标 SQL 的数字来自种子数据真实执行（内存 SQLite）；判分逻辑是真实代码，按第十三节协议运行。关键指标 `net_revenue` 的表达式（`sum(orders.net_amount)`）可在 seed 上真实执行，treatment 答案与之一致；R4 埋雷落在独立的 `refund_total` 上，不参与 eval 金标路径。

## 四个命令

| 命令 | 做什么 | 输入 | 输出 |
|---|---|---|---|
| `audit` | 静态诊断 7 类问题（R1 同义冲突 / R2 孤儿指标 / R3 join 歧义 / R4 悬空引用 / R5 证据缺失 / R6 缺描述 / R7 冗余） | `semantic/metrics.yml` + `schema.sql` | 每条问题带规则、危险、修复建议 |
| `eval` | 两臂对照评测：同一批问题，分别在没有/有语义层的条件下回答 | `questions.yaml` + 两臂答案（默认 `demo_results.json`） | 准确率与静默错答率 |
| `rot` | 在内存副本注入三类漂移，重跑 audit，报告新增捕获（默认不写回磁盘） | 同上 | 漂移前 → 漂移后 → 新增捕获 |
| `report` | 完整体检报告，含高危/中危、腐烂模拟、对照评测三块 | 同上 | `reports/health-report.md` |

## 安装与快速开始

```bash
pip install -r requirements.txt   # 唯一依赖：pyyaml

python scripts/hygieia.py audit  fixtures/ecom   # 静态诊断
python scripts/hygieia.py eval   fixtures/ecom   # 两臂对照评测
python scripts/hygieia.py rot    fixtures/ecom   # 腐烂模拟
python scripts/hygieia.py report fixtures/ecom   # 完整体检报告
```

跑完 `report` 后，打开 `fixtures/ecom/reports/health-report.md` 就能看到完整体检结果。`eval` 的终端输出长这样：

```
$ python scripts/hygieia.py eval fixtures/ecom
臂           正确        静默错答        准确率       静默错答率
control（无语义层）13/20      7/20          65.0%       35.0%
treatment（有语义层）20/20      0/20         100.0%        0.0%
```

然后可以跑一遍自测，确认契约数字没被改坏：

```bash
python -m unittest discover -s tests -v
```

常用可选参数：`--results <json>` 换评测答案文件；`--json` 输出机器可读结果；`--fail-on high` 存在高危即退出码 1（CI 用）；`--write` 让 `rot` 把漂移后的语义层落盘为 `metrics.rot.yml`。`doctor` 是 `audit` 的兼容别名。

## 为什么做这个项目

现有的语义层工具大多解决「怎么建」——从元数据、文档和表单引导生成本体。但建完之后怎么保证它不烂，没人管：诊断本体有没有毛病、证明本体到底救了 agent 还是害了它、检测本体什么时候开始腐烂，这三件事没有现成工具。Hygieia 是一个概念验证，只做这一件事，并用可复现的数字把「为什么需要它」演示出来。

本项目为原创：不对标、不引用任何第三方项目。

## 项目结构

```
hygieia/
├── SKILL.md                       # 触发语 + 操作契约（标准技能格式）
├── README.md                      # 中文版说明
├── README.en.md                   # 英文版说明
├── docs/
│   └── contract.md     # 全景 + 编码契约（第十一～十四节）
├── scripts/hygieia.py             # audit / eval / rot / report
├── tests/test_hygieia.py          # 标准库自测
├── fixtures/ecom/
│   ├── schema.sql                 # 6 表电商 DDL
│   ├── seed.sql                   # 可眼算的原创合成小数据
│   ├── semantic/metrics.yml       # 故意埋雷的语义层（R1/R3/R4/R5）
│   ├── questions.yaml             # 20 题（含金标 SQL 与期望行为）
│   ├── demo_results.json          # 两臂演示结果（simulated: true）
│   └── reports/health-report.md   # report 生成的体检报告
├── LICENSE                         # MIT 许可证
└── requirements.txt               # pyyaml>=6.0
```

## 已知限制

1. 两臂演示答案由人工模拟（`demo_results.json` 顶部已标注）：数字本身来自 SQL 真实执行，但答案不是模型现场生成的。真实评测需按协议在 coding agent 里现场跑，产物存 `fixtures/ecom/runs/<时间戳>/`；
2. 规则是启发式，不是完整的 SQL 解析器（v1 计划换成 AST 级解析）；
3. 只覆盖 7 类静态问题，深层口径语义、权限、动作安全不在范围内；
4. 只支持单个 schema 目录、单一方言（SQLite 友好的子集即可跑通 fixture）；
5. 没有界面、多租户或行动层；
6. 「语义质量工具」的商业价值尚未验证——本项目只负责演示需求，不构成需求证明；
7. v0 只认本仓库的目录布局和 `metrics.yml` 契约，第三方建模生态的适配器明确不做，列为 v1+ 候选。

### 已知误报与漏检（避免过度承诺）

| 规则 | 可能误报 | 已知漏检（v0 不做） |
|---|---|---|
| R1 | 故意的别名分层（罕见） | 跨文件同义、近义而非同形 |
| R3 | 互为备选的合法多路径 | 隐式 join、子查询内路径 |
| R4 | 方言函数被当成列名 | 公共表表达式别名、宏/模板 |
| R5 | 证据在仓库之外 | 过期证据仍算「有」 |
| R6/R7 | 短而精准的描述 | 长篇但仍空洞的套话 |

## 路线图

```
v0（本 demo）  诊断 + 评测 + 腐烂模拟        ← 证明问题存在（当前版本）
v1            AST 级解析 + 多方言 + 影响分析 + CI 门禁   ← 变成工程资产（2-3 周）
v2            演化闭环：变更→检测→建议→审批→版本化      ← 补齐缺失的维护闭环（2-3 月）
v3            跨平台语义一致性 + 行动层审计              ← 接市场空白（6-12 月）
```

- v1：join 挖掘改用 AST 级 SQL 解析；支持主流中国数仓方言；合并请求触发 audit + eval，质量不达标即拦截；git 变更 → 受影响指标影响分析
- v2：本体版本化与演化历史；变更 → 检测 → 建议 → 人工审批 → 合并的闭环；把维护从人工周报变成 CI 事件

## 数据声明

ecom fixture 为原创合成演示数据，无任何外部数据来源。

## 许可证

MIT License，见 [LICENSE](LICENSE)。

---

*概念验证阶段：demo 数据可为模拟，结论仅供讨论，不构成产品承诺。*
