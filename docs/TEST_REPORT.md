# 测试报告（Test Report）

> 依据：**Task 23 最终技术验收**（2026-09-16）实测数据。
> 本报告不重新造假、不夸大；引用数字均标注来源。

---

## 1. 总体结论

| 项 | 结果 |
|---|---|
| **pytest** | **367 passed**（来源：Task 23 最终技术验收实测） |
| FastAPI routes | 10 条真实可达 |
| OpenAPI schema | 10 paths 可生成、`/docs` 可访问 |
| Frontend build | 通过（`tsc -b && vite build`，仅 chunk>500kB 警告） |
| Frontend lint | 通过（oxlint：0 errors、1 warning） |
| E2E Smoke | 5 条真实问题全链路成功（真实 Mimo） |

> 复现命令：**从项目根目录运行**（`test_eval_runner.py` 中的 Gold Hash Gate 用例依赖根目录相对路径 `data/eval/ecommerce_eval_v1.json`）：

```bash
python -m pytest backend/tests
# 或使用本地虚拟环境：
.venv\Scripts\python.exe -m pytest backend/tests
```

---

## 2. 单元测试（Unit Test）

测试文件位于 `backend/tests/`，覆盖以下模块：

| 模块 | 测试文件 | 覆盖点 |
|---|---|---|
| Detector（E3，冻结） | `test_e3_fanout_detector.py` | Gold-independent 静态 Fan-out 检测；粒度风险识别；E-0086 模式 |
| Hint（E3，冻结） | `test_task20_hint.py` | Hint 注入 / 单次 regeneration 机制 |
| telemetry（E3，冻结） | `test_task18_telemetry.py` | Detector telemetry 记录 |
| SQL 安全 / 校验 | `test_sqlgen_prompt_rules.py`、`test_sql_executor.py`、`test_sql_generate_api.py` | 只读白名单、多语句禁止、LIMIT 注入、Prompt 规则 |
| Agent 组件 | `test_agent_graph.py`、`test_agent_api.py`、`test_agent_trace.py` | 有界 Repair（≤1/≤2）、Trace 结构、DB 只读 |
| Schema Linking | `test_schema_linking.py`、`test_schema_link_api.py` | 表/字段/置信度、真实 Schema 复核 |
| Few-shot | `test_fewshot_retriever.py`、`test_fewshot_dataset.py`、`test_fewshot_api.py` | 规则检索、Top-K 排序、数据集校验 |
| SQL 生成 | `test_sql_generator.py`、`test_sql_generate_api.py` | 生成 + 只读校验 |
| SQL 修复 | `test_sql_repair.py`、`test_sql_repair_api.py` | 有限单次修复、二次校验/执行 |
| LLM Provider | `test_llm_provider.py`、`test_llm_api.py` | 异常映射（401/403→502、429/5xx/超时→503） |
| 数据库只读层 | `test_database.py` | mode=ro + query_only、DB hash 前后一致 |
| 健康检查 | `test_health.py` | `/api/health` 探活 |
| 评测框架 | `test_eval_runner.py`、`test_eval_units.py`、`test_validate_eval_dataset.py` | Gold Hash Gate、Leakage Gate、EX 归一化 |

## 3. 集成测试（Integration）

| 关注点 | 说明 |
|---|---|
| FastAPI | 所有路由经 `TestClient` 调用；错误状态码约定（422/500/502/503）统一 |
| SQL 执行 | 只读执行全链路：safety 校验 → mode=ro 执行 → 结果截断保护 |
| Repair | `execute-with-repair` 闭环：Safety → Execute → Repair(≤1) → 二次 Safety → 二次 Execute |

## 4. 前端（Frontend）

| 项 | 结果 |
|---|---|
| `npm run build`（tsc -b && vite build） | 成功（PASS） |
| `npm run lint`（oxlint） | 0 errors、1 warning（react-refresh only-export-components） |

## 5. 端到端 Smoke（E2E）

5 条真实问题、真实 Mimo、全链路（`POST /api/agent/analyze`），全部 `success`。
完整记录：`reports/eval/task23_final_acceptance/e2e_smoke.json`。

| # | 问题 | 结果 |
|---|---|---|
| Q1 | 哪个地区的用户最多？ | success，`region+COUNT`，1 行（广东 246） |
| Q2 | 哪个类目的销售额最高？ | success，4 表 JOIN，1 行（家用电器 8290243.71） |
| Q3 | 2025 年每月销售额是多少？ | success，月度 GROUP BY，12 行 |
| Q4 | 近30天销量最高的商品 Top 5 是哪些？ | success，JOIN + 排名，5 行 |
| Q5 | 那这些商品分别属于哪个类目？（多轮追问） | success（**单轮行为边界**：重新生成、未携带上下文 —— 验证当前为单轮 Agent，Multi-turn 属 PRD 阶段 2） |

## 6. 评测回归（Evaluation，非重新跑 Benchmark）

- 本报告引用的是 **Task 23 已验收结果**，本次文档阶段**不重新跑 100 条 Benchmark**；
- 相关评测验证门禁历史记录：Clean Baseline v1.1 报告 显示其运行前 pytest = **357 passed**（来源：`reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` 卫生检查表）；
- Task 23 最终技术验收追加了 E3 相关测试后，pytest 增长至 **367 passed**；
- 评测数据与上述 367 个测试互不干扰（评测不修改 DB / Gold / Prompt / Few-shot）。

## 7. 已知未覆盖 / 边界（如实声明）

- 无登录 / 用户管理 / 多轮 conversation API（PRD 阶段 2 / Out-of-Scope），因此无对应测试；
- E2E 为 5 条 smoke 用例，不构成全量回归（全量回归由 100 条 Benchmark 承担）；
- 前端 `datasets / history / settings` 为占位页，无自动化 UI 测试。

---

*数据来源：Task 23 FINAL_ACCEPTANCE_REPORT（2026-09-16）、Task 15 clean_baseline_v1_1 报告（提及 357 passed）。文档阶段未重新跑 100 条 Benchmark、未修改任何冻结实验数据。*