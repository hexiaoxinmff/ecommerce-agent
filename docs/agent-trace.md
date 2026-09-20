# Agent Trace（Execution Trace）说明

> 阶段：阶段 4-任务 9（Agent Trace / Execution Trace 基础能力）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 设计目标

为 LangGraph Agent 增加**可观测、结构化、按节点记录**的执行 Trace，回答：
执行到哪一步、每步是否成功、每步耗时、输入/输出摘要、是否调用 Repair、
第几次 SQL 执行、最终成功/失败原因。

**不新增任何 AI 能力**：只记录已有流程；Trace 不影响 `repair_count ≤ 1`、
`execute_count ≤ 2` 的有界语义。

> **Trace 当前仅存在于单次 Agent Run 的内存 State 与 API Response 中，不持久化。**

## 2. TraceEvent 结构（app/trace/models.py）

```python
class TraceEvent(BaseModel):
    sequence: int = Field(ge=1)          # 全局序号，严格递增
    node: str = Field(min_length=1)
    status: Literal["success", "error", "skipped"]
    duration_ms: float = Field(ge=0)     # perf_counter 耗时
    message: str = ""
    input_summary: dict = {}             # 轻量摘要
    output_summary: dict = {}            # 轻量摘要
```

## 3. AgentState 中的 Trace（app/agent/state.py）

```python
trace: Annotated[list[dict], operator.add]   # reducer 追加
trace_final: list[dict]                      # result 节点写回的规范化/补全结果
```

## 4. 使用什么 reducer

Trace channel 显式使用 `Annotated[list[dict], operator.add]`：
节点只需返回 `{"trace": [event]}`，LangGraph 自动追加，避免并发覆盖问题。

## 5. Trace Node 列表

```text
schema_link / fewshot_retrieve / sql_generate / sql_safety /
sql_execute / sql_repair / sql_execute_repaired / result
```

固定顺序用于最终排序与 skipped 补全。

## 6. Status 定义

```text
success  - 节点执行成功
error    - 节点逻辑失败 / 异常（Safety 拒绝、执行数据库错误、Repair 拒绝、Provider 错误）
skipped  - 条件分支未命中（含已失败终止后未执行的固定边节点）
```

## 7. duration_ms 计算方式

`time.perf_counter()` 起止；只统计当前 Node，互不混淆；保证 `>= 0`。

## 8. input_summary / output_summary

只记录摘要，禁止塞入完整 State / 完整 SQL / 查询结果全集 / 用户隐私：
- schema_link：in {question}；out {tables, columns_count, confidence}
- fewshot_retrieve：out {match_count, example_ids}
- sql_generate：out {sql_length, tables}
- sql_safety：out {allowed}
- sql_execute / sql_execute_repaired：out {row_count, truncated}（**不含 rows**）
- sql_repair：out {repair_success, repaired_sql_length, error}
- result：out {success}

完整 `generated_sql / repaired_sql / execution_result` 仍在 AgentResult 中保留（核心证据），Trace 不做重复副本。

## 9. 错误记录

错误 Node 记录 `status=error` 与 `message`；执行/错误信息一律经
`sanitize_execution_error` 清洗（过滤路径/密钥长串），禁止 Trace 泄漏
API Key / .env 内容 / 数据库路径 / 连接串。

## 10. Repair Trace

```text
sql_execute             error     SQL 执行失败: no such table: user
sql_repair              success   repair_success:true
sql_execute_repaired    success   row_count:15
result                  success
```

## 11. skipped Trace

- 正常路径：`sql_repair(skipped)`、`sql_execute_repaired(skipped)`；
- 首次 Safety 拒绝：`sql_execute/sql_repair/sql_execute_repaired` 全部 skipped
  （并给出可解释 message，如 "未执行（SQL Safety 未通过）"）。

## 12. execute_count / repair_count 对齐

| 场景 | execute_count | 对应 Trace |
|---|---|---|
| 正常 | 1 | sql_execute(success)=1 |
| Repair 成功 | 2 | sql_execute(error) + sql_execute_repaired(success) |
| Repair 后仍失败 | 2 | sql_execute(error) + sql_execute_repaired(error) |
| Safety 拒绝 | 0 | sql_execute(skipped) |

Repair 节点（error/success 且非 skipped）数量 == repair_count。

## 13. Provider 错误 Trace

节点异常（如 SchemaLinker 抛 `LLMNetworkError`）→ 记录 `schema_link(error)` +
`fewshot_retrieve/sql_generate/...` 为 skipped，并置 `http_status`（认证 502，其余 503）
供 API 层映射；**不吞异常语义**（对外错误文案与既有一致），Trace 不因异常丢失。

## 14. total_time_ms

`run_agent` 入口计时、结束记录——整个 Graph Run 总耗时（不是某节点），
与各节点 duration_ms 可对比（Schema / Few-shot / SQL / Execute / Repair 各自耗时清晰可见）。

## 15. API 响应

`POST /api/agent/analyze` 响应增加：

```json
{
  "success": true,
  "result": {
    "question": "...",
    "success": true,
    "generated_sql": "...",
    "execute_count": 1,
    "repair_count": 0,
    "total_time_ms": 35229.0,
    "trace": [
      {"sequence": 1, "node": "schema_link", "status": "success", "duration_ms": 22771.3, ...}
    ]
  }
}
```

不新增 Trace 专用接口（不持久化）。

## 16. 测试

新增 `backend/tests/test_agent_trace.py`（25 项，fake 组件 + 真实 SQLite）：

- 正常路径顺序与 skipped 补全、全节点覆盖、status 枚举、sequence 严格递增、
  duration>=0、节点唯一性、计数一致性（3 组参数化）、摘要轻量、total_time；
- Repair 成功 / 最终失败路径顺序与计数；
- Safety 拒绝（execute/repair/repaired = skipped，计数 0/0）；
- Repair 输出被拒（不二次执行）；
- Provider 错误（schema_link=error、Trace 保留、无密钥泄漏、后续 skipped）；
- 数据库零变更（正常 / Repair / Safety / 恶意 Repair 四场景后 SHA256 一致）。

```bash
pytest -q        # 269 passed（244 原有 + 25 新增）
```

## 17. 真实验证

### 真实 SQLite（scripts/test_agent_graph.py，fake LLM 不调用 Mimo）

- 正常查询：5 节点 success + repair/repaired skipped，执行 15 行；
- Execute Error → Repair → Execute Success：sql_execute(error) → sql_repair(success)
  → sql_execute_repaired(success)，execute_count=2，执行 15 行；
- Safety Reject：sql_safety(error) + 三个后续 skipped，execute_count=0。

### 真实 Mimo（scripts/test_agent_graph_real.py）

`近30天销售额最高的商品有哪些？` 真实成功：生成 SQL 并真实执行 **481 行**，
execute_count=1，Total Time 35.2s；Trace 可见 schema_link 22.8s / sql_generate 12.4s /
execute 5.9ms 各节点真实耗时。

### Live /api/agent/analyze

两次调用均因官方端点断连返回 503 `Mimo network error`（结构化、无泄漏），如实记录；
全链路含 Trace 的真实成功已由脚本验证。待上游恢复后即可复现 Live 200 + Trace。

## 18. 当前限制

```text
Trace 不持久化（单次请求内存/响应）
前端真实 Trace UI：未实现（本任务只保证后端真实 Trace 数据）
Multi-turn / Chart / Conclusion：未实现
数据库表 / 文件日志 / Redis：未引入
前端：未修改
数据库：未修改（SHA256 前后一致 65E5D8B2...）
无新增依赖
```