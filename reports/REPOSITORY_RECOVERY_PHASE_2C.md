# Repository Recovery Phase 2C — Git Restoration + Candidate A Promotion

> Date: 2026-09-20
> Scope: restore a working `master`, then build a promotion branch containing **only** Candidate A.
> **Candidate A is NOT merged back into master.**

---

## 1. Original Git Failure

**What happened.** During the Task 29 promotion attempt, the command

```
git switch -c feature/candidate-a-promotion master
```

produced a **silent partial failure**:

- The **ref creation step failed silently** — git reported success, but no ref file was written.
- The **checkout step executed** — the worktree was overwritten with `master`'s tree.

**Result:** all uncommitted Task 29–35 artifacts in the worktree were destroyed, and no branch/commit existed to recover them from.

**Root cause (confirmed).** `git --version` → **`git 2.55.0.windows.3`**. On the `F:` drive this git build **cannot create refs containing `/`** — `git update-ref refs/heads/feature/x <sha>` returns `rc=0` but writes no file. Because `git switch -c` treats a `rc=0` ref write as success, it proceeded to the checkout, which then clobbered the worktree.

**Damage.** The original `master` ref pointed at `d668e6a6395394848fd7f96c6f292045e55febac`. After the incident, `.git/refs/heads/master` **still contained that SHA as text**, but the **commit object itself was gone from the object database**, and `HEAD` was dangling (`ref: refs/heads/feature/candidate-a-promotion`, a ref that never existed). Reflog was empty; there was no `packed-refs` and no `ORIG_HEAD`.

**Standing prohibition derived from this.** No new ref name may contain `/`. Allowed names for this recovery: `recovery_master_20260920`, `candidateA_promotion_20260920`.

---

## 2. Original master SHA

```
d668e6a6395394848fd7f96c6f292045e55febac
```

Recording that `.git/refs/heads/master` held this exact text after the incident is what made §七's atomic compare-and-swap possible.

---

## 3. Original master Recoverability

**Verdict: `ORIGINAL_MASTER_COMMIT_UNRECOVERABLE`.**

A read-only, global, bounded search was performed across every plausible location. The commit object is **nowhere on disk**:

| Location searched | Method | Result |
|---|---|---|
| `git cat-file -t d668e6a6` | direct probe | `rc=128` (object not found) |
| Loose object store `.git/objects/` | path probe | absent |
| The single pack (`.git/objects/pack/*.idx`) | `git verify-pack -v` | absent |
| Multi-pack-index | `git multi-pack-index verify` / entry scan (809 entries) | absent |
| Full ODB enumeration | `git cat-file --batch-all-objects --batch-check` | only commits `29b6f2e4`, `80a09b5a`, `d2584919`, `f9e1f3fd` exist |
| Linked worktrees (`workbuddy/master-*`) | `git ls-files --others` + ref resolution | all resolve to `80a09b5a`, not `d668e6a6` |
| Incident temp snapshot | object-store comparison | **identical** object store (no extra objects) |
| `~/.workbuddy-ai` (file-history, sessions, transcripts) | scoped grep | only **string references** in audit logs / logs — never the object bytes |
| `git fsck` | integrity scan | `error: refs/heads/master: invalid sha1 pointer d668e6a6…` + missing blobs `a314a06c…`, `4db91c65…`, `ab1c844d…` |

The search was **deliberately bounded** — not run to infinity — per instruction. Once the object database was exhaustively enumerated and the hash appearable only as a text string in logs, further searching could not produce a result.

**Consequence:** the recovery commit is built **without fabricating ancestry** (0 parents). See §六.

---

## 4. Recovery Commit

### 4.1 Step 1 — §四 stage the two master lost files

Two files required by the recovered baseline were restored from the Phase 2B-2 `EXACT_ORIGINAL` reconstruction and staged:

| File | Size | SHA256 | Git blob | `== .git/index` sha1 |
|---|---|---|---|---|
| `reports/WORKBUDDY_HANDOVER_REPORT.md` | 43,804 B | `4e19cc1e706fa6a2…` | `a314a06c6e3fa21706b155439fa4ad763321c61b` | **YES** |
| `reports/task28_final_delivery.md` | 35,390 B | `f0293d8fae97af06…` | `4db91c65776aad550cb36a0794dbf8855c1d92de` | **YES** |

Both were required to satisfy `SHA256 == Phase 2B-2 verified hash`, and both matched exactly (blob equality with the index entry is an fsck-independent byte-exactness proof).

### 4.2 Step 2 — §六 build the tree

`git write-tree` initially failed:

```
error: invalid object 100644 ab1c844dc4fef5d6563a7c237d1eb284be0bb6b8 for '.workbuddy-ai/memory/2026-09-17.md'
fatal: git-write-tree: error building trees
```

Diagnosis: exactly **one** index-referenced blob was missing from the ODB. The worktree file content hashed to that same value (so content was intact — the object had simply never been written). Note that `git add` on this file **appeared to succeed but wrote nothing**, because the **stat-cache skip** logic saw the index blob hash already matched the working-tree hash and concluded there was nothing to write.

Fix: force the object into the ODB with

```
git hash-object -w "F:\...\.workbuddy-ai\memory\2026-09-17.md"
```

(Note: `git hash-object` requires **native Windows paths**; Git Bash `/c/...` paths fail.) Then:

```
recovery_tree = c43821c46fc2351c27090f2868bd1933d4580765   (802 entries)
```

### 4.3 Step 3 — §六 commit with **no parent**

```
git commit-tree c43821c46fc2351c27090f2868bd1933d4580765 -m "<message>"
```

Message body explicitly states:

> Recovered from validated Phase 1 master index/worktree. Original master commit d668e6a... was unrecoverable. No Candidate A or Task 29-35 production changes included.

**Result:**

```
recovery_commit = 518cd8964fc438aa82151f60b415cb4d9ce17a37
parents = (none — 0 parents)
```

**No fabricated ancestry.** The original parent chain could not be known, so none was invented.

---

## 5. Recovered Master Verification

### 5.1 §五 baseline completeness

- `git diff --numstat` → **empty** (zero content difference).
- Working tree = recovered baseline. **Only** the two master lost files needed re-adding.
- **No Task 29–35 experimental files** anywhere in the tree.
- **No** Candidate A, Rule Linker, Coverage Guard, Hybrid Linker, Schema Retrieval, or Task 33/34 research artifacts.
- The five Candidate A target files were confirmed still at master baseline (0 hits for `_DEFAULT_GRAPH_CACHE` / `_CATALOG_CACHE` / `_get_client` / `_parse_single_readonly`).

### 5.2 §七 atomic master replacement

```
git update-ref refs/heads/recovery_master_20260920 518cd89…
git update-ref refs/heads/master 518cd89… d668e6a6395394848fd7f96c6f292045e55febac
```

The second command is a **compare-and-swap**: it succeeds only if master's current value is exactly `d668e6a6…`. It returned `rc=0`, so the replacement was atomic and no concurrent modification was possible. (`refs/heads/recovery_master_20260920` verified as a 41-byte ref file on disk.) `git log master` now resolves — the branch is functional again.

Had it failed, the instruction was to **stop immediately, not retry, not force-overwrite**. It did not fail.

### 5.3 §八 HEAD repair

```
git symbolic-ref HEAD refs/heads/master
```

`symbolic-ref` changes only the HEAD pointer and **does not touch the worktree** — the safe way to repair a dangling HEAD.

Verified: `git symbolic-ref --short HEAD` → `master`; `git rev-parse --verify HEAD` → `518cd89…`; `git rev-parse --verify refs/heads/master` → `518cd89…`.

### 5.4 §九 post-restoration state

`git status --short` initially showed **158 phantom `AM` entries**. Root cause: `core.autocrlf=true` — the index stores LF-normalized blobs while the worktree holds CRLF, so git flags "modified" entries that have **zero content difference**. Proven harmless with `git diff --ignore-cr-at-eol --numstat` → empty. Fixed with `git add --renormalize .`, after which the working tree became genuinely clean (only 2 untracked `.workbuddy-ai/memory/*` files). Re-verified that the HEAD tree equals the index tree (`c43821c4…`) — the renormalize therefore did not alter the commit.

Production red lines confirmed at this point: `LINKER_MODE` absent, `linker_factory.py` absent, `graph.py` importing and using only `SchemaLinker`.

---

## 6. Candidate A Included Files

**Six files** (5 production + 1 test). Full derivation and hashes: `reports/CANDIDATE_A_PROMOTION_MANIFEST.md` / `.json`.

| # | File | Role | SHA256 |
|---|---|---|---|
| 1 | `backend/app/agent/graph.py` | A1 graph cache | `9d09cbae3de49521…` |
| 2 | `backend/app/schema/metadata.py` | A2 catalog cache | `6aa9b571229d17ad…` |
| 3 | `backend/app/llm/mimo.py` | A3 client reuse | `2eddd623bf8db37a…` |
| 4 | `backend/app/sqlgen/safety.py` | A4 single parse | `c9cd072471381036…` |
| 5 | `backend/app/sqlgen/validator.py` | A4 consumer | `1c0e9a2c395adabc…` |
| 6 | `backend/tests/test_task29_runtime_reuse.py` | behavioral test | `5d6282299832c69e…` |

**Important — one contamination was found and fixed.** The set was **not** assumed from "five core files"; it was re-derived from `RECOVERY_MANIFEST_FINAL.json`, Task 29 evidence, the Task 35 report, and the recovered transcript/file-history. During the §十三 diff gate, content review of `graph.py` revealed a **Task 30 hunk** that was not part of Candidate A:

```diff
-from app.schema.linker import SchemaLinker
+from app.schema.linker_factory import create_schema_linker
```

Root cause: the Phase 2B-1 replay protocol applies transcript Edits onto the **master baseline**, but those Edits were originally authored on a **Task-30-era file**. An `old_string` matched a semantically adjacent — but different — location, carrying the Task 30 factory switch into Candidate A. **`old_string` match ≠ semantic match.**

Per the §十三 gate the flow **stopped before committing**. The single hunk was isolated, reverted to master-baseline form, and all six files were rescanned (only `graph.py` had been affected; the other five were `CLEAN`). After the fix: zero occurrences of `linker_factory` / `create_schema_linker` / `LINKER_MODE` / `rule_linker` / `coverage_guard` / `hybrid` / `structural_coverage` / `schema_retrieval` across all six files.

§十三 diff gate result:

```
git diff master..candidateA_promotion_20260920 --name-only
→ exactly the 6 files above. 6 files changed, 383 insertions(+), 13 deletions(-)
→ forbidden files present: NONE
```

---

## 7. Experimental Files Excluded

**12 files excluded** (6 components + 5 tests + 1 conftest):

| File | Reason |
|---|---|
| `backend/app/schema/rule_linker.py` | Task 30/31 — Holdout V2 FAIL, integration BLOCKED (88.9% < 98%) |
| `backend/app/schema/linker_factory.py` | Task 30/31 — introduces the `LINKER_MODE` production switch |
| `backend/app/schema/coverage_guard.py` | Task 32 — routing locks Sufficiency at 87.5% |
| `backend/app/schema/hybrid_linker.py` | Task 32 — depends on coverage_guard |
| `backend/app/agent/structural_coverage.py` | Task 33 — method-boundary BLOCKED |
| `backend/app/agent/schema_retrieval.py` | Task 34 — INCONCLUSIVE, generalization unproven |
| `backend/tests/test_b1_rule_linker.py` | depends on Task 30 component → `EXCLUDE` |
| `backend/tests/test_task32_coverage_guard.py` | depends on Task 32 component → `EXCLUDE` |
| `backend/tests/test_structural_coverage.py` | depends on Task 33 component → `EXCLUDE` |
| `backend/tests/test_task33b_r1_audit.py` | depends on Task 33 component → `EXCLUDE` |
| `backend/tests/test_task34_schema_retrieval.py` | depends on Task 34 component → `EXCLUDE` |
| `backend/tests/conftest.py` | recovered version's `_reset_process_caches` imports Task 32/33 components → would `ImportError` on every test |

**Rule applied:** any test depending on a Task 30/32+ component is excluded. Only "Candidate A only + no experimental dependency" qualifies.

**Disclosed risk for the `conftest.py` exclusion.** Without `_reset_process_caches`, process-level caches could in principle survive across test files. This was **not observed in practice** — the promotion branch runs **399 passed / 0 failed**. `_get_client()` is instance-level and `_parse_single_readonly()` is stateless, so neither has a cross-test pollution path. A follow-up (out of Phase 2C scope) should add a Candidate-A-only conftest variant calling only `clear_default_graph_cache()` and `SchemaCatalog.clear_cache()`.

---

## 8. Regression Tests

| Branch | Command | Passed | Failed | Warnings | Duration |
|---|---|---|---|---|---|
| `master` (recovered baseline) | `python -m pytest backend/tests` | **367** | 0 | 1 | 26.11 s |
| `candidateA_promotion_20260920` | `python -m pytest backend/tests` | **399** | 0 | 1 | 25.08 s |

**Difference: +32.**

**Explanation of the difference.** The +32 is exactly `backend/tests/test_task29_runtime_reuse.py` (16 `def test_` functions, of which 16 expand to 32 parameterized cases). No other test file changed.

**On the historical "655 passed".** The Task 35 report recorded 655 passed on the pre-incident working tree. That number is **not recoverable as a comparison baseline**, because it included Task 30–34 experimental tests that are **deliberately excluded** here (and whose components are absent from production). Therefore this report states two separate, honest numbers:

- **Recovered master test count: 367**
- **Candidate A promotion test count: 399**

They are not comparable to 655, and no attempt was made to force a match — adding experimental tests back would have imported Task 30–34 components into production, violating §十五.

---

## 9. Frozen Asset Verification

All four frozen assets hashed **before** and **after** applying Candidate A. All **MATCH**:

| Asset | File | BEFORE | AFTER | Match |
|---|---|---|---|---|
| Prompt V1.3 | `backend/app/sqlgen/prompt.py` | `31244e614fb36a69…` | `31244e614fb36a69…` | **YES** |
| Dataset / Benchmark | `data/eval/ecommerce_eval_v1.json` | `dba277cc0be7cc28…` | `dba277cc0be7cc28…` | **YES** |
| Few-shot | `data/fewshot/ecommerce_examples.json` | `ee12fcc994c6afec…` | `ee12fcc994c6afec…` | **YES** |
| Database | `db/ecommerce.db` | `65e5d8b2727cfa06…` | `65e5d8b2727cfa06…` | **YES** |

Candidate A touches only runtime reuse in the five source files; it does not touch the prompt, the dataset, the few-shot set, or the database.

---

## 10. Production Status

### 10.1 Final repository state

```
master                        518cd8964fc438aa82151f60b415cb4d9ce17a37   (recovered baseline)
candidateA_promotion_20260920 019b18a450c25887c1786ce2a76d55af57640ea8   (master + Candidate A only)
recovery_master_20260920      518cd8964fc438aa82151f60b415cb4d9ce17a37   (safety copy of master)
```

`candidateA_promotion_20260920`'s parent is `518cd8964fc438aa82151f60b415cb4d9ce17a37`, i.e. master. **Candidate A was NOT merged back into master.**

### 10.2 §十五 production red lines

| Check | Result |
|---|---|
| `LINKER_MODE` in production | **ABSENT** |
| `linker_factory.py` present | **NO** |
| default linker | `SchemaLinker` (`from app.schema.linker import SchemaLinker`) |
| `graph.default_components()` | `SchemaLinker(provider=provider)` — identical to master |
| `get_llm_provider()` | unchanged (`return MimoProvider()`) |
| `create_schema_linker()` | absent (not wired) |
| `rule_linker` wired | NO |
| `coverage_guard` wired | NO |
| `hybrid_linker` wired | NO |
| `schema_retrieval` wired | NO |

### 10.3 §十七 safety regression

11 cases compared between the baseline two-step path (`check_sql_safety` + `extract_referenced_tables`) and Candidate A's single-parse path (`check_sql_safety_with_tables`). **Exception class, message, and status identical in every case:**

| Case | Result (both paths) |
|---|---|
| valid SELECT | OK |
| valid WITH / CTE | OK |
| multi-statement `SELECT 1; SELECT 2` | `SQLUnsafeError: 只允许单条 SQL 语句` |
| PRAGMA | `SQLUnsafeError: 只允许 SELECT / WITH 查询` |
| INSERT / UPDATE / DELETE / DROP | `SQLUnsafeError: 只允许 SELECT / WITH 查询` |
| ATTACH | `SQLUnsafeError: 只允许 SELECT / WITH 查询` |
| empty SQL | `SQLUnsafeError: SQL 为空` |
| non-select (EXPLAIN) | `SQLUnsafeError: 只允许 SELECT / WITH 查询` |

`ALL_EQUIVALENT = True`.

Result limit and repair path were verified **untouched**: `backend/app/sqlexec/executor.py` and the repair files do **not** appear in `git diff master --name-only`; `MAX_RESULT_ROWS = 500` unchanged; read-only protection unchanged (`mode=ro` + `query_only=ON`); graph repair bound unchanged (`repair_count <= 1`, `execute_count <= 2`).

### 10.4 Performance claims (§十九)

**No new real E2E performance numbers were measured or claimed.** The Mimo provider is returning **HTTP 402 (insufficient account balance)**, so no provider-backed end-to-end run was possible. Only the following three categories are reported, kept strictly separate:

1. **Local deterministic evidence (measured, reproducible):** BEFORE `29.074 ms` → AFTER `1.955 ms` = **−93.3%** (Task 35 non-LLM harness).
2. **Historical provider-backed evidence (recorded, not re-measured):** client reuse saved ≈ **836 ms/call**.
3. **Current real E2E:** `NOT_MEASURED`.

⚠️ The HTTP 402 mis-mapping noted in earlier phases (`mimo.py` classifies 402 as `LLMServiceUnavailableError`) remains **unfixed** — fixing it is outside Phase 2C scope.

---

## 11. Remaining Recovery Gaps

| # | Gap | Status | Impact |
|---|---|---|---|
| 1 | Original `master` commit `d668e6a6…` | **PERMANENTLY LOST** | Cannot recover the original commit object or its true parent chain. Replacement uses 0 parents — an **honest discontinuity**, not fabricated history. |
| 2 | `reports/task34_retrieval_holdout_v1.json` | `METADATA_ONLY` | Bytes never found (generator replay hit only 16/24 hunks). Task 34's blind-test holdout cannot be run as originally specified. |
| 3 | `backend/tests/conftest.py` `_reset_process_caches` | **EXCLUDED** | Not applied (imports Task 32/33 components). Process-level cache isolation for tests is weaker than the original. Debugging only; no production impact. Follow-up needed if Candidate A is merged. |
| 4 | Task 30–34 experimental tests | **ABSENT FROM PRODUCTION (by design)** | Historical "655 passed" is unrecoverable as a comparison point. Recovered master = 367; promotion = 399. |
| 5 | Provider HTTP 402 | **UNFIXED** | No end-to-end performance measurement possible. `NOT_MEASURED` for current E2E. |
| 6 | `graph.py` hash deviation from the 2B-1 source hash (`744d5d96…` → `9d09cbae…`) | **INTENTIONAL** | Caused by removing the Task 30 contamination hunk (§6). Diff line-by-line reviewed; behavior verified by 399 passed + runtime probes. |
| 7 | Git build cannot create `/`-containing refs on `F:` | **WORKAROUND IN PLACE** | Slash-free branch names only. If a future workflow needs slashes, migrate the repo off `F:` or upgrade/repair the git install. |

---

`Status: READY_FOR_REVIEW`
