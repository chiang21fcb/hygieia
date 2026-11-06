# 语义层健康报告（Hygieia demo）

- 数据：ecom（6 表，20 题中文问题集）

## 🔴 高危（3）
- R1-synonym-conflict：同义词「营收」同时指向 revenue, net_revenue，问数时会静默选错口径
- R3-join-ambiguity：orders -> customers 有 2 条 join 路径，agent 可能走错导致金额翻倍或漏行
- R4-dangling-ref：指标「refund_total」引用了不存在的表「refunds」，该指标必然算错

## 🟠 中危（4）
- R5-no-evidence：指标「revenue」没有任何来源证据（文档/注释/仪表盘），无法区分「事实」和「猜测」
- R5-no-evidence：指标「net_revenue」没有任何来源证据（文档/注释/仪表盘），无法区分「事实」和「猜测」
- R5-no-evidence：指标「avg_order_value」没有任何来源证据（文档/注释/仪表盘），无法区分「事实」和「猜测」
- R5-no-evidence：指标「order_count」没有任何来源证据（文档/注释/仪表盘），无法区分「事实」和「猜测」

## 🟡 低危（0）
- （无）

## 腐烂模拟
漂移前问题数：7 ｜ 漂移后：11 ｜ 新增捕获：4
- 注入：列改名 orders.total_amount -> order_amount（语义层仍引用旧列）；refund_total.expr 被篡改为追加 refunds.tax 引用；新增孤儿指标 gross_margin（domain finance 不存在、无证据）
- 🆕 R2-orphan-metric：指标「gross_margin」的 domain「finance」不存在
- 🆕 R4-dangling-ref：指标「revenue」引用了 orders 中不存在的列「total_amount」
- 🆕 R4-dangling-ref：指标「avg_order_value」引用了 orders 中不存在的列「total_amount」
- 🆕 R5-no-evidence：指标「gross_margin」没有任何来源证据（文档/注释/仪表盘）

## 对照评测
| 指标 | 无语义层（control） | 有语义层（treatment） |
|---|---|---|
| 准确率 | 13/20 (65%) | 20/20 (100%) |
| 静默错答率 | 7/20 (35%) | 0/20 (0%) |

> 说明：本 demo 的评测是「模拟两臂答案 + 真实 SQL 判分」——两臂答案来自 demo_results.json（simulated: true，人工模拟），数字由金标/候选 SQL 在内存 SQLite 上真实执行得出；不是现场 LLM 评测。

## 未覆盖漂移（v1+）
- 同义词漂移（好词指向坏指标）
- 新增第三条 join 路径
- 证据过期 / 链接失效
- 描述被改成 tautology（纯 R7）
- 时间 grain 或单位/币种不一致

*本报告由 `python scripts/hygieia.py report <fixture_dir>` 生成；两臂演示答案来自 demo_results.json（simulated: true，手工模拟）。*