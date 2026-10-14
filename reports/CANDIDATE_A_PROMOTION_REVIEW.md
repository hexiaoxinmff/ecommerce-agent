# Candidate A Promotion Review

> Phase 2D — Final Candidate A Independent Review
> Date: 2026-09-20
> Mode: **READ-ONLY acceptance audit.** No merge, rebase, reset, cherry-pick, commit, push, or production/test/prompt/few-shot/benchmark/DB modification was performed.

---

## 1. Review Scope

This review performs a read-only final acceptance audit of the Candidate A promotion, confirming that the promotion branch contains **only** Candidate A and that `master` remains the untouched recovered baseline.

**Objects under review:**

| Object | SHA |
|---|---|
| `master` (recovered baseline) | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| Candidate A production commit | `019b18a450c25887c1786ce2a76d55af57640ea8` |
| Promotion documentation commit | `681415360f08b905cb607947ead5bc9a3767165d` |
| Candidate A branch | `candidateA_promotion_20260920` |

**Prohibitions honored:** no merge, no rebase, no reset, no cherry-pick, no commit, no push; no production-code change, no test change, no Prompt / Few-shot / Benchmark / DB change, no modification to `master`. All operations in this review are read-only inspections (`git rev-parse`, `git diff`, `git cat-file`, `git ls-tree`, `git show`, `git grep`) plus local deterministic test/verification runs. The two report files written at the end are the only filesystem writes, as required by §13.

---

## 2. Commit Ancestry

```
019b18a^ = 518cd8964fc438aa82151f60b415cb4d9ce17a37
master   = 518cd8964fc438aa82151f60b415cb4d9ce17a37
6814153^ = 019b18a450c25887c1786ce2a76d55af57640ea8
```

Required assertions:

| Assertion | Result |
|---|---|
| `019b18a^ == 518cd896…` | **PASS** |
| `6814153^ == 019b18a` | **PASS** |

The promotion commit's sole parent is the recovered master. The documentation commit's sole parent is the production commit. No fabricated or skipped ancestry exists between them.

**Recovery ancestry statement (required wording).**

```
Original master d668e6a:
  UNRECOVERABLE

Recovered master 518cd896:
  reconstructed baseline
  0 parent
  no fabricated ancestry
```

The recovered baseline commit `518cd896…` has **0 parents** — the original `master` commit `d668e6a6395394848fd7f96c6f292045e55febac` was permanently lost (its object is absent from loose objects, the pack, the multi-pack-index, all linked worktrees, the incident snapshot, and the full `.workbuddy-ai` tree, appearing only as a text string in audit logs). Because the true parent chain is unknowable, **none was invented**. This is an honest discontinuity, not restored history. This report deliberately does **not** say "original master restored"; the correct description is **recovered/reconstructed baseline commit**.

---

## 3. Production Diff

```
git diff --name-only master 019b18a
```

Result — **exactly 6 files** (5 Candidate A production files + 1 Candidate A test file):

| # | Path | Role | Blob (sha1) | Content SHA256 | Size |
|---|---|---|---|---|---|
| 1 | `backend/app/agent/graph.py` | A1 graph cache | `cbfff471bcc84acbdef0c72f38dc83b7f04d6d70` | `9d09cbae3de49521cef242e106e967b8065aa368c9a6dcc0183b16503d14a25b` | 4,889 |
| 2 | `backend/app/llm/mimo.py` | A3 client reuse | `3f79645d53f63cb136b2ce50139f5b2194abe754` | `2eddd623bf8db37a91cf9462783eba6f462944c08363c977540999750e2be403` | 5,779 |
| 3 | `backend/app/schema/metadata.py` | A2 catalog cache | `88f829e09e687d706b9193ec54ee3da58e50c249` | `6aa9b571229d17ad6d9f066c911886f35b046b48a39911280d3a1989293e2de8` | 6,219 |
| 4 | `backend/app/sqlgen/safety.py` | A4 single parse | `cf2f597903dcaf1908b5c3c39752ef1f3ec5281d` | `c9cd072471381036b9e32c675225dafa30a7992e096ee2fbbb0f42fa03bb85b1` | 3,575 |
| 5 | `backend/app/sqlgen/validator.py` | A4 consumer | `0c24047b98dcf0145ef7041841e8c5a16dc28ee7` | `1c0e9a2c395adabcf1528ced1f90f844e1e2b9d6f5f76a2138570ff05f384e59` | 4,545 |
| 6 | `backend/tests/test_task29_runtime_reuse.py` | Candidate A test | `dec8e72f64aa2064b13aa884667cdd1a1b2bffb7` | `5d6282299832c69e7b75a5a5a768ba1307661a529940cfc24cd0cb0bf4d52383` | 9,783 |

> SHA256 values above are computed from the **committed blob content** (`git cat-file -p <commit>:<path> | sha256sum`), i.e. they describe the commit object itself, not the working tree.

`git diff --stat master 019b18a`:

```
 backend/app/agent/graph.py                 |  30 +++-
 backend/app/llm/mimo.py                    |  21 ++-
 backend/app/schema/metadata.py             |  29 +++-
 backend/app/sqlgen/safety.py               |  39 ++++-
 backend/app/sqlgen/validator.py            |   7 +-
 backend/tests/test_task29_runtime_reuse.py | 270 +++++++++++++++++++++++++++++
 6 files changed, 383 insertions(+), 13 deletions(-)
```

**Verdict: exactly 5 production + 1 test. No seventh file. No unexpected path.**

---

## 4. Content-Level Contamination Check

### 4.1 `graph.py` — the critical file

Since Phase 2C identified and removed a Task 30 contamination in exactly this file, `graph.py` receives targeted scrutiny.

Content at `019b18a:backend/app/agent/graph.py`:

```
31: from app.schema.linker import SchemaLinker
40:     schema_linker = SchemaLinker(provider=provider)
```

| Required | Forbidden | Result |
|---|---|---|
| `SchemaLinker(provider=provider)` present | — | **PASS** |
| — | `create_schema_linker(...)` | **PASS (0 occurrences)** |
| — | `linker_factory` | **PASS (0 occurrences)** |

### 4.2 Full-diff scan

Scanned every **added** line (`git diff master 019b18a | grep "^+"`, excluding `+++` headers) and every **removed** line (excluding `---` headers):

| Pattern | Added lines | Removed lines |
|---|---|---|
| `linker_factory` | 0 | 0 |
| `create_schema_linker` | 0 | 0 |
| `Rule Linker` | 0 | 0 |
| `RuleSchemaLinker` | 0 | 0 |
| `rule_linker` | 0 | 0 |
| `Coverage Guard` | 0 | 0 |
| `coverage_guard` | 0 | 0 |
| `Hybrid` | 0 | 0 |
| `hybrid` | 0 | 0 |
| `Schema Retrieval` | 0 | 0 |
| `schema_retrieval` | 0 | 0 |
| `structural_coverage` | 0 | 0 |
| `Task 30` | 0 | — |
| `Task 32` | 0 | — |
| `Task 33` | 0 | — |
| `Task 34` | 0 | — |
| `LINKER_MODE` | 0 | 0 |

**All 17 patterns: zero hits on both sides.** Scanning removed lines as well as added lines guards against the symmetric failure mode ("delete the legitimate line, add the illegitimate one").

### 4.3 Positive check — the four optimizations are present

| Signature | Added-line occurrences |
|---|---|
| `_DEFAULT_GRAPH_CACHE` | 7 |
| `get_default_graph` | 12 |
| `clear_default_graph_cache` | 4 |
| `_CATALOG_CACHE` | 7 |
| `get_cached` | 11 |
| `clear_cache` | 5 |
| `_get_client` | 7 |
| `max_retries=0` | 1 |
| `_parse_single_readonly` | 3 |
| `check_sql_safety_with_tables` | 12 |

**Verdict: forbidden production contamination = 0. The diff contains the four intended optimizations and nothing else.**

---

## 5. Experimental Component Isolation

### 5.1 Source files absent from the promotion tree

Checked with `git cat-file -e 019b18a:<path>`:

| File | In tree `019b18a` | In tree `master` |
|---|---|---|
| `backend/app/schema/rule_linker.py` | **absent** | **absent** |
| `backend/app/schema/coverage_guard.py` | **absent** | **absent** |
| `backend/app/schema/hybrid_linker.py` | **absent** | **absent** |
| `backend/app/agent/schema_retrieval.py` | **absent** | **absent** |
| `backend/app/schema/linker_factory.py` | **absent** | — |
| `backend/app/agent/structural_coverage.py` | **absent** | — |

### 5.2 Whole-tree reference scan

Enumerated **all 123 `.py` files** in tree `019b18a` and grep'd each for the six experimental module names:

```
rule_linker         → 0 hits
coverage_guard      → 0 hits
hybrid_linker       → 0 hits
schema_retrieval    → 0 hits
structural_coverage → 0 hits
linker_factory      → 0 hits
```

### 5.3 Factory / graph / config wiring

| Wiring surface | Finding |
|---|---|
| `graph.py` import | `from app.schema.linker import SchemaLinker` — no factory import |
| `graph.default_components()` | `SchemaLinker(provider=provider)` — direct construction |
| `LINKER_MODE` config switch | **0 occurrences anywhere in `backend/`** |
| `create_schema_linker()` | not present, not called |
| `config.py` linker settings | no experimental linker settings |

**Verdict: `NOT REACHABLE FROM PRODUCTION`.** The components do not exist in the tree, are not referenced by any of the 123 Python files, and there is no configuration surface (no `LINKER_MODE`) that could select them. Production's linker construction path is `SchemaLinker(provider=provider)` — byte-identical to the recovered baseline.

---

## 6. Functional Tests

Command (run on branch `candidateA_promotion_20260920`):

```
python -m pytest backend/tests
```

Result:

```
399 passed, 1 warning in 25.50s
```

| Metric | Value |
|---|---|
| Passed | **399** |
| Failed | **0** |
| Warnings | 1 (`anyio.abc.BlockingPortal` deprecation from `starlette.testclient`) |
| Duration | 25.50 s |

For context only (not a business metric): the recovered master baseline runs **367 passed**. The delta of **+32** is arithmetic bookkeeping for the newly-included Candidate A test module (`test_task29_runtime_reuse.py` holds 16 test functions which parameterize into 32 cases). Per §6, **the 399−367 difference is explicitly NOT presented as a business or performance indicator** — it counts tests, not outcomes.

---

## 7. Safety Regression

Task 35's **11 safety samples** were replayed, comparing the baseline two-step path (`check_sql_safety` + `extract_referenced_tables`) against the Candidate A single-parse path (`check_sql_safety_with_tables`), on all four required dimensions: **exception class, message, status, repair behavior**.

| # | Case | Baseline (2-step) | Candidate A (1-parse) | class | message | status |
|---|---|---|---|---|---|---|
| 1 | `valid_select` | `OK: ['users']` | `OK: ['users']` | = | = | = |
| 2 | `valid_with_cte` | `OK: ['orders']` | `OK: ['orders']` | = | = | = |
| 3 | `multi_statement` | `SQLUnsafeError: 只允许单条 SQL 语句` | identical | = | = | = |
| 4 | `pragma` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |
| 5 | `write_insert` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |
| 6 | `write_update` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |
| 7 | `write_delete` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |
| 8 | `write_drop` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |
| 9 | `attach` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |
| 10 | `empty_sql` | `SQLUnsafeError: SQL 为空` | identical | = | = | = |
| 11 | `non_select` | `SQLUnsafeError: 只允许 SELECT / WITH 查询` | identical | = | = | = |

```
ALL_EQUIVALENT = True
```

Notably, the two valid cases also return **identical extracted table sets** (`['users']` and `['orders']`), meaning the single-parse path produces the same referenced-table result that the two-step path produced — not merely the same pass/fail.

**Repair behavior:** `repair path present in graph.py = True`; `repair bounded (repair_count) = True`. The repair branch and its ≤1 re-entry bound are intact and untouched by Candidate A (the repair/executor files do not appear in the production diff at all).

**Verdict: `PASS`.**

---

## 8. Runtime Smoke Tests

Executed locally with **no Mimo network calls** (the provider returns HTTP 402, and no probe performs a provider call).

| Probe | Result | Evidence |
|---|---|---|
| **A1** graph reuse | **PASS** | builder invoked exactly once across two `get_default_graph()` calls (`calls=1`); `clear_default_graph_cache()` forces a rebuild to a new object |
| **A2** schema resource reuse | **PASS** | `get_cached()` returns the *same instance* twice; table set complete (`users, categories, products, orders, order_items`); `clear_cache()` forces rebuild |
| **A3** Mimo client reuse | **PASS** | `_get_client` present; contains `max_retries=0`; `self._client` initialized lazily in `__init__` as instance-level state (verified not a class attribute, so instances cannot leak a client to each other) |
| **A4** safety / referenced-table reuse | **PASS** | `_parse_single_readonly` callable; JOIN returns `{'users','orders'}`; CTE name correctly excluded (`WITH t …` → `{'orders'}`) |

```
RUNTIME_SMOKE = PASS
```

The A3 probe is deliberately **structural only** — it inspects source and attribute placement rather than calling `_get_client()` for real, precisely to avoid constructing a client against the network.

---

## 9. Frozen Asset Verification

Working-tree hashes on the Candidate A branch:

| Asset | File | Hash | Match |
|---|---|---|---|
| Prompt V1.3 | `backend/app/sqlgen/prompt.py` | `31244e614fb36a693220a44d5a71610b0350aca26c61c8b98075afcd70d87fed` | **MATCH** |
| Dataset / Benchmark | `data/eval/ecommerce_eval_v1.json` | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` | **MATCH** |
| Few-shot | `data/fewshot/ecommerce_examples.json` | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` | **MATCH** |
| Database | `db/ecommerce.db` | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9` | **MATCH** |

Commit-level cross-check (blob content of `019b18a` vs `master`, per file): **identical for all three text assets** — `prompt.py` blob hash `a7803fa4…` in both, `ecommerce_eval_v1.json` `28159b29…` in both, `ecommerce_examples.json` `ee12fcc9…` in both. (Blob hashes differ from the working-tree SHA256 only because `core.autocrlf` normalizes CRLF→LF inside the object store; the working-tree values are the authoritative frozen hashes, and both trees agree with each other.)

**Verdict: all four frozen assets MATCH. Candidate A touches neither the prompt, the dataset, the few-shot set, nor the database.**

---

## 10. Master Integrity

```
master   = 518cd8964fc438aa82151f60b415cb4d9ce17a37
branch   = 681415360f08b905cb607947ead5bc9a3767165d
```

`master == 518cd896…` — **confirmed**.

`master` contains no Candidate A. Verified per-optimization against the `master` tree:

| Symbol | Present in `master`? | Result |
|---|---|---|
| `_DEFAULT_GRAPH_CACHE` (A1) | no | **PASS: master 无 A1** |
| `_CATALOG_CACHE` (A2) | no | **PASS: master 无 A2** |
| `_get_client` (A3) | no | **PASS: master 无 A3** |
| `_parse_single_readonly` (A4) | no | **PASS: master 无 A4** |

`git diff master 019b18a` is a forward-only diff: it shows Candidate A added on the promotion side, with `master` as the unchanged left-hand side. **`master` is UNCHANGED — the recovered baseline remains the production state.**

Note the branch pointer: `candidateA_promotion_20260920` has advanced to `6814153` (the documentation commit), which is expected — the *production* content is `019b18a`, and the documentation commit only adds report files on top of it.

---

## 11. Documentation Commit Separation

```
git diff --name-only 019b18a 6814153
```

Result:

```
reports/CANDIDATE_A_PROMOTION_MANIFEST.json
reports/CANDIDATE_A_PROMOTION_MANIFEST.md
reports/REPOSITORY_RECOVERY_PHASE_2C.md
```

```
git show --stat --oneline 6814153
6814153 docs: Phase 2C recovery report + Candidate A promotion manifest
 reports/CANDIDATE_A_PROMOTION_MANIFEST.json | 194 ++++++++++++++++
 reports/CANDIDATE_A_PROMOTION_MANIFEST.md   | 194 ++++++++++++++++
 reports/REPOSITORY_RECOVERY_PHASE_2C.md     | 328 ++++++++++++++++++++++++++++
 3 files changed, 716 insertions(+)
```

| Check | Result |
|---|---|
| Files changed | 3 — all under `reports/` |
| Production source files (`backend/`, `frontend/`, `scripts/`, `data/`, `db/`) | **0** |
| Nature of change | pure additions (716 insertions, 0 deletions) |

**Verdict: `6814153` contains recovery / promotion documentation ONLY.** No production source modification. Not `BLOCKED`.

---

## 12. Final Decision

Every required condition was evaluated:

| # | Condition | Result |
|---|---|---|
| 1 | `019b18a` parent = recovered master | **PASS** (`019b18a^ == 518cd896…`) |
| 2 | Production diff = Candidate A only | **PASS** (5 production + 1 test, exactly) |
| 3 | Forbidden production contamination = 0 | **PASS** (17 patterns × both diff sides = 0 hits) |
| 4 | 399 tests passed | **PASS** (399 passed, 0 failed) |
| 5 | Safety = PASS | **PASS** (`ALL_EQUIVALENT = True`) |
| 6 | Runtime smoke = PASS | **PASS** (A1–A4 all PASS, no network) |
| 7 | Frozen hashes = MATCH | **PASS** (Prompt / Few-shot / Dataset / DB all MATCH) |
| 8 | Master unchanged | **PASS** (`518cd896…`, zero Candidate A symbols) |
| 9 | Working tree clean | **PASS** (only 2 untracked `.workbuddy-ai/memory/*` files — see note) |
| 10 | `6814153` = documentation only | **PASS** (3 report files, 0 production files) |

**Working-tree note:** `git status --short` reports two untracked entries, both in `.workbuddy-ai/memory/` (`2026-09-20.md`, `MEMORY.md`). These are the assistant's own working-memory files, are outside the tracked production tree, and reflect no Candidate A content. With these excluded, the tracked working tree is clean and matches the branch tip exactly. They are **not** a promotion artifact and are not proposed for commit.

### Decision

```
READY_FOR_MASTER_MERGE
```

`master` is NOT merged with this branch by this review. The promotion is verified ready; the merge decision belongs to the operator.

---

`Status: STOPPED`
