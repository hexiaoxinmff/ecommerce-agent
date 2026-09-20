# LangGraph Agent 编排说明

> 阶段：阶段 4-任务 8（LangGraph Agent Orchestration）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 目标

用 LangGraph 把已验收模块编排成**固定流程、显式状态、条件分支、有界循环**
的 Text2SQL Agent。**不新增核心业务能力**——Schema Linking / Few-shot /
Generator / Safety / Executor / Repair 全部复用现有模块。

采用**控制式编排**（节点固定、State 明确、条件边明确、Repair/Execute 有上限），
**不使用**自由 ReAct Agent（Agent 自由选工具 / 自由循环 / 无限思考）。

## 2. 流程

```text
START
  ↓
schema_link
  ↓
fewshot_retrieve
  ↓
sql_generate
  ↓
sql_safety
  ↓
sql_execute
  ├── 成功 / Safety拒绝 / repair 已用尽 ──→ result -> END
  └── 数据库执行错误（repair_count==0）→ sql_repair
        ├── 被拒绝（Safety/Schema/非法输出）→ result -> END
        └── 通过 → sql_execute_repaired → result -> END
```

保证：`repair_count ≤ 1`、`execute_count ≤ 2`，绝不无限循环。

## 3. 目录与文件

```text
backend/app/agent/
├─ state.py     # AgentState（TypedDict，total=False，显式字段）
├─ nodes.py     # make_nodes() 节点工厂 + 路由函数 + build_agent_result
├─ graph.py     # default_components() / build_agent() / run_agent()
└─ models.py    # AgentRequest / AgentResult / AgentResponse
```

- 每个节点只修改自己负责的 State 字段；无全局 Agent 状态；
- 依赖注入：`AgentComponents`（schema_linker / fewshot_retriever /
  sql_generator / sql_executor / sql_repairer），默认取真实模块，测试可全套替换为 fake。

## 4. State（AgentState 关键字段）

```text
question / schema_tables / schema_columns / schema_reasons / schema_confidence
fewshot_examples
generated_sql / original_sql / repaired_sql / repair_reason / repair_error
execution_result / execution_error
execute_count / repair_count
内部标志：sql_safety_ok / executed_ok / execute_error_kind / repair_ok
最终：success / final_error
```

## 5. 节点职责（全部复用既有模块）

| 节点 | 复用 | 写入 |
|---|---|---|
| schema_link | `SchemaLinker.link` | schema_* |
| fewshot_retrieve | `FewShotRetriever.retrieve`（Top-3） | fewshot_examples |
| sql_generate | `SQLGenerator.generate_with_context` | generated_sql / original_sql |
| sql_safety | `app.sqlgen.safety.check_sql_safety` | sql_safety_ok |
| sql_execute | `app.sqlexec.executor.execute` | execution_result / execute_count / 错误分类 |
| sql_repair | `SQLRepairer.repair`（含 Safety+Schema 二次校验） | repaired_sql / repair_count / repair_ok |
| sql_execute_repaired | `app.sqlexec.executor.execute` | 第二次执行结果 |
| result | 组装终态 | - |

### 避免重复 Mimo 调用

为 `SQLGenerator` 新增 `generate_with_context(question, link_result, fs_result)`
内部入口：直接使用 Graph 已准备好的 Schema Linking + Few-shot，**不重复调用**
SchemaLinker / FewShotRetriever。原 `generate(question)` 默认行为不变（自带两步）。
Graph 中保证：一次 Schema Linking + 一次 Few-shot + 一次 SQL Generation。

测试通过调用计数断言（link/retriever/generator 各恰好 1 次）。

## 6. 条件边

```python
route_after_sql_safety: 通过 -> execute；拒绝 -> result（禁止 Repair）
route_after_execute:     成功 / Safety错误 / repair已用尽 -> result；
                        数据库错误且 repair_count==0 -> repair
route_after_repair:     repair_ok -> 第二次执行；拒绝 -> result
```

逻辑明确、无模糊条件。

## 7. 有界循环验证（计数）

| 场景 | execute_count | repair_count | 测试覆盖 |
|---|---|---|---|
| 无错误 | 1 | 0 | ✅ |
| 一次 Repair 成功 | 2 | 1 | ✅ |
| Repair 后仍失败 | 2 | 1 | ✅ |
| sql_safety 阶段拒绝（生成 SQL 危险） | 0 | 0 | ✅ |
| 执行 Safety 错误 | 0 | 0（禁止 Repair） | ✅ |
| Repair 输出被拒 | 1 | 1（不二次执行） | ✅ |

## 8. 输出结构（AgentResult）

```text
question / success / generated_sql / repaired_sql / execution_result
execution_error / repair_reason / repair_error / execute_count / repair_count / final_error
```

保留全部中间证据，供后续 Trace UI / Bad Case 分析。

## 9. API

```http
POST /api/agent/analyze
{ "question": "哪个地区的用户最多？" }
```

- 成功（200）：`{success: true, result: {...}}`；
- 最终失败仍返回 200 结构 + `success=false` + 诊断字段；
- Provider/LLM 错误：认证 502，其余 503（与既有约定一致）；
- 参数（空 question）422；未预期异常 500 固定文案。

> 说明：任务提示文本在「Graph API 新增」处截断，接口名按项目惯例采用
> `POST /api/agent/analyze`（LangGraph 编排入口）。如需其他命名可再调整。

## 9b. Trace（阶段 4-任务 9 扩展）

- `AgentState` 增加 `trace`（`Annotated[list[dict], operator.add]` reducer 追加）
  与 `trace_final`（result 节点补全 skipped 后写回）；
- 每个节点产生 `TraceEvent{sequence, node, status(success/error/skipped),
  duration_ms, message, input_summary, output_summary}`；
- `AgentResult` 增加 `trace`、`total_time_ms`、`http_status`、`error_type`；
  详见 [docs/agent-trace.md](docs/agent-trace.md)。

## 10. 测试

新增两个测试文件（14 项）：

- `test_agent_graph.py`（fake 组件注入 + 真实 SQLite executor）：
  全流程成功（计数 1/0）、一次 Repair 成功（2/1）、Repair 后仍失败（2/1 停止）、
  Repair Safety 拒绝（1/1 不二次执行）、sql_safety 阶段拒绝（0/0 不 Repair）、
  执行 Safety 错误（0/0）、`graph.compile().invoke()` 可用、
  **不重复调用**（link/retriever/generator 各 1 次）、**数据库零变更**、
  default_components 为真实模块；
- `test_agent_api.py`：成功 200、Repair 成功 200（2/1）、最终失败
  success=false + 诊断、空 question 422、Provider 错误 503。

```bash
pytest -q        # 244 passed（230 原有 + 14 新增）
```

## 11. 真实验证（Live `/api/agent/analyze`，真实 Mimo + 真实 SQLite）

- 第一次调用：`503 {"error":"Mimo network error"}`（官方端点断连，如实记录）；
- 稍后重试：**真实成功**——
  `generated_sql: SELECT region, COUNT(*) AS user_count FROM users GROUP BY region ORDER BY user_count DESC LIMIT 1`，
  执行返回 `广东 246`（1 行），`execute_count=1, repair_count=0, success=true`，
  全部为真实 Mimo 生成并经 Safety 校验、真实 SQLite 只读执行。

## 12. 当前限制

```text
结论生成 / 图表：未实现
自由 ReAct / 多 Agent / Multi-turn：未实现（控制式编排）
无限 Repair 自循环：不存在（有界 <=1 次 / <=2 次执行）
Trace UI：未实现（后续阶段）
Evaluation Benchmark：未实现（后续阶段）
前端：未修改
数据库：未修改（全程只读，SHA256 前后一致 65E5D8B2...）
无新增依赖（langgraph 为既有）
```