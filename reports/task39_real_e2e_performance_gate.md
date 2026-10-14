# Task 39 — Real E2E Performance Gate

> **STATUS: PERFORMANCE_GATE_CLOSED — Provider UNAVAILABLE（HTTP 402 余额不足）**
> 单臂、master @ 35a9ad6、真实 Mimo。100 题**未执行**（按任务书 §五 于 smoke test 阶段停止）。
> 所有性能指标 = **NOT_MEASURED**。工作树已恢复到测试前状态。

---

## 1. Objective

测量当前正式发布基线 `master @ 35a9ad6` 的真实端到端性能，判定 8 秒门禁（`mean_e2e_ms <= 8000`）。

单臂设计：只测 `CURRENT MASTER`。不比较 E8，不重跑 Task 38，不做因果归因。

---

## 2. Master Baseline

| 项 | 值 |
|---|---|
| HEAD | `35a9ad61a9616619c1324fda68de69b6ae19996c` |
| master | `35a9ad61a9616619c1324fda68de69b6ae19996c` |
| **HEAD == master** | **True** |
| commit subject | `docs: finalize Phase 2E report tip` |
| release tag | `release_baseline_20260920` → 35a9ad6 |
| 测试前 tracked modification | 8（Task 36/37/38 未提交改动） |

### 2.1 测试树准备（可逆恢复，未使用 clean / reset --hard）

任务书 §一 要求先把工作树恢复到 master，且恢复方式必须可逆。

```text
备份位置: %TEMP%\task39_worktree_patch_backup\
  patch.diff                 完整 git diff
  status_before.txt          测试前 git status --short
  head_before.txt            测试前 HEAD
  hashes_before.txt          13 个文件 sha256
  files/                     8 个 modified 文件的字节副本（保留相对路径）
  untracked_modules/         2 个未跟踪运行时模块副本
  untracked_tests/           3 个未跟踪测试文件副本
```

**备份完整性：`VERIFIED`**（13 个文件副本 vs 原件逐字节 sha256 全 MATCH）。

恢复动作：`git restore --source=HEAD -- <8 files>`（**路径限定**，非分支切换）。
**未使用** `git clean` / `git reset --hard` / `git checkout <branch>` / `git stash`。

### 2.2 恢复后验证

```text
git diff HEAD --stat          → 空（与 HEAD 无内容差异）
8 个文件 vs HEAD blob         → content=True（全部）
git status --short            → 2 个文件显示 M（mimo.py / runner.py）
```

那 2 个 `M` 是 `core.autocrlf=true` 的**行尾幽灵**（`bytes=False` 但 `content=True`），
零内容差异 —— 本项目已多次记录的既有现象，不影响运行时行为。

### 2.3 Task 36 / 37 / 38 缺席确认（测试树）

| 检查项 | 文件 | 命中 |
|---|---|---|
| Task 36 `LLMInsufficientBalanceError` | `backend/app/llm/provider.py` | 0 → **ABSENT** |
| Task 36 `402` 处理 | `backend/app/llm/mimo.py` | 0 → **ABSENT** |
| Task 36 `PROVIDER_ERROR_NAMES` | `evaluation/runner.py` | 0 → **ABSENT** |
| Task 37 `check_sql_scope` | `backend/app/sqlexec/executor.py` | 0 → **ABSENT** |
| Task 37 `check_sql_scope` | `backend/app/sqlrepair/validator.py` | 0 → **ABSENT** |
| Task 37 `SQLExecutionScopeError` | `backend/app/sqlexec/errors.py` | 0 → **ABSENT** |
| Task 38 `entity_constraint` | `backend/app/sqlgen/prompt.py` | 0 → **ABSENT** |

**`TASK 36/37/38 ALL ABSENT FROM TESTED TREE: True`**

---

## 3. Runtime Configuration

**未修改任何配置。** 全部为 master 默认值。

| 配置项 | 值 | 说明 |
|---|---|---|
| 解释器 | `.venv/Scripts/python.exe` | Python 3.12.10 —— **与冻结基线同一解释器** |
| `model` | `mimo-v2.5-pro` | 冻结基线一致 |
| `provider` | `mimo` | 冻结基线一致 |
| `base_url` | `https://api.xiaomimimo.com/v1` | 冻结基线一致 |
| `SQLGEN_EXTRA_RULES` | (unset) | **E8 = OFF** ✔ |
| `LINKER_MODE` | (unset) | 回退 `llm` ✔ |
| `temperature` | 0.0 | harness 固定 |
| `per_item_timeout_s` | 60.0 | 与基线一致 |
| `sdk_max_retries` | 0 | 与 `MimoProvider._get_client()` 一致 |
| `api_key` | `.env` 经 `load_dotenv` 注入 | **绝不记录到输出** |

---

## 4. Benchmark Dataset

| 项 | 值 |
|---|---|
| 数据集 | `data/eval/ecommerce_eval_v1.json`（ECO-SQL-Bench v1.1） |
| 题数 | 100 |
| sha256 | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` |
| 与冻结记录比对 | **MATCH** |
| 题目/Gold 修改 | **无** |
| 困难题排除 | **无** |
| 手工重跑覆盖 | **无** |

---

## 5. Provider Availability — **UNAVAILABLE**

### 5.1 Smoke test（任务书 §五，3 题）

```text
$ .venv/Scripts/python.exe scripts/task36_e2e_benchmark.py --limit 3

model          : mimo-v2.5-pro  (configured: mimo-v2.5-pro)
timeout        : 60.0s    temperature: 0.0
max_retries    : 0 (SDK layer)
provider       : mimo
endpoint       : https://api.xiaomimimo.com
api key        : SET (not recorded)

[1/3] E-0001   total=  5900.02ms  provider=  5846.78ms  nonllm=  53.23ms  ok=False  exc=LLMServiceUnavailableError  upstream_http=-
[2/3] E-0002   total=   637.60ms  provider=   629.52ms  nonllm=   8.09ms  ok=False  exc=LLMServiceUnavailableError  upstream_http=-
[3/3] E-0003   total=   547.46ms  provider=   539.62ms  nonllm=   7.83ms  ok=False  exc=LLMServiceUnavailableError  upstream_http=-

mode           : PARTIAL
success        : 0/3
provider calls : 3
```

**0/3 成功。** 命中任务书 §五 的停止条件（provider 故障）⇒ **停止，不进入 100 题**。

### 5.2 上游真实状态码（直接探测，只读，未改任何代码）

```text
endpoint : https://api.xiaomimimo.com/v1
api key  : SET (len=51)

RESULT   : EXCEPTION
  class      : APIStatusError
  status_code: 402
  body       : {"code": "402", "message": "Insufficient account balance",
                "type": "insufficient_balance"}
```

**Provider 不可用的根因：上游 HTTP 402 — 账户余额不足。**

### 5.3 任务书 §九：记录 master 的**实际**行为（不修代码）

master 的 `backend/app/llm/mimo.py` 错误映射：

```python
status_code = exc.status_code
if status_code in (401, 403):
    return LLMAuthenticationError("Mimo authentication failed")
if status_code == 429:
    return LLMRateLimitError("Mimo rate limited")
if status_code >= 500:
    return LLMServiceUnavailableError("Mimo service unavailable")
return LLMServiceUnavailableError("Mimo request failed")   # ← 402 落在这里
```

实测 `final_error == "Mimo request failed"` —— **正是最后一个分支**。
若上游为 5xx，文案会是 `"Mimo service unavailable"`。

```text
402 classification on master:
  upstream_http_status   = 402
  master 映射为          = LLMServiceUnavailableError("Mimo request failed")
  exception_class        = LLMServiceUnavailableError
  http_status (异常属性) = None（master 未向异常附加该属性）
  → 402 被掩盖为「服务不可用」
```

**这正是 Task 36 要修的缺陷，而 Task 36 不在 master 中 —— 与任务书 §三 的预判完全一致。**

```text
Task 36 status:
  NOT_IN_CURRENT_MASTER

Task 39 402 regression:
  NOT_APPLICABLE（本次为性能 benchmark，不是 Task 36 regression）
```

**未修改任何代码来适配 Task 36。**

---

## 6. Execution Accuracy

**NOT_MEASURED** —— 100 题未执行（provider 402）。

| 指标 | 值 |
|---|---|
| EX | **NOT_MEASURED** |
| Exec | **NOT_MEASURED** |
| SQL Execution Accuracy | **NOT_MEASURED** |

---

## 7. E2E Latency

**NOT_MEASURED。**

| 指标 | 值 |
|---|---|
| Mean E2E | **NOT_MEASURED** |
| P50 / P95 / Min / Max | **NOT_MEASURED** |
| Mean provider latency | **NOT_MEASURED** |
| Mean non-LLM latency | **NOT_MEASURED** |
| Provider failures | **NOT_MEASURED** |
| Repair count | **NOT_MEASURED** |

> Smoke test 的 3 个样本**不构成性能测量**：全部为失败运行（`provider_latency_ms` 统计
> 在成功子集上为 `n=0`），且 n=3 远低于任何有意义的样本量。**不从中得出任何性能结论。**

---

## 8. Provider Latency

**NOT_MEASURED**（同上，成功子集为空）。

---

## 9. Failure Analysis

失败样本共 3 个（smoke test 全部）。逐项记录：

| eval_id | stage | exception_class | upstream_http_status | provider_latency_ms | total_e2e_latency_ms | sql_success | repair_triggered |
|---|---|---|---|---|---|---|---|
| E-0001 | provider | `LLMServiceUnavailableError` | 402（被掩盖） | 5846.78 | 5900.02 | False | False |
| E-0002 | provider | `LLMServiceUnavailableError` | 402（被掩盖） | 629.52 | 637.60 | False | False |
| E-0003 | provider | `LLMServiceUnavailableError` | 402（被掩盖） | 539.62 | 547.46 | False | False |

### 分类

| 类别 | 数量 |
|---|---|
| **provider**（上游 402 余额不足） | **3** |
| authentication | 0 |
| balance | 3（归入 provider，见下） |
| rate limit | 0 |
| timeout | 0 |
| network | 0 |
| LLM generation | 0 |
| schema linking | 0 |
| SQL generation | 0 |
| SQL safety | 0 |
| SQL execution | 0 |
| repair | 0 |

> 分类说明：`balance` 在 master 上**无法与 provider 区分**——402 被映射为
> `LLMServiceUnavailableError`，异常上不带 `http_status` 属性，harness 的
> `upstream_http_status` 读到 `None`。本次通过**独立的直接 HTTP 探测**才确认其为 402。
> 这本身就是 Task 36 修复价值的直接证据。

**失败全部发生在 provider 阶段，未触及 schema linking / SQL generation / safety / execution / repair。**

---

## 10. Frozen Baseline Comparison

**未做比较** —— 本次无测量结果。仅列历史背景（任务书 §八 要求，Observed comparison）：

| 指标 | 冻结基线（run `20260916_09876`, mode=full） | 本次 Task 39 |
|---|---|---|
| EX | 90.0% | **NOT_MEASURED** |
| Exec | 99.0% | **NOT_MEASURED** |
| Avg E2E | 10876.08 ms | **NOT_MEASURED** |
| P50 | 10488.92 ms | **NOT_MEASURED** |
| P95 | 15440.79 ms | **NOT_MEASURED** |
| Repair Trigger Rate | 1.0% | **NOT_MEASURED** |
| Provider Failures | 0 | **NOT_MEASURED** |
| Valid Model Runs | 100 | **NOT_MEASURED** |

**未声称任何因果结论。** 不写「Candidate A caused X% improvement」。

---

## 11. Eight-Second Target

```text
8-Second Target:
  NOT_MEASURED
```

**理由**：无 100 题正式测量。**未使用** P50 / P95 / 成功题平均值 / 本地 micro-benchmark 替代。

---

## 12. Candidate A Interpretation

**不做归因。**

```text
Candidate A:  ACTIVE（IN_MASTER）
```

Candidate A 在 master 中，但本次**未获得任何可归因的性能数据**，
因此**不给出任何关于 Candidate A 性能影响的陈述**。

---

## 13. Reproducibility

| 项 | 值 |
|---|---|
| 测试树 | `master @ 35a9ad61a9616619c1324fda68de69b6ae19996c`（内容级干净） |
| 解释器 | `.venv/Scripts/python.exe`（3.12.10） |
| harness | `scripts/task36_e2e_benchmark.py`（未跟踪文件，restore 不影响） |
| 命令（smoke） | `.venv/Scripts/python.exe scripts/task36_e2e_benchmark.py --limit 3` |
| 命令（100 题） | **未执行** |
| 输出 | `reports/eval/task39/smoke3.json` |
| 随机性 | temperature=0.0；provider 端未暴露可控随机性 |
| 冻结数据集 | `data/eval/ecommerce_eval_v1.json`（sha256 `dba277cc…`） |

---

## 14. Frozen Asset Verification

| 资产 | 路径 | sha256 前缀 | 大小 | 结果 |
|---|---|---|---|---|
| Prompt V1.3 | `data/prompts/sql_generator_v1.3.txt` | `2af938be…` | 3,372 B | ✅ MATCH |
| FEWSHOT_V3 | `data/fewshot/ecommerce_examples.json` | `ee12fcc9…` | 13,556 B | ✅ MATCH |
| ECO-SQL-Bench | `data/eval/ecommerce_eval_v1.json` | `dba277cc…` | 101,778 B | ✅ MATCH |
| DB | `db/ecommerce.db` | `65e5d8b2…` | 2,912,256 B | ✅ MATCH |
| Clean Baseline | `reports/eval/clean_baseline_v1_1/…json` | `39404fed…` | 418,828 B | ✅ MATCH |

```text
Frozen Assets:  MATCH (5/5)
```

**未重新 hash 后修改任何冻结文件。**

---

## 15. Final Decision

### 15.1 任务书 15 节覆盖

| 章节 | 状态 |
|---|---|
| 1. Objective | ✅ |
| 2. Master Baseline | ✅ |
| 3. Runtime Configuration | ✅ |
| 4. Benchmark Dataset | ✅ |
| 5. Provider Availability | ✅ **UNAVAILABLE（402）** |
| 6. Execution Accuracy | ⛔ NOT_MEASURED |
| 7. E2E Latency | ⛔ NOT_MEASURED |
| 8. Provider Latency | ⛔ NOT_MEASURED |
| 9. Failure Analysis | ✅（3/3 provider 失败，已分类） |
| 10. Frozen Baseline Comparison | ⚠️ 仅背景，未比较 |
| 11. Eight-Second Target | ⛔ NOT_MEASURED |
| 12. Candidate A Interpretation | ✅ 不做归因 |
| 13. Reproducibility | ✅ |
| 14. Frozen Asset Verification | ✅ 5/5 MATCH |
| 15. Final Decision | ✅ |

### 15.2 测试运行与恢复检查

| 项 | 结果 |
|---|---|
| pytest（干净 master 树） | **399 passed / 0 failed**，26.02s |
| pytest 解释器 | `.venv/Scripts/python.exe` |
| 3 个未跟踪测试文件 | 用 `--ignore` 排除（非 master 内容） |
| HEAD 变化 | **无**（35a9ad6 → 35a9ad6） |
| master 变化 | **无** |
| 新增 commit | **无**（`git log` 顶部仍为 35a9ad6） |
| 8 个 tracked modification | **全部恢复**，sha256 逐个 MATCH |
| `status_before` vs `status_after` | tracked 行 **IDENTICAL** |
| 唯一新增 | `?? reports/eval/task39/`（Task 39 输出，独立保存） |
| **Working Tree** | **RESTORED_TO_PRETEST_STATE** |

#### ⚠️ 用例数口径更正：实测 399，非 367

任务书 §十一 预期 `367 passed`。**实测为 399 passed。**

差额 **32** 已定位：`backend/tests/test_task29_runtime_reuse.py` 恰有 **32 个用例**，
且该文件**在 master 中**（Candidate A 已入 master）。

```text
399 − 32 = 367   ← 你的预期是 Candidate A 入 master 之前的用例数
```

`reports/RELEASE_BASELINE_MANIFEST.json`（Phase 2F 冻结）同样记录 `passed: 399`，与本次实测一致。
**master @ 35a9ad6 的正确基线是 399，不是 367。**

### 15.3 API Key 泄露扫描

| 文件 | 结果 |
|---|---|
| `reports/task39_real_e2e_performance_gate.md` | clean |
| `reports/task39_real_e2e_performance_gate.json` | clean |
| `reports/eval/task39/smoke3.json` | clean |

以 `.env` 中真实 key（长度 51）做逐字比对：

```text
API Key Leakage:  NONE
```

### 15.4 最终输出

```text
Task 39 COMPLETE

Measured Tree:
  master @ 35a9ad6

Task 36:
  NOT_IN_MASTER

Task 37:
  NOT_IN_MASTER

Task 38:
  NOT_IN_MASTER

E8:
  OFF

Benchmark:
  100 questions — NOT RUN（于 smoke test 阶段按 §五 停止）

Provider:
  UNAVAILABLE（HTTP 402 Insufficient account balance）

EX:
  NOT_MEASURED

Exec:
  NOT_MEASURED

Mean E2E:
  NOT_MEASURED

P50:
  NOT_MEASURED

P95:
  NOT_MEASURED

8-Second Target:
  NOT_MEASURED

Candidate A:
  ACTIVE

Frozen Assets:
  MATCH

Tests:
  399 passed

Working Tree:
  RESTORED_TO_PRETEST_STATE

Master:
  UNCHANGED

Status:
  PERFORMANCE_GATE_CLOSED

STOP
```

---

## 附：本任务未执行的动作（确保无污染）

- ❌ 未执行 100 题 benchmark（§五 门禁）
- ❌ 未产生任何性能数字
- ❌ 未修改任何代码、配置、冻结资产
- ❌ 未执行 `git add` / `commit` / `stash` / `checkout <branch>` / `clean` / `reset --hard`
- ❌ 未用重试掩盖失败
- ❌ 未手工重跑失败题
- ✅ 唯一写入：`reports/task39_real_e2e_performance_gate.{md,json}`、`reports/eval/task39/smoke3.json`、
  以及 TEMP 下的备份目录（仓库外）

## 附：后续建议（仅记录，不执行）

任务书 §四 要求仅记录不执行：

```text
Task 36 → 独立 promotion
Task 37 → 独立确认
Task 38 → 独立确认
```

它们进入 master 后，再重新建立新的正式 benchmark baseline。
**不要把多个任务混成一个 benchmark。**

另：本次再次验证了 **402 误映射**在 master 上真实存在且可观测——
`LLMServiceUnavailableError("Mimo request failed")` 完全掩盖上游 402，
导致无法区分「服务故障」与「余额不足」。这是 Task 36 promotion 的额外论据。
