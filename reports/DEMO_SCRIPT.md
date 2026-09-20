# Demo Script

> 用途：课堂答辩现场按本脚本操作，不需要临时思考。
> 免责声明：**演示中不做任何代码修改、不跑 Benchmark、不临时创造问题**；全部 4 个问题均来自 Task 23 E2E Smoke 实测（`reports/eval/task23_final_acceptance/e2e_smoke.json`）。

---

## 1. Demo 总时长

**6~8 分钟**（其中 4 个 Demo 约 4~5 分钟，Trace / SQL / E3 讲解约 2~3 分钟）。

> 每个真实查询端到端约 8~12 秒（含 Mimo 推理），连续 4 次共约 40~50 秒纯等待；话术穿插覆盖等待时间。

## 2. 开场话术

> 各位老师好，接下来我用系统真实运行演示一遍。我的演示围绕一句话展开：**用户面对的是自然语言，而系统内部最终产生的是可执行 SQL**。系统是一个 LangGraph 编排的 Agent，不是"一问一答的聊天机器人"。
>
> 演示中我会按 4 个已验证问题演示，并在最后展示 SQL、Trace 和一个 E3 检测案例。

## 3. 环境启动

**演示前已完成（见 DEFENSE_CHECKLIST.md）**：

```text
1. Backend：cd backend && uvicorn app.main:app --reload   → http://127.0.0.1:8000
2. Frontend：cd frontend && npm run dev                    → http://localhost:5173
3. 健康检查：curl http://127.0.0.1:8000/api/health          → status: ok
4. LLM 链路：POST /api/llm/test                             → success
5. 浏览器已打开 http://localhost:5173（智能分析页）
```

**开场即验证一句**（可选，10 秒）：

> 我先确认服务健康：系统正在对 SQLite 数据库做只读连接探活，返回 ok。

## 4. Demo 1：普通查询

**问题（复制粘贴到输入框，不要手打）**：

> 哪个地区的用户最多？

**预期结果**（已验证）：

```text
region | user_count
广东   | 246
1 行
```

**讲解词**：

- Schema Linking：系统先理解"地区、用户"对应 `users.region`，而不是全表扫描；
- Few-shot：检索最相似的示例辅助生成；
- SQL：`SELECT region, COUNT(*) AS user_count FROM users GROUP BY region ORDER BY user_count DESC LIMIT 1`；
- Safety → 只读执行 → 结果；
- 强调：**用户只说了自然语言，系统内部产生的是可执行 SQL**。

## 5. Demo 2：聚合/时间

**问题**：

> 2025年每月销售额是多少？

**预期结果**（已验证）：

```text
12 行（月度 ym, total_sales）
示例：2025-01 → 725433.47，2025-02 → 775493.74 …
```

**讲解词**：

- 这一题考的是：时间函数（`strftime('%Y-%m')`）+ 聚合（`SUM`）+ **口径**（排除 `cancelled`）；
- 讲清楚：`order_items.subtotal` 是明细行金额、`orders.total_amount` 是订单实付金额，系统按统一口径统计"实际销售"；
- Safety 层会校验表/列存在性与只读约束。

## 6. Demo 3：Top-N 排名

**问题**：

> 近30天销量最高的商品 Top 5 是哪些？

**预期结果**（已验证）：

```text
5 行（product_name, total_sold）
示例：完美日记钢笔X2 20、苏泊尔粉底液青春版 18 …
```

**讲解词**：

- 生成 SQL：`date('now', '-30 day')` 时间窗口 + `SUM(quantity)` + `ORDER BY ... DESC LIMIT 5`；
- 强调 LIMIT ≤500 是安全层强制的上限，系统不假装一次返回全部数据；
- "排名需求"由 Agent 链路的 SQL 生成负责，无需用户知道 SQL。

## 7. Demo 4：多表 JOIN

**问题**：

> 哪个类目的销售额最高？

**预期结果**（已验证）：

```text
4 表 JOIN（order_items × orders × products × categories）
家用电器 → 8,290,243.71（1 行）
```

**讲解词**：

- 这是最能说明"Schema Understanding 价值"的一题：模型先靠 Schema Linking 确定 4 张表的关系，再生成 JOIN 型 SQL；
- 结果与 Demo 3 的不同在于口径：这里是按类目汇总销售额，而不是商品销量；
- 强调：**表关系复杂时，Schema 描述 + 校验层才是可信的保证**。

## 8. Trace 展示

操作：任选一个 Demo 完成后，点开页面下方"Agent Trace"面板。

**讲解话术**：

> 这不是黑盒调用模型。大家看 Trace：它有确定的节点——schema_link → fewshot_retrieve → sql_generate → sql_safety → sql_execute →（可选 sql_repair）→ result。每个节点都记录成功 / 失败 / Skip、耗时与输入输出摘要。

**现场要点**：

- 指出 `execute_count`（本次执行次数）与 `repair_count`（自动修复次数）；
- 指出耗时分布：主要耗时在 LLM 推理环节（schema_link / sql_generate），sql_safety / sql_execute 是毫秒级；
- 强调有界约束：`repair_count ≤ 1`、`execute_count ≤ 2`，绝不无限循环。

## 9. SQL 展示

操作：推荐用 Demo 1 或 Demo 4 的结果，展开"SQL 查询"面板（已默认展开）。

**讲解话术**：

> 用户问题 → 生成 SQL → 安全检查 → 只读执行 → 结构化结果。这条 SQL 是系统真实生成的，不是演示数据。整个过程用户不需要看懂 SQL，但系统把 SQL 透明地展示出来，结果可验证、可追溯。

**注意**：**不在现场手动修改 SQL**。

## 10. E3 案例讲解

**不建议现场实时跑**，用口述 + 页面/截图讲解 E-0086：

```text
orders × order_items（订单×明细）
   ↓
Fan-out 粒度放大
   ↓
Pred SQL 累计消费额 369854.65
   ↓
真实结果 89397.46
   ↓
约 4.14× 放大
```

再讲机制（结合 P12/P13 页）：

```text
Detector（只读 Pred SQL，不依赖 Gold）
   ↓
Alarm
   ↓
注入 FANOUT_RECHECK_HINT
   ↓
1 次 regeneration
   ↓
EX ✗ → EX ✓
```

**必须同时说明的口径**（不可省略）：

> E3 当前是 proof of concept / mechanism validation；alarm 样本仅 1 条；
> **OFF 90% / ON 93% 是观测差异，不代表 Hint 整体提升 3 个百分点**；只有 E-0086 这 +1 分有直接 Hint 归因证据。

## 11. Demo 异常处理

| 现象 | 处理 |
|---|---|
| Mimo API 失败（502/503/超时） | **不临时换问题、不编数据**；切换到已准备好的真实截图 / Trace 材料 |
| 前端无法连接 Backend | 展示已准备好的真实系统截图（`reports/ppt_assets/03_result.png` 等） |
| 模型响应过慢 | 不现场久等；直接展示已验证结果截图 + Trace |
| 顺序乱了 | 回到 Demo 清单：1 普通 → 2 聚合 → 3 Top-N → 4 JOIN，再 SQL/Trace、最后 E3 |

## 12. 现场兜底方案

- **素材包**（提前准备好，随 U 盘/本地携带）：
  - 真实截图：`reports/ppt_assets/01_home.png`（首页）、`03_result.png`（真实结果 广东/246）、`05_sql_trace.png`（SQL+Trace 8 节点）；
  - PPT：`reports/基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx`（16 页，含 Demo 页）；
  - 记录：`reports/eval/task23_final_acceptance/e2e_smoke.json`（4 条实测证据）。
- **原则**：现场只演示已验证内容；断网/无 Key 时全部改用截图讲解；**不改代码、不现场跑 Benchmark**。

## 13. Demo 结束话术

> 以上就是系统真实运行的完整演示：自然语言提问 → Schema 理解 → 少样本示例 → 可执行 SQL → 安全校验 → 只读执行 → 结构化结果，全程可 Trace。谢谢各位老师，欢迎提问。

---

*依据：e2e_smoke.json（4 条已实测）、PPT_CONTENT.md、FINAL_DELIVERY_GAP_CHECK.md（响应时间/局限披露）。*