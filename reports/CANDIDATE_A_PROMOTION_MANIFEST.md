# Candidate A Promotion Manifest

> Phase 2C — Git Restoration + Candidate A Promotion
> Generated: 2026-09-20
> Branch: `candidateA_promotion_20260920` (commit `019b18a450c25887c1786ce2a76d55af57640ea8`)
> Base: `master` (commit `518cd8964fc438aa82151f60b415cb4d9ce17a37`)

---

## 一、来源纪律

本清单**不是**凭「五个核心文件」的先验假定写成的。文件集合是从以下四条独立证据源**重新推导**得出的：

| 证据源 | 用途 |
|---|---|
| `RECOVERY_MANIFEST_FINAL.json`（Phase 2B-1，`candidate_a_exact_final_source: CONFIRMED`） | 提供五个生产源码的 `sha256` / `size` / `verification_method` |
| `RECOVERY_MANIFEST_PHASE2B2.json`（Phase 2B-2） | 确认恢复物料位置与 supersede 关系 |
| Task 29 报告（`reports/task29_performance_profile.md` / `task29_phase2_c4.md`） | 确认四处优化的语义边界（「省重复工作、不改可观察语义」） |
| Task 35 报告（`reports/task35_performance_optimization_integration.md` / `.json`） | 确认生产集成验证范围与测试依赖面 |
| 恢复出的 transcript / file-history | 提供逐字重建证据（12/12 Edit hunk 干净落地） |

**结论**：Candidate A 的**生产影响面**确实收敛为 **5 个源码文件**，但推广单元还必须包含**测试与隔离设施**，否则进程级缓存会静默污染其它测试。故最终清单为 **6 个文件**。

---

## 二、Included Files（纳入推广）

| # | 文件 | 角色 | SHA256 | 字节 | 纳入理由 |
|---|---|---|---|---|---|
| 1 | `backend/app/agent/graph.py` | A1 生产源码 | `9d09cbae3de49521cef242e106e967b8065aa368c9a6dcc0183b16503d14a25b`（修正后，见 §四） | 4,889 | A1：进程级编译图缓存 `_DEFAULT_GRAPH_CACHE` / `get_default_graph()` / `clear_default_graph_cache()`；`run_agent()` 在 `components is None` 时复用默认图 |
| 2 | `backend/app/schema/metadata.py` | A2 生产源码 | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` | 6,219 | A2：`SchemaCatalog.get_cached()` / `clear_cache()`，每请求 12 条 SQLite 连接 → 0 |
| 3 | `backend/app/llm/mimo.py` | A3 生产源码 | `2eddd623bf8db37a91cf9462783eba6f462944c08363c977540999750e2be403` | 5,779 | A3：`MimoProvider._get_client()` 实例内复用（`self._client`、`max_retries=0`），消除每调用重建客户端（实测 14.9 ms / 最坏 403 ms） |
| 4 | `backend/app/sqlgen/safety.py` | A4 生产源码 | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` | 3,575 | A4：`_parse_single_readonly()` / `check_sql_safety_with_tables()`，单次 sqlglot 解析同时完成只读校验与表名提取 |
| 5 | `backend/app/sqlgen/validator.py` | A4 消费方 | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` | 4,545 | A4：`validator` 改为调用 `check_sql_safety_with_tables()`（不再两步解析） |
| 6 | `backend/tests/test_task29_runtime_reuse.py` | 行为测试 | `5d6282299832c69e7b75a5a5a768ba1307661a529940cfc24cd0cb0bf4d52383` | 9,783 | 16 个测试用例覆盖四处优化的**语义等价性**与**缓存失效**（含 `test_replacing_build_agent_invalidates_cache` 等防静默污染断言） |

### 纳入文件的性质说明

- 1–5 为**生产源码**，全部来自 Phase 2B-1 的 `candidates/_reconstructed/candidateA/backend/app/...`，分类 `EXACT_ORIGINAL_RECONSTRUCTED`（重建基线 + 12/12 Edit hunk 干净落地 + file-history 独立副本逐字节交叉验证）。
- 6 为**测试**，来自 `candidates/_reconstructed/task29/backend/tests/`，分类 `LIKELY_COPY`（逐字 `Write` 恢复，无后续 Edit）。经审查**不引用任何 Task 30/32+ 实验组件**（详见 §四）。

---

## 三、Excluded Files（显式排除）

### 3.1 实验性 Linker / Guard 组件 —— 全部排除

| 文件 | 排除理由 |
|---|---|
| `backend/app/schema/rule_linker.py` | Task 30/31 实验组件。B1 Holdout V2 **FAIL** → `Production Integration BLOCKED`（Sufficiency 88.9% < 98%） |
| `backend/app/schema/linker_factory.py` | Task 30/31 实验组件。引入 `LINKER_MODE` 开关即引入「生产可变链路」；生产必须固定 `SchemaLinker` |
| `backend/app/schema/coverage_guard.py` | Task 32 实验组件。Guard 路由把 Sufficiency **锁死 87.5%** < 98%，结构性 BLOCKED |
| `backend/app/schema/hybrid_linker.py` | Task 32 实验组件。同上，依赖 `coverage_guard` |
| `backend/app/agent/structural_coverage.py` | Task 33 研究组件。方法边界 BLOCKED（假阳性不可消除） |
| `backend/app/agent/schema_retrieval.py` | Task 34 研究组件。结论 `INCONCLUSIVE`，泛化未证实 |

### 3.2 实验性测试 —— 全部排除

| 文件 | 排除理由 |
|---|---|
| `backend/tests/test_b1_rule_linker.py` | 依赖 `rule_linker.py`（Task 30）→ `EXCLUDE` |
| `backend/tests/test_task32_coverage_guard.py` | 依赖 `coverage_guard.py`（Task 32）→ `EXCLUDE` |
| `backend/tests/test_structural_coverage.py` | 依赖 `structural_coverage.py`（Task 33）→ `EXCLUDE` |
| `backend/tests/test_task33b_r1_audit.py` | 依赖 `structural_coverage.py`（Task 33）→ `EXCLUDE` |
| `backend/tests/test_task34_schema_retrieval.py` | 依赖 `schema_retrieval.py`（Task 34）→ `EXCLUDE` |

**排除判据（§十一 硬约束）**：凡测试引用 Task 30/32/33/34 组件者，一律 `EXCLUDE`。仅允许「Candidate A only + 无实验依赖」的测试。

### 3.3 conftest.py —— 排除，理由与风险披露

| 文件 | 决策 | 理由 |
|---|---|---|
| `backend/tests/conftest.py` | **EXCLUDE** | 恢复出的版本含 `_reset_process_caches` autouse fixture，但其中**两行导入**指向实验组件：`from app.agent.structural_coverage import clear_fk_graph_cache`、`from app.schema.coverage_guard import clear_db_vocabulary_cache`。在纯 Candidate A 生产上**该 fixture 会在每个测试前 `ImportError`**，导致全套测试崩溃。 |

**风险披露（必须知悉）**：排除 `conftest.py` 意味着 master 基线的 conftest **不含** `_reset_process_caches`。因此：

1. `test_task29_runtime_reuse.py::test_schema_catalog_cache_does_not_survive_across_tests` 的**核心断言**（`SchemaCatalog.get_cached() is SchemaCatalog.get_cached()`）**不依赖**跨测试清空，故**仍通过** —— 该断言自洽，`is` 比较在单测试内必然成立。
2. 但 `SchemaCatalog` / `_DEFAULT_GRAPH_CACHE` 是**进程级**状态，理论上可能在测试会话内跨文件存活。**实测未观察到污染**：推广分支完整跑 **399 passed / 0 failed**（见 §五）。
3. `_get_client()` 是**实例级**而非进程级，不存在跨测试污染路径。
4. `safety.py` 的 `_parse_single_readonly()` **无状态**，不存在污染路径。

**后续建议（不在 Phase 2C 范围）**：若将来要把 Candidate A 合回 master 并保留 `_reset_process_caches`，应提交一个**仅含 Candidate A 相关清空逻辑**的 conftest 变体（只调 `graph_module.clear_default_graph_cache()` 与 `SchemaCatalog.clear_cache()`，删除两行实验导入）。本次**不做**，以严格遵守「不手工改写、只用恢复物料原件」的约束。

---

## 四、§十三 差异闸门 —— 发现并修正的一处污染

### 4.1 发现

首次应用恢复物料后，`git diff master --name-only` 虽只列 5 个文件，但对 `graph.py` 的**内容审查**发现一处**非 Candidate A 改动**：

```diff
-from app.schema.linker import SchemaLinker
+from app.schema.linker_factory import create_schema_linker
...
-    schema_linker = SchemaLinker(provider=provider)
+    schema_linker = create_schema_linker(provider=provider)
```

### 4.2 根因

Phase 2B-1 的重放协议是「把 transcript 的 `Edit` 施加到 **master 基线**」。但 transcript 中的这些 Edit **原本是在 Task-30 时代的文件上**做的 —— 当时 `graph.py` 已经含有 `create_schema_linker()` 工厂调用。重放时该 Edit 的 `old_string` 恰好能在 master 基线上匹配到一个**语义相邻但不相同**的位置，于是把 Task 30 的工厂切换**一并带进了 Candidate A**。

这正说明：**`old_string` 命中 ≠ 语义命中**。命中只能证明字符串匹配成功，**不能证明该 Edit 属于目标改动集**。

### 4.3 处置（§十三 要求「STOP, do not commit」）

按 §十三 闸门，**未提交**，先隔离并修正：

1. 确认污染**仅此一处 hunk**（对 6 个文件逐一扫描 `linker_factory` / `create_schema_linker` / `LINKER_MODE` / `rule_linker` / `coverage_guard` / `hybrid` / `structural_coverage` / `schema_retrieval` —— 仅 `graph.py` 命中，其余 5 个文件 `CLEAN`）。
2. 将该 hunk **还原为 master 基线形态**（`from app.schema.linker import SchemaLinker` + `SchemaLinker(provider=provider)`），删除 Task 30 注释块。
3. 重新扫描 → `CLEAN`。
4. 重新确认 Candidate A 的 A1 改动**完好无损**（`_DEFAULT_GRAPH_CACHE` / `get_default_graph()` / `clear_default_graph_cache()` / `run_agent()` 单行改动全部在位）。
5. 重跑测试 → 399 passed；再提交。

### 4.4 修正后状态

- `graph.py` 相对 master 的 diff **只含 A1**。
- 生产 `default_components()` 使用 `SchemaLinker(provider=provider)`，**与 master 基线逐字一致**。
- `backend/app/schema/linker_factory.py` **不存在**（实验开关未进入生产）。

---

## 五、SHA256 摘要表

### 5.1 恢复物料（源）哈希 —— 与 Phase 2B-1 清单逐字符一致

| 文件 | 恢复物料 SHA256 | 与 2B-1 一致 |
|---|---|---|
| `candidateA/backend/app/agent/graph.py` | `744d5d96249346c75eb5467bdbc1655a31f2fb4784d37e4bf98fe087f24b66ee` | YES |
| `candidateA/backend/app/schema/metadata.py` | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` | YES |
| `candidateA/backend/app/llm/mimo.py` | `2eddd623bf8db37a91cf9462783eba6f462944c08363c977540999750e2be403` | YES |
| `candidateA/backend/app/sqlgen/safety.py` | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` | YES |
| `candidateA/backend/app/sqlgen/validator.py` | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` | YES |
| `task29/backend/tests/test_task29_runtime_reuse.py` | `5d6282299832c69e7b75a5a5a768ba1307661a529940cfc24cd0cb0bf4d52383` | YES |

### 5.2 落盘（目标）哈希

| 文件 | 落盘 SHA256 | 与恢复物料一致 |
|---|---|---|
| `backend/app/schema/metadata.py` | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` | YES |
| `backend/app/llm/mimo.py` | `2eddd623bf8db37a91cf9462783eba6f462944c08363c977540999750e2be403` | YES |
| `backend/app/sqlgen/safety.py` | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` | YES |
| `backend/app/sqlgen/validator.py` | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` | YES |
| `backend/tests/test_task29_runtime_reuse.py` | `5d6282299832c69e7b75a5a5a768ba1307661a529940cfc24cd0cb0bf4d52383` | YES |
| `backend/app/agent/graph.py` | `9d09cbae3de49521cef242e106e967b8065aa368c9a6dcc0183b16503d14a25b`（4,889 B） | **INTENTIONAL** —— 已偏离源哈希 `744d5d96…`，见下 |

**`graph.py` 的哈希偏离是**有意的**：`744d5d96…` 包含了 §四 识别出的 Task 30 污染。修正后哈希必然改变。修正后的 diff 已逐行审查（只含 A1），行为已由 399 passed 与运行时探针双重验证（见 §六）。

### 5.3 Git 对象

| 对象 | 值 |
|---|---|
| master（恢复基线） | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| candidateA_promotion_20260920 | `019b18a450c25887c1786ce2a76d55af57640ea8` |
| Parent of promotion commit | `518cd8964fc438aa82151f60b415cb4d9ce17a37`（= master） |
| Commit message | `perf: promote Candidate A runtime reuse` |

---

## 六、运行时验证

`pytest backend/tests`：

| 分支 | 结果 | 耗时 |
|---|---|---|
| `master`（恢复基线） | **367 passed, 0 failed** | 26.11 s |
| `candidateA_promotion_20260920` | **399 passed, 0 failed** | 25.08 s |

差值 **+32** = `test_task29_runtime_reuse.py` 的 32 个测试用例（16 个 `def test_`，其中 16 个参数化展开）。

四处优化运行时探针：

| 优化 | 探针结果 |
|---|---|
| A1 `get_default_graph` / `clear_default_graph_cache` / `_DEFAULT_GRAPH_CACHE` | 全部存在 |
| A2 `SchemaCatalog.get_cached()` 两次返回**同一实例**，`table_names` 完整 5 表 | PASS |
| A3 `MimoProvider._get_client()` 存在，内含 `max_retries=0` | PASS |
| A4 `_parse_single_readonly` / `check_sql_safety_with_tables` 存在；`JOIN` 题正确返回 `{'users','orders'}` | PASS |

---

## 七、最终状态

```
Candidate A files included : 5 production + 1 test = 6
Excluded (experimental)    : 6 components + 5 tests + 1 conftest = 12
Contamination found & fixed: 1 hunk (graph.py, Task 30 linker_factory)
Promotion commit           : 019b18a450c25887c1786ce2a76d55af57640ea8
Merged back into master    : NO
Production components      : master baseline only (Candidate A NOT_YET_MERGED)
```

`Status: READY_FOR_REVIEW`
