# Phase 13 跨数据库迁移实验汇总

生成时间：2026-09-30T13:29:42

## B0（确定性检查，不调用 LLM）

- 场景：B0 仅换数据库连接（A 的 Schema 白名单原样生效）
- 可见表：（无）
- 结论：白名单过滤后无任何业务表，Schema Linking 无表可链，系统结构不可用。换库必须至少放开/更新 Schema 白名单。

| 指标 | Exp A | Exp B | Exp C |
|---|---|---|---|
| EX | 75.0% | 50.0% | 75.0% |
| Exec Rate | 100.0% | 83.33% | 95.83% |
| Pass@1 | 75.0% | 50.0% | 75.0% |
| Conditional EX | 75.0% | 50.0% | 75.0% |
| Repair Trigger Rate | 0.0% | 16.67% | 0.0% |

## 错误类型细分

**Experiment A（A库 + A Profile（基线））**
- correct: 18
- semantic_error: 6

**Experiment B（B库 + A 业务知识（最低限度适配））**
- correct: 12
- failed:sql_repair: 4
- semantic_error(borrowed): 8

**Experiment C（B库 + B Profile（完整适配））**
- correct: 18
- failed:sql_generation: 1
- semantic_error: 5
