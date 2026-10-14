# Release Baseline — 2026-09-20

> **Phase 2F — Release Baseline Freeze**
> 正式开发基线冻结记录。**非功能开发任务。**

机器可读版本：`reports/RELEASE_BASELINE_20260920.json`
哈希清单：`reports/RELEASE_BASELINE_MANIFEST.{json,md}`

---

## 1. Baseline Identity

```text
Current Development Baseline:
  35a9ad6

Commit (full):
  35a9ad61a9616619c1324fda68de69b6ae19996c

Branch:
  master

HEAD:
  35a9ad61a9616619c1324fda68de69b6ae19996c   (== master)

Release tag:
  release_baseline_20260920  ->  35a9ad61a9616619c1324fda68de69b6ae19996c

Tag type:
  lightweight
```

- Tag 只指向 `35a9ad6`，**未修改 commit 内容**。
- **无任何含 `/` 的 ref 名称**（`git 2.55.0.windows.3` 在 F: 盘创建含斜杠 ref 会静默失败 —— 见 §11 L6）。
- Tag ref 文件已确认落盘：`.git/refs/tags/release_baseline_20260920`（41 B），`git rev-parse --verify` 返回 `35a9ad6…` ✓

## 2. Git State

| 分支 | Commit | 说明 |
|---|---|---|
| `master` | `35a9ad6` | 正式基线 |
| `candidateA_promotion_20260920` | `35a9ad6` | 与 master 同点 |
| `recovery_master_20260920` | `518cd896` | **恢复锚点，保留未删** |

**Tags**

```text
release_baseline_20260920 -> 35a9ad61a9616619c1324fda68de69b6ae19996c
```

**Commit tip**

```text
35a9ad6 (HEAD -> master, tag: release_baseline_20260920, candidateA_promotion_20260920) docs: finalize Phase 2E report tip
df83d0a docs: correct Phase 2E report final state
7286d11 docs: Phase 2E final promotion report
6814153 docs: Phase 2C recovery report + Candidate A promotion manifest
019b18a perf: promote Candidate A runtime reuse
```

**Linked worktrees**（未改动）

| 路径 | HEAD | 分支 |
|---|---|---|
| `F:/基于 Text2SQL 的电商智能数据分析 Agent` | `35a9ad6` | `master` |
| `.../Worktrees/.../master-b947f329` | `80a09b5` | `workbuddy/master-b947f329` |
| `.../Worktrees/.../master-de8ad9a1` | `80a09b5` | `workbuddy/master-de8ad9a1` |
| `.../Worktrees/.../master-e516219f` | `80a09b5` | `workbuddy/master-e516219f` |

**环境**：git `2.55.0.windows.3`，`core.autocrlf=true`

## 3. Candidate A Production State

**`IN_MASTER`** —— 入 master 于 `019b18a perf: promote Candidate A runtime reuse`。

| 文件 | SHA256 |
|---|---|
| `backend/app/agent/graph.py` | `9d09cbae3de49521cef242e106e967b8065aa368c9a6dcc0183b16503d14a25b` |
| `backend/app/schema/metadata.py` | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` |
| `backend/app/llm/mimo.py` | `2eddd623bf8db37a91cf9462783eba6f462944c08363c977540999750e2be403` |
| `backend/app/sqlgen/safety.py` | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` |
| `backend/app/sqlgen/validator.py` | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` |

| 测试 | SHA256 |
|---|---|
| `backend/tests/test_task29_runtime_reuse.py` | `5d6282299832c69e7b75a5a5a768ba1307661a529940cfc24cd0cb0bf4d52383` |
| `backend/tests/conftest.py` | `3aec65b806a228b5d611f93080f23d776398c4c7c7adf8d28cdfde483c376599` |

**四处优化**（消除每请求重复构造，不改可观察语义）：

1. `graph.py` — `get_default_graph()` 进程级图缓存
2. `metadata.py` — `SchemaCatalog.get_cached()` / `clear_cache()`（每请求 12 条 SQLite 连接 → 0）
3. `mimo.py` — `MimoProvider._get_client()` 实例内复用（`max_retries=0`）
4. `safety.py` — `check_sql_safety_with_tables()` 单次 sqlglot 解析；`validator.py` 改用之

`observable_semantics_changed: false`

## 4. Experimental Component Isolation

**Production**

```text
SchemaLinker          （LINKER_MODE=llm，经 create_schema_linker()）
Candidate A           （运行时复用优化）
```

**Not Production**

```text
Rule Linker           BLOCKED        Task 30/31：Sufficiency 88.9% < 98%
Coverage Guard        BLOCKED        Task 32：召回 1/4（真实 0/4），上界锁死 87.5%
Hybrid Linker         BLOCKED        Task 32：上界由召回决定，不由精度决定
Schema Retrieval      INCONCLUSIVE   Task 34：无配置满足「高召回 + 明显更小候选集」
```

`experimental_wired_to_production: false` —— 四者**均未接入生产链路**。

## 5. Test Baseline

```bash
python -m pytest backend/tests
```

```text
399 passed
0 failed
0 errors
0 skipped
1 warning      （starlette BlockingPortal 弃用告警，非本项目代码）

执行时间:  27.62s（pytest 报告值） / 32s（墙钟）
解释器:    .venv/Scripts/python.exe   Python 3.12.10   pytest 9.1.1
结果:      PASS
```

## 6. Safety Baseline

```text
Safety: PASS
```

- 含于 399 passed 内（`backend/tests/test_sql_executor.py` + `app/sqlgen/safety.py` 单测）
- Candidate A 安全回归：**29 样本 0 差异**（Task 35 复测结论）

## 7. Frozen Asset Hashes

| 资产 | 路径 | SHA256 | 冻结记录 | 结论 |
|---|---|---|---|---|
| Prompt V1.3 | `data/prompts/sql_generator_v1.3.txt` | `2af938be9866a62a97fdc3f1b0c7dc43b0785a7ff75ad420109b1d18ed39dc4c` | `10583478` | **MATCH** |
| FEWSHOT_V3 | `data/fewshot/ecommerce_examples.json` | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` | `ee12fcc9` | **MATCH** |
| Dataset | `data/eval/ecommerce_eval_v1.json` | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` | `dba277cc` | **MATCH** |
| DB | `db/ecommerce.db` | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9` | — | 2,912,256 B |
| Clean Baseline eval | `reports/eval/clean_baseline_v1_1/eval_clean_baseline_v1_1.json` | `39404fedef84b338cc7b48ed2972db98c7c574cd8cfca196ca02f7843e42f66e` | `39404fed` | **MATCH**（418,828 B） |
| `sqlglot` | — | `30.18.0` | `30.18.0` | **MATCH** |

**Overall: `MATCH`** —— 五项冻结资产全部逐字节吻合，无一漂移。

## 8. Performance Measurement Scope

```text
Local deterministic:
  BEFORE     29.074 ms
  AFTER       1.955 ms
  DELTA      -93.3%

Historical provider-backed:
  ~836 ms/call   client reuse evidence

Current real E2E:
  NOT_MEASURED

Reason:
  Mimo HTTP 402 Insufficient account balance
```

**禁止表述**：

```text
❌ E2E latency improved 93.3%
```

三层证据纪律：**本地确定性** / **历史 provider 支撑** / **当前 E2E** —— 不得混用，不得由此及彼。

## 9. Recovery Anchor

| 项目 | 值 |
|---|---|
| Ref | `recovery_master_20260920` |
| Commit | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| Subject | `recovery: reconstruct master baseline 2026-09-20` |
| 存在 | **YES** |
| 删除 | **NO** |

构建方式：`git write-tree` + `git commit-tree`（**0 parent，不猜祖先**）。

## 10. Backup Location

```text
C:\Users\29593\Desktop\Text2SQL_Agent_ReleaseBackup_20260920\
```

**物理备份**（`.git` + 完整工作树，**非 git export**）—— 用于避免下一次 ref / worktree 故障。

| 检查 | 源 | 备份 | 结论 |
|---|---|---|---|
| `.git` 字节 | 53,223,332 | 53,223,332 | **逐字节相同** |
| 工作树文件数 | 12,337 | 12,337 | **相同** |
| HEAD | `35a9ad6…` | `35a9ad6…` | **一致** |
| master | `35a9ad6…` | `35a9ad6…` | **一致** |
| tag | `release_baseline_20260920` | 同 | **一致** |
| tag ref 文件 | 存在 | 存在 | **一致** |
| `git fsck --connectivity-only` | — | 仅既有 dangling 对象，无损坏 | **通过** |

总计 **404,054,901 B（≈416 M）**。

> **首次尝试 FAILED 与修复**：第二条 `cp -r "$SRC/."` 的目标已含 `.git`，造成自我覆盖与约 57 个 `Permission denied`。
> 已清空目标目录重做 —— **`.git` 独占复制在前**，再 `find -mindepth 1 -maxdepth 1 ! -name .git` 复制其余。第二次 `cp` rc=0 / rc=0，**stderr 零报错**。

## 11. Known Limitations

| ID | 级别 | 限制 |
|---|---|---|
| **L1** | **HIGH** | **真实 E2E 延迟未测量** —— provider HTTP 402（余额不足）。不得对本基线作任何端到端延迟声明。 |
| L2 | MEDIUM | `mimo.py` 把 402 误映射为 `LLMServiceUnavailableError`。**按指令未修**（Phase 2F 禁止触碰 402）。 |
| L3 | MEDIUM | 原 master 对象 `d668e6a6` **永久不可恢复**（`ORIGINAL_MASTER_COMMIT_UNRECOVERABLE`）。当前基线 = 重建 commit `518cd896` 向前演进至 `35a9ad6`；其上**无祖先被伪造**，也**不可恢复**。 |
| L4 | MEDIUM | Schema Linking 实验线全部 `BLOCKED` / `INCONCLUSIVE`，未接生产。Task 31 实测 **泛化差距 11.1pp** 仍是头号方法论结论。 |
| L5 | LOW | `core.autocrlf=true` 会产生幽灵 modified 条目（零内容差异）。当前 tracked clean。 |
| L6 | LOW | Git `2.55.0.windows.3` 在 F: 盘**无法创建含 `/` 的 ref**（静默失败：`update-ref` rc=0 但无文件）。**永久约束**，本 release 全部 ref 无斜杠。 |
| L7 | LOW | 4 个 untracked 文件**有意保留**，未删未 add。 |

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

**Gate 状态：`OPEN_FOR_TASK_36`** —— **仅登记状态，未执行 Task 36**。

---

## Working Tree（§9 记录）

```text
tracked clean:
  YES   （git status --short 无 tracked 条目；tracked_modified_count = 0）

untracked:
  .workbuddy-ai/memory/2026-09-20.md
  .workbuddy-ai/memory/MEMORY.md
  reports/CANDIDATE_A_PROMOTION_REVIEW.json
  reports/CANDIDATE_A_PROMOTION_REVIEW.md
```

**未删除任何 untracked recovery / memory 文件。**

---

**Phase 2F COMPLETE — `RELEASE_BASELINE_FROZEN`**
