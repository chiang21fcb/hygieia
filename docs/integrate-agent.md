# 把 Hygieia 挂进 agent 流水线

目标：agent 在**回答之前**先过一道语义层体检门禁。语义层有高危问题时，不返回数字，
而是返回"需要澄清"并附上 findings；只有门禁通过才把答案发给用户。

这是对静默错答（silent error：返回了数字、没报错、也没澄清）最省事的一道闸。

## 流水线顺序

```
读语义层 ──▶ 生成答案 ──▶ 写 runs/<id>/ ──▶ hygieia audit --fail-on high
                                              │
                              exit 0 ─────────┴──────── exit 1
                                 │                        │
                           发出答案               回"需要澄清" + findings
                              └──（可选）──▶ hygieia eval --results runs/<id>
```

## 五步

1. **读层**：`semantic/metrics.yml`（或先 `hygieia adapt dbt|ossie` 生成）。只读，不写回。
2. **生成答案**：照常调用你的 agent；答案同时写 `raw` 与原样 SQL。
3. **落盘**：写 `runs/<run_id>/`，字段与
   [docs/eval-live.md](eval-live.md) 一致（`meta.json` + `control.json` + `treatment.json`）。
4. **门禁**：`hygieia audit <fixture> --json --fail-on high`。
   - exit `0`：可以发答案；
   - exit `1`：改写为"需要澄清"，把 `findings` 里的 rule / subject / detail / fix 附给用户；
   - exit `2`：参数错误，按失败处理，别发答案。
5. **（可选）判分**：`hygieia eval <fixture> --results runs/<id>`。manifest 的 model /
   prompt / questions / corpus / semantic 哈希不一致时，两次 run 不可直接比较。

## 直接可跑的壳

[examples/agent-pipeline](../examples/agent-pipeline/) 提供 `gate.sh`：

```bash
./gate.sh ../../fixtures/ecom /tmp/run      # 高危 3 条 -> exit 2，写 reply.md
./gate.sh ../../fixtures/adapt_dbt_mini /tmp/run-ok   # 无高危 -> exit 0
```

`audit --json` 保证 stdout 是纯 JSON（门禁消息写 stderr），`reply.md` 直接可发。

## 判定口径

- **只有高危拦截**。中危（R5 缺证据、R2 无 table 绑定）不拦：真实仓库里证据体系往往
  落后于语义层，一律拦会把门禁变成噪音。需要更严时改成 `--fail-on medium`。
- **"需要澄清"不是道歉**：回复里要写清楚是哪条定义有问题、会怎样影响数字、修完后
  如何重试。`reply.md` 的模板就是按这个写的。
- **不伪造证据**：不要为了让门禁通过而在 `metrics.yml` 里补假 `evidence` 或删同义词；
  R1/R8 的冲突本身就是需要人确认的业务决定。

## 边界

- 本仓库**不实现完整 agent**，只给壳脚本与目录约定；模型调用、prompt、工具编排由你用。
- Hygieia 静态审计，不执行 SQL、不读数据。它保证的是"定义层面没有已知的静默错误来源"，
  不保证"这条 SQL 一定对"——后者交给平台的结构编译门禁（`dbt sl validate`、SemCI）。
- 不做 R10/R11 读数据规则、不做通用 mutation 引擎；这些是后续阶段。
- 全本地离线，单次 audit 在毫秒级，适合放在 agent 的同步路径上。

## 失败时的推荐回复

```text
需要澄清：语义层当前有 3 条高危问题，直接作答可能给出错误口径。

- R1 同义冲突：`营收` 同时指向 revenue / net_revenue
- R3 join 歧义：orders -> customers 有 2 条路径
- R4 悬空引用：refund_total 引用了不存在的 refunds 表

请确认口径，或在修复语义层后重试。完整报告：`runs/<id>/audit.json`。
```

这与 `examples/agent-pipeline/gate.sh` 生成的 `reply.md` 结构一致。
