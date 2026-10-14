# RELEASE BASELINE MANIFEST — 2026-09-20

> Phase 2F — Release Baseline Freeze
> Verdict: **RELEASE_BASELINE_FROZEN**

机器可读版本：`reports/RELEASE_BASELINE_MANIFEST.json`

---

## 1. Baseline Identity

| 项目 | 值 |
|---|---|
| Current Development Baseline | **`35a9ad6`** |
| Commit (full) | `35a9ad61a9616619c1324fda68de69b6ae19996c` |
| Commit subject | `docs: finalize Phase 2E report tip` |
| Branch | `master` |
| HEAD symbolic ref | `refs/heads/master` |
| HEAD == master | **YES** |
| Release tag | **`release_baseline_20260920`** |
| Tag target | `35a9ad61a9616619c1324fda68de69b6ae19996c` |
| Tag type | lightweight |
| Tag ref file | `.git/refs/tags/release_baseline_20260920`（41 B，已落盘验证） |
| 含 `/` 的 ref 名 | **无** |
| Commit 内容被修改 | **否** |

## 2. Git State

- git version：`2.55.0.windows.3`
- `core.autocrlf`：`true`

**Branches**

| 分支 | Commit | 说明 |
|---|---|---|
| `master` | `35a9ad6` | 正式基线 |
| `candidateA_promotion_20260920` | `35a9ad6` | 与 master 同点 |
| `recovery_master_20260920` | `518cd896` | **恢复锚点，保留未删** |

**Tags**

| Tag | Commit |
|---|---|
| `release_baseline_20260920` | `35a9ad6` |

**Commit tip**

```text
35a9ad6 (HEAD -> master, tag: release_baseline_20260920, candidateA_promotion_20260920) docs: finalize Phase 2E report tip
df83d0a docs: correct Phase 2E report final state
7286d11 docs: Phase 2E final promotion report
6814153 docs: Phase 2C recovery report + Candidate A promotion manifest
019b18a perf: promote Candidate A runtime reuse
```

**Linked worktrees**（只读记录，未改动）

| 路径 | HEAD | 分支 |
|---|---|---|
| `F:/基于 Text2SQL 的电商智能数据分析 Agent` | `35a9ad6` | `master` |
| `C:/Users/29593/WorkBuddy/Worktrees/.../master-b947f329` | `80a09b5` | `workbuddy/master-b947f329` |
| `C:/Users/29593/WorkBuddy/Worktrees/.../master-de8ad9a1` | `80a09b5` | `workbuddy/master-de8ad9a1` |
| `C:/Users/29593/WorkBuddy/Worktrees/.../master-e516219f` | `80a09b5` | `workbuddy/master-e516219f` |

## 3. Candidate A Production State

**状态：`IN_MASTER`**

- 入 master 于 `019b18a perf: promote Candidate A runtime reuse`
- 提升分支 `candidateA_promotion_20260920`，HEAD `35a9ad6`
- 未改变可观察语义（`observable_semantics_changed: false`）

**Five Sources SHA256**

| 文件 | SHA256 | `git hash-object` |
|---|---|---|
| `backend/app/agent/graph.py` | `9d09cbae3de49521cef242e106e967b8065aa368c9a6dcc0183b16503d14a25b` | `cbfff471bcc84acbdef0c72f38dc83b7f04d6d70` |
| `backend/app/schema/metadata.py` | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` | `88f829e09e687d706b9193ec54ee3da58e50c249` |
| `backend/app/llm/mimo.py` | `2eddd623bf8db37a91cf9462783eba6f462944c08363c977540999750e2be403` | `3f79645d53f63cb136b2ce50139f5b2194abe754` |
| `backend/app/sqlgen/safety.py` | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` | `cf2f597903dcaf1908b5c3c39752ef1f3ec5281d` |
| `backend/app/sqlgen/validator.py` | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` | `0c24047b98dcf0145ef7041841e8c5a16dc28ee7` |

**Test SHA256**

| 文件 | SHA256 |
|---|---|
| `backend/tests/test_task29_runtime_reuse.py` | `5d6282299832c69e7b75a5a5a768ba1307661a529940cfc24cd0cb0bf4d52383` |
| `backend/tests/conftest.py` | `3aec65b806a228b5d611f93080f23d776398c4c7c7adf8d28cdfde483c376599` |

**四处优化**

1. `graph.py` — `get_default_graph()` 进程级图缓存（`_DEFAULT_GRAPH_CACHE` / `clear_default_graph_cache`）
2. `metadata.py` — `SchemaCatalog.get_cached()` / `clear_cache()`（每请求 12 条 SQLite 连接 → 0）
3. `mimo.py` — `MimoProvider._get_client()` 实例内复用（`max_retries=0`）
4. `safety.py` — `check_sql_safety_with_tables()` 单次 sqlglot 解析；`validator.py` 改用之

## 4. Experimental Component Isolation

**Production**

- `SchemaLinker`（`LINKER_MODE=llm`，经 `create_schema_linker()`）
- `Candidate A`（运行时复用优化）

**Not Production**

| 组件 | 文件 | 裁决 | 原因 |
|---|---|---|---|
| Rule Linker | `backend/app/schema/rule_linker.py` | `BLOCKED` | Task 30/31：Sufficiency 88.9% < 98% |
| Coverage Guard | `backend/app/schema/coverage_guard.py` | `BLOCKED` | Task 32：召回 1/4（真实 0/4），上界锁死 87.5% |
| Hybrid Linker | `backend/app/schema/hybrid_linker.py` | `BLOCKED` | Task 32：上界由召回决定 |
| Schema Retrieval | `backend/app/agent/schema_retrieval.py` | `INCONCLUSIVE` | Task 34：无配置满足「高召回 + 明显更小候选集」 |

`experimental_wired_to_production: false` —— 以上组件**均未接入生产链路**。

## 5. Test Baseline

```bash
python -m pytest backend/tests
```

| 项目 | 值 |
|---|---|
| 解释器 | `.venv/Scripts/python.exe` |
| Python | `3.12.10` |
| pytest | `9.1.1` |
| **passed** | **399** |
| failed | 0 |
| errors | 0 |
| skipped | 0 |
| warnings | 1（starlette `BlockingPortal` 弃用告警） |
| 耗时（报告值） | `27.62s` |
| 耗时（墙钟） | `32s` |
| 结果 | **PASS** |

## 6. Safety Baseline

- 状态：**PASS**（含于 399 passed 内，覆盖于 `backend/tests/test_sql_executor.py` 与 `safety.py` 单测）
- Candidate A 安全回归：**29 样本 0 差异**（Task 35 复测结论）

## 7. Frozen Asset Hashes

| 资产 | 路径 | SHA256 | 冻结记录 | 结论 |
|---|---|---|---|---|
| Prompt V1.3 | `data/prompts/sql_generator_v1.3.txt` | `2af938be9866a62a97fdc3f1b0c7dc43b0785a7ff75ad420109b1d18ed39dc4c` | `10583478` | MATCH |
| FEWSHOT_V3 | `data/fewshot/ecommerce_examples.json` | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` | `ee12fcc9` | MATCH |
| Dataset (ECO-SQL-Bench) | `data/eval/ecommerce_eval_v1.json` | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` | `dba277cc` | MATCH |
| DB | `db/ecommerce.db` | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9` | — | 2,912,256 B |
| Clean Baseline eval | `reports/eval/clean_baseline_v1_1/eval_clean_baseline_v1_1.json` | `39404fedef84b338cc7b48ed2972db98c7c574cd8cfca196ca02f7843e42f66e` | `39404fed` | MATCH（418,828 B） |
| `sqlglot` | — | `30.18.0` | `30.18.0` | MATCH |

**附属 Few-shot / 数据集哈希**

| 文件 | SHA256 |
|---|---|
| `data/fewshot/ecommerce_examples_fewshot_v1.json` | `3c8dc8eac8f69082c085ab357f1f6d5dd6cb4efe272d7a56f1ba7b03180a233a` |
| `data/fewshot/ecommerce_examples_v1_leaky.json` | `3c8dc8eac8f69082c085ab357f1f6d5dd6cb4efe272d7a56f1ba7b03180a233a` |
| `data/fewshot/ecommerce_examples_v2_leaky.json` | `39dd2cee9476953bb83c9e5e2083c925d7741719fda44029c938180c1d8d730d` |
| `data/eval/error_taxonomy_v2.json` | `173f836951dec65bae203c863427199d899cdf05d135e758cbe375fd8a69d82c` |

Clean Baseline 目录其余文件：

| 文件 | SHA256 |
|---|---|
| `bad_case_comparison.json` | `6c4eda5463497b0d09ca3bb546d81bb10417971356bd6e321a7f882f0b5e01a8` |
| `clean_baseline_v1_1.md` | `6a6a137d7757bc863a310005281341a90d8f8a0eda4384cd8d5c70dba55237e0` |
| `experiment_config.json` | `5c83c64e642652d37a92311331956ab5cb1b5fd3e437dc3fb810593773302db0` |
| `metadata.json` | `f3c3c077e9ca64fb1863c78392348edc2de7b7c5a0ec4eb80c156aa941f5ea2a` |
| `raw_runner_report.md` | `54fcc6eb88004db1b73301d2771879dbd7a0c34dc98182fd470360011f419243` |

> ⚠️ 口径提醒：生成器写入的 `dataset_sha256` 覆盖 `items` 逻辑内容而非文件字节，二者不同是设计使然；此处列的是**文件字节**哈希。

## 8. Performance Measurement Scope

`Local deterministic`（确定性本地基准）

```text
BEFORE  29.074 ms
AFTER    1.955 ms
DELTA   -93.3%
```

`Historical provider-backed`（历史 provider 支撑证据）

```text
~836 ms/call  client reuse evidence
```

`Current real E2E`

```text
NOT_MEASURED

Reason:
  Mimo HTTP 402 Insufficient account balance
```

**禁止表述**：

```text
❌ E2E latency improved 93.3%
```

三层证据（本地确定性 / 历史 provider 支撑 / 当前 E2E）**不得混用**。

## 9. Recovery Anchor

| 项目 | 值 |
|---|---|
| Ref | `recovery_master_20260920` |
| Commit | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| Short | `518cd896` |
| Subject | `recovery: reconstruct master baseline 2026-09-20` |
| 是否存在 | **YES** |
| 是否删除 | **NO** |

构建方式：`git write-tree` + `git commit-tree`（**0 parent，不猜祖先**）。

## 10. Backup Location

```text
C:\Users\29593\Desktop\Text2SQL_Agent_ReleaseBackup_20260920\
```

| 项目 | 值 |
|---|---|
| 方法 | 物理 `cp -r`（`.git` + 完整工作树）；**非 git export** |
| 状态 | **COMPLETE** |
| 第 2 次尝试 | `cp` rc=0 / rc=0，**stderr 零报错** |
| `.git` 字节 | 53,223,332（源 53,223,332，**逐字节相同**） |
| 工作树文件数 | 12,337（源 12,337，**相同**） |
| 总计 | 404,054,901 B（≈416 M） |

**备份验证**

| 检查 | 结果 |
|---|---|
| `backup HEAD` | `35a9ad61a9616619c1324fda68de69b6ae19996c` ✓ |
| `backup master` | `35a9ad61a9616619c1324fda68de69b6ae19996c` ✓ |
| `backup tag` | `release_baseline_20260920 -> 35a9ad6` ✓ |
| tag ref 文件 | 存在于备份 `.git/refs/tags/` ✓ |
| 分支列表 | 与源一致 ✓ |
| `git fsck --connectivity-only` | 仅既有 dangling 对象，**无损坏** ✓ |

> 首次尝试 **FAILED**：第二条 `cp -r "$SRC/."` 的目标已含 `.git`，造成自我覆盖与约 57 个 `Permission denied`。
> 已清空目标目录重做：**.git 独占复制在前**，再 `find -maxdepth 1 ! -name .git` 复制其余。第二次干净通过。

## 11. Known Limitations

| ID | 级别 | 限制 |
|---|---|---|
| L1 | HIGH | **真实 E2E 延迟未测量** —— provider HTTP 402（余额不足）。不得对本基线作端到端延迟声明。 |
| L2 | MEDIUM | `mimo.py` 把 402 误映射为 `LLMServiceUnavailableError`。**按指令未修**（Phase 2F 禁止触碰 402）。 |
| L3 | MEDIUM | 原 master 对象 `d668e6a6` **永久不可恢复**（`ORIGINAL_MASTER_COMMIT_UNRECOVERABLE`）。当前基线为重建 commit `518cd896` 向前演进至 `35a9ad6`；`518cd896` 之上**无祖先被伪造**，也**不可恢复**。 |
| L4 | MEDIUM | Schema Linking 实验线全部 `BLOCKED` / `INCONCLUSIVE`，均未接生产。Task 31 实测 **泛化差距 11.1pp** 仍是头号方法论结论。 |
| L5 | LOW | `core.autocrlf=true` 会产生幽灵 modified 条目（零内容差异）。当前 tracked clean。 |
| L6 | LOW | Git `2.55.0.windows.3` 在 F: 盘**无法创建含 `/` 的 ref**（静默失败）。本 release 全部 ref 无斜杠。**永久约束。** |
| L7 | LOW | 4 个 untracked 文件**有意保留**：`.workbuddy-ai/memory/{MEMORY.md,2026-09-20.md}`、`reports/CANDIDATE_A_PROMOTION_REVIEW.{md,json}`。未删、未 add。 |

## 12. Task 36 Entry Gate

```text
Task 36:
  NOT STARTED

Entry baseline:
  35a9ad6

Recovery anchor:
  518cd896

Release tag:
  release_baseline_20260920

Tests:
  399 passed

Production:
  Candidate A active

Provider:
  E2E measurement unavailable due to HTTP 402
```

**Gate 状态：`OPEN_FOR_TASK_36`** —— 仅登记状态，**未执行 Task 36**。

---

## Phase 2F 约束遵守清单

| 约束 | 是否触碰 |
|---|---|
| 业务源码 | NO |
| 测试 | NO |
| Prompt | NO |
| Few-shot | NO |
| Benchmark | NO |
| DB | NO |
| Linker | NO |
| Schema Retrieval | NO |
| Rule / Coverage / Hybrid | NO |
| 修 402 | NO |
| 进入 Task 36 | NO |
| merge / rebase | NO |
| push | NO |
| 删除 recovery ref | NO |
| `git gc` / `git prune` / `git clean` | NO |
| 含 `/` 的 ref 名 | NO |
| 修改 commit 内容 | NO |

---

**Status: `RELEASE_BASELINE_FROZEN`**
