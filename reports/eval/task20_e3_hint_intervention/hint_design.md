# Task 20：E3 Detector 提示型干预 — Hint 设计说明

> 独立实验配置；不修改正式 Prompt / Generator / Detector；不引入 Repair / 第二 Agent / AST rewrite。

## 1. 干预变量（唯一）

`FANOUT_RECHECK_HINT` —— 仅当 `analyze_fanout(sql).fan_out_suspected == True` 时注入。

- `false` → **不添加任何内容**（绝对不成为全局规则）；
- `true` → 将 hint 作为**额外的 user message** 追加在调用方（SQLGenerator.generate_with_context）原有的
  `[system, user(question+schema+fewshot+...)]` messages 之后，调用同一 provider（temperature=0）重新生成 final SQL；
- 原始 schema linking / few-shot / question 上下文完全复用，不重复调用 link/retrieve。

## 2. 流程

```text
question
 ↓
schema linking  (正式组件)
 ↓
few-shot        (正式组件)
 ↓
SQL generation  (正式 SQLGenerator)
 ↓
fanout detector (analyze_fanout)
 ├─ false → final_sql = initial_sql（零干预）
 └─ true  → 追加 FANOUT_RECHECK_HINT → 同一 provider 重新生成 final_sql
```

说明：本方案 = 「同一次生成链路内的额外一次生成」（复用同一 prompt 构造与校验，
非独立 Repair 流程）。与正式 Agent 的 Repair 分支无接口关联。

## 3. Hint 文本（version v1，Task20 固定）

```text
【Fan-out 自检提示】
检测到当前 SQL 存在潜在 1:N Join 粒度风险（orders × order_items）。
请重新检查 SQL 中 orders 与 order_items 的 Join 粒度：
- 如果聚合函数作用于 orders 级字段（例如 orders.total_amount、订单数），请确认
  是否会因 order_items 的多行展开导致重复累加 / 重复计数；
- 不要修改查询需求的业务语义；
- 优先通过订单级预聚合（先按订单分组后聚合）、独立聚合后再按维度 JOIN、或使用
  EXISTS / 去重等方式避免重复累计；
- 注意：item-level 指标（例如 order_items.subtotal、order_items.quantity）不受本提示影响，
  请勿因本提示改写 item 级聚合。
请基于上述提示与题目原始需求，重新生成唯一一条只读 SQLite SQL。
```

## 4. 边界（§五 §十）

- 不是强制改 SQL、不是自动生成、不是 AST rewrite、不是 Repair、不是第二 Agent；
- 不修改 Detector 规则 / Benchmark / Gold / Few-shot / Prompt V1.3 正式版本；
- 实验代码独立于正式 Agent 主链路（backend/app/experiments/fanout_hint.py）。

## 5. 注入点选择（最小干预）

- 若正式 SQLGenerator 已支持"传入额外 user message 重新生成" → 会在正式实验中复用；
- 当前实现：FanoutHintGenerator 显式构造 messages=[system, user(prompt), user(hint)]，
  直接调用 provider.generate → parse_llm_output → validate_output（与正式生成完全同构）；
- 因此本设计不需要修改 graph / nodes / repair。

## 6. 单例 dry-run 结果（见 single_case_e0086）

- E-0086：alarm=true → hint 注入 → 模型自行改为 订单粒度 CTE（user_order_stats 聚合 total_amount）
  与 明细粒度 CTE（product_count）再 JOIN → **EX✗ → EX✓**（total_spent 369854.65 → 89397.46）。