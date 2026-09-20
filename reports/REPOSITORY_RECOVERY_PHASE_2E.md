# Repository Recovery Phase 2E — Final Promotion

> Date: 2026-09-20
> Mode: **fast-forward promotion.** No `--no-ff`, no rebase, no reset, no cherry-pick, no source/test/Prompt/Few-shot/Benchmark/DB/Linker modification, no new features.

---

## 1. Preflight

Read-only verification performed before any ref change:

| Ref | SHA |
|---|---|
| `master` | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| `019b18a` (Candidate A production) | `019b18a450c25887c1786ce2a76d55af57640ea8` |
| `6814153` (documentation) | `681415360f08b905cb607947ead5bc9a3767165d` |
| `019b18a^` | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| `6814153^` | `019b18a450c25887c1786ce2a76d55af57640ea8` |

Required assertions:

| Assertion | Result |
|---|---|
| `master == 518cd896…` | **PASS** |
| `019b18a^ == 518cd896…` | **PASS** |
| `6814153^ == 019b18a` | **PASS** |

**Fast-forward feasibility (explicitly checked).** `git merge-base --is-ancestor 518cd896 6814153` → **YES**. `518cd896` is an ancestor of `6814153`, so the promotion is a genuine fast-forward and **no merge commit is created**.

`git diff master 019b18a --exit-code` → `rc=1` (difference exists, as expected). Diff contained exactly the 6 Candidate A files.

### Untracked files — deliberately excluded

`git status --short` at preflight:

```
?? .workbuddy-ai/memory/2026-09-20.md
?? .workbuddy-ai/memory/MEMORY.md
?? reports/CANDIDATE_A_PROMOTION_REVIEW.json
?? reports/CANDIDATE_A_PROMOTION_REVIEW.md
```

**None of these were included in this promotion.** Neither `git add .` nor `git add -A` was used. The staging area was verified empty (`git diff --cached --name-only` → 0 entries) immediately before the ref move, so nothing could be swept in accidentally. These files remain untracked and preserved (see §10).

---

## 2. Fast-Forward Promotion

The promotion used an **atomic compare-and-swap**, not a merge:

```
git update-ref refs/heads/master 681415360f08b905cb607947ead5bc9a3767165d 518cd8964fc438aa82151f60b415cb4d9ce17a37
```

| Parameter | Value |
|---|---|
| new value | `681415360f08b905cb607947ead5bc9a3767165d` |
| expected old value | `518cd8964fc438aa82151f60b415cb4d9ce17a37` |
| exit code | **`rc=0`** |
| result | **CAS SUCCESS** |

The `expected_old` argument guarantees the ref is only moved if `master` still held precisely `518cd896…` at the moment of the write. This closes the race window between the preflight read and the write: had any other process moved `master` in between, `update-ref` would have returned non-zero **without overwriting anything**, and the procedure would have stopped.

Because the CAS succeeded, execution continued.

**HEAD repair.** At the time of the ref move, `HEAD` pointed at `candidateA_promotion_20260920`, so `git symbolic-ref HEAD refs/heads/master` was executed. This changes only the HEAD pointer and never touches the worktree.

---

## 3. Master Verification

```
master   = 681415360f08b905cb607947ead5bc9a3767165d
HEAD     = 681415360f08b905cb607947ead5bc9a3767165d
HEAD sym = master
```

`git log --oneline --decorate -3 master`:

```
6814153 (HEAD -> master, candidateA_promotion_20260920) docs: Phase 2C recovery report + Candidate A promotion manifest
019b18a perf: promote Candidate A runtime reuse
518cd89 (recovery_master_20260920) recovery: reconstruct master baseline 2026-09-20
```

**`HEAD = master` and `master = 6814153…` — both confirmed.** The history is linear with no merge commit.

---

## 4. Candidate A Presence

Verified with `git grep` against the `master` tree:

| Signature | Files matched in `backend/app/` |
|---|---|
| `_DEFAULT_GRAPH_CACHE` (A1) | 1 |
| `get_default_graph` (A1) | 1 |
| `_CATALOG_CACHE` (A2) | 1 |
| `get_cached` (A2) | 1 |
| `_get_client` (A3) | 1 |
| `_parse_single_readonly` (A4) | 1 |
| `check_sql_safety_with_tables` (A4) | 2 |

**Candidate A: PRESENT.**

The critical linker construction was re-confirmed at `master:backend/app/agent/graph.py`:

```
31: from app.schema.linker import SchemaLinker
40:     schema_linker = SchemaLinker(provider=provider)
```

`SchemaLinker(provider=provider)` **still present** — unchanged from the recovered baseline.

---

## 5. Experimental Isolation

| Component | In `master` tree |
|---|---|
| `backend/app/schema/rule_linker.py` | **NOT_IN_PRODUCTION** |
| `backend/app/schema/coverage_guard.py` | **NOT_IN_PRODUCTION** |
| `backend/app/schema/hybrid_linker.py` | **NOT_IN_PRODUCTION** |
| `backend/app/agent/schema_retrieval.py` | **NOT_IN_PRODUCTION** |
| `backend/app/schema/linker_factory.py` | **NOT_IN_PRODUCTION** |

`LINKER_MODE` across the entire `backend/` tree: **0 occurrences (absent)**. There is no configuration surface that could select an experimental linker. Production's linker path remains the fixed `SchemaLinker`.

---

## 6. Regression Tests

Command run **with `HEAD` on `master`** (so this proves master itself is now the Candidate A mainline):

```
python -m pytest backend/tests
```

Result:

```
399 passed, 1 warning in 25.61s
```

| Metric | Value |
|---|---|
| Passed | **399** |
| Failed | **0** |
| Warnings | 1 (`anyio.abc.BlockingPortal` deprecation from `starlette.testclient`) |
| Duration | 25.61 s |

This is the same figure measured on the promotion branch in Phase 2D — as expected, since `master` and `candidateA_promotion_20260920` are now the same commit.

---

## 7. Frozen Assets

| Asset | File | Hash | Match |
|---|---|---|---|
| Prompt V1.3 | `backend/app/sqlgen/prompt.py` | `31244e614fb36a693220a44d5a71610b0350aca26c61c8b98075afcd70d87fed` | **MATCH** |
| Dataset / Benchmark | `data/eval/ecommerce_eval_v1.json` | `dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a` | **MATCH** |
| Few-shot | `data/fewshot/ecommerce_examples.json` | `ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee` | **MATCH** |
| Database | `db/ecommerce.db` | `65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9` | **MATCH** |

All four match the values recorded before and after the Phase 2C application. The promotion moved refs only; it did not touch these assets. (The fast-forward changes no working-tree bytes at all — it only re-points `master` at a commit whose tree the worktree already matched.)

### Content diff `518cd896 → 6814153`

```
git diff 518cd896 6814153 --name-only
```

```
backend/app/agent/graph.py
backend/app/llm/mimo.py
backend/app/schema/metadata.py
backend/app/sqlgen/safety.py
backend/app/sqlgen/validator.py
backend/tests/test_task29_runtime_reuse.py
reports/CANDIDATE_A_PROMOTION_MANIFEST.json
reports/CANDIDATE_A_PROMOTION_MANIFEST.md
reports/REPOSITORY_RECOVERY_PHASE_2C.md
```

**9 files = 6 Candidate A files + 3 promotion/recovery documentation files.** `9 files changed, 1099 insertions(+), 13 deletions(-)`.

Forbidden-file scan:

| File | Occurrences |
|---|---|
| `rule_linker.py` | 0 |
| `coverage_guard.py` | 0 |
| `hybrid_linker.py` | 0 |
| `schema_retrieval.py` | 0 |
| `structural_coverage.py` | 0 |
| `linker_factory.py` | 0 |

No experimental production components present.

---

## 8. Branch Equality

```
master                        = 7286d114b6628550451aa076c7b8e76fb6ad727e
candidateA_promotion_20260920 = 7286d114b6628550451aa076c7b8e76fb6ad727e
```

**`master == candidateA_promotion_20260920` — confirmed.**

### Sequence note

The promotion point is `6814153`, and immediately after §4's CAS both `master` and `candidateA_promotion_20260920` read `6814153…`, satisfying the original §12 assertion exactly. This report was then written and committed as a **separate documentation commit** (`7286d11`) on `master`, as §17 permits. That advanced `master` by one commit and would have left the two branches unequal, so `candidateA_promotion_20260920` was advanced to `7286d11` with a second atomic CAS:

```
git update-ref refs/heads/candidateA_promotion_20260920 7286d11 6814153
→ rc=0 (CAS SUCCESS)
```

The invariant `master == candidateA_promotion_20260920` therefore holds at the final state, at `7286d11`. Both branches contain `6814153` as an ancestor, so the promotion content is fully preserved.

Merge-commit audit (parent count per commit):

| Commit | Parents | Assessment |
|---|---|---|
| `7286d11` (Phase 2E report) | 1 | non-merge |
| `6814153` (Phase 2C docs) | 1 | non-merge |
| `019b18a` (Candidate A) | 1 | non-merge |
| `518cd896` (recovered baseline) | 0 | reconstructed root |

**No merge commit exists anywhere in the promoted history.**

`git log --oneline --decorate --graph -5 --all`:

```
* 7286d11 (HEAD -> master, candidateA_promotion_20260920) docs: Phase 2E final promotion report
* 6814153 docs: Phase 2C recovery report + Candidate A promotion manifest
* 019b18a perf: promote Candidate A runtime reuse
* 518cd89 (recovery_master_20260920) recovery: reconstruct master baseline 2026-09-20
* 80a09b5 (workbuddy/master-e516219f, workbuddy/master-de8ad9a1, workbuddy/master-b947f329) chore: 首次提交 —— 建立版本基线
```

The structure matches the target: documentation on top of the perf commit on top of the recovered baseline, entirely linear.

---

## 9. Recovery Anchor

`recovery_master_20260920` was **NOT deleted** and still points at:

```
recovery_master_20260920 = 518cd8964fc438aa82151f60b415cb4d9ce17a37
```

This ref is the incident-recovery baseline anchor and remains available. It is deliberately preserved so the pre-promotion baseline can always be re-inspected — `master` having advanced to `6814153` does not remove the ability to examine the recovered baseline.

### Original master facts preserved (unchanged)

```
d668e6a6395394848fd7f96c6f292045e55febac:
  ORIGINAL_MASTER_COMMIT_UNRECOVERABLE

518cd8964fc438aa82151f60b415cb4d9ce17a37:
  reconstructed recovered baseline
  0 parent
  no fabricated ancestry
```

The historical statements in `REPOSITORY_RECOVERY_PHASE_2C.md` and `REPOSITORY_RECOVERY_PHASE_2D`-related material were **not modified**. This promotion does not rewrite history — it advances a branch pointer. It is still accurate to say that the original master is unrecoverable and that `518cd896` is a reconstructed baseline, now serving as the root of the promoted history.

---

## 10. Final State

```
master:
  7286d114b6628550451aa076c7b8e76fb6ad727e
  (promotion point 6814153 + Phase 2E report commit)

candidateA_promotion_20260920:
  7286d114b6628550451aa076c7b8e76fb6ad727e

recovery_master_20260920:
  518cd8964fc438aa82151f60b415cb4d9ce17a37

HEAD:
  master
```

The **promotion point** — the commit that carries Candidate A into master — is `6814153`, and it is an ancestor of the current `master` tip (verified with `git merge-base --is-ancestor 6814153 master` → YES). The current tip `7286d11` adds only the Phase 2E report.

### Working tree

`git status --short`:

```
?? .workbuddy-ai/memory/2026-09-20.md
?? .workbuddy-ai/memory/MEMORY.md
?? reports/CANDIDATE_A_PROMOTION_REVIEW.json
?? reports/CANDIDATE_A_PROMOTION_REVIEW.md
```

| Check | Result |
|---|---|
| Tracked-file modifications | **0** — tracked files clean |
| Untracked files | 4, preserved, **not** cleaned |
| `git clean -fd` used | **No** |

The tracked working tree is clean and matches the `master` tree exactly. The four untracked files are preserved for separate handling: two are assistant working-memory files, two are the Phase 2D review reports. **No cleanup was performed**, per instruction.

### Promotion path realized

```
master
  ↓
recovered baseline        (518cd896 — 0 parent, reconstructed)
  ↓
Candidate A               (019b18a — 6 files, perf: promote Candidate A runtime reuse)
  ↓
promotion/recovery docs   (6814153 — 3 reports)
```

### Note on this report

This report was written **after** the promotion completed and required **no production source modification** to produce. It is therefore not part of the promoted history as of `6814153`; if it is to be committed, it belongs in a separate documentation commit on top of `6814153`.

---

`Status: CANDIDATE_A_PROMOTED_TO_MASTER`
