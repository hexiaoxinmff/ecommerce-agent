# Few-shot Retrieval 说明

> 阶段：阶段 4-任务 4（Few-shot Retrieval 基础能力）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 概述

根据用户当前问题（及其 Schema Linking 结果），从本地人工整理的
Text2SQL 示例中检索最相关的 Top-K 个 Few-shot Examples，供后续
SQL Generator 参考。本模块**不生成 SQL、不调用 Mimo / OpenAI /
Embedding**。

> 当前版本为**规则型可解释检索**，**不是 Embedding / RAG**。
> 不引入向量数据库、Embedding API、Chroma/FAISS/Milvus/ES/Redis 等。

## 2. Few-shot Dataset 设计

- 文件：`data/fewshot/ecommerce_examples.json`；
- 示例数量：**23 条**人工高质量样例（覆盖商品/类别/用户/地区/订单/
  趋势/占比/价格等高频分析场景），scenario 互不相同；
- **版本**：FEWSHOT_V3（Task 14.3 干净版：删除与 Benchmark Gold 泄漏的
  ex_002、重写 V2 泄漏示例为独立实例；通过
  `python scripts/check_benchmark_leakage.py` 验证无泄漏）；
- 必须符合项目业务口径，「实际销售额/销量」默认排除
  `orders.status = 'cancelled'` 订单；`subtotal`=明细行金额、
  `total_amount`=最终支付金额，两者语义区别在样例中保持一致；
- 示例不得直接复用 Benchmark Gold SQL / 专属日期 / 专属阈值
  （Leakage Gate 强制检查）。

### 字段结构

```json
{
  "id": "ex_001",
  "question": "近30天销售额最高的商品有哪些？",
  "scenario": "product_sales_ranking",
  "tables": ["orders", "order_items", "products"],
  "columns": ["orders.order_date", "orders.status", "..."],
  "sql": "SELECT ...",
  "explanation": "按商品汇总销售额并进行排序。",
  "tags": ["商品", "销售额", "排名", "时间范围"]
}
```

- `columns` 一律使用「表名.字段名」；
- scenario 互不重复，便于后续 SQL Generator 组合。

## 3. 数据结构（backend/app/fewshot/models.py）

```python
FewShotExample(id, question, scenario, tables, columns, sql, explanation, tags)
FewShotQuery(question, tables=[], columns=[], scenario=None, top_k=3)
FewShotMatch(example_id, score, question, scenario, tables, columns, sql, explanation)
FewShotResult(question, matches)
```

## 4. 数据集加载与校验（dataset.py）

- 首次使用时从 JSON 读取（`FEWSHOT_DATASET_PATH` 可覆盖，
  默认 `data/fewshot/ecommerce_examples.json`）；
- 表名/字段名以当前**真实 SQLite Schema**（SchemaCatalog）复核；
- 以下任一情况**明确报错**（不静默跳过）：
  JSON 解析失败 / 顶层非数组 / 缺字段或类型错误 / 重复 example_id /
  SQL 为空 / 表不存在 / 字段不存在 / 字段表不在 tables 中；
- `get_dataset()` 带一级缓存，`reload_dataset()` 强制刷新。

## 5. 检索算法（retriever.py）

纯本地规则型检索，确定性、可解释、可复现。

```text
score =
   0.30 * 关键词Jaccard
 + 0.25 * 表重合(Jaccard)
 + 0.25 * 字段重合(Jaccard)
 + 0.20 * 场景/标签分
```

- **关键词**：固定中文关键词表（销售额/销量/订单/用户/地区/商品/类别/
  排名/趋势/平均/数量/近30天/上月/Top…），
  用户问题与 example（问题+标签）取关键词集合 Jaccard；
- **表重合 / 字段重合**：用户 Schema Linking 的 tables/columns 与
  example 的 tables/columns 取集合 Jaccard；
- **场景分**：用户 scenario 与 example scenario 完全相等取 1.0，
  否则取 0.5 × tags Jaccard；
- 权重见 `WEIGHTS` 常量，可测试、可解释。

**排序**：按 `(score 降序, example_id 升序)` 稳定排序。

> 注意：`score` 是**检索相似度**，不是 **SQL 正确性**。
> 找到的 Few-shot 只是参考案例，后续 SQL Generator 仍须重新生成与验证 SQL。

## 6. top-k 机制

- `top_k` 默认 3，API 层限制为 1~50（`top_k=0` / 超大值 -> HTTP 422，
  明确处理不崩溃）；
- Retriever 层：`top_k < 1` 抛 `ValueError`；`top_k` 大于数据集大小
  时按数据集大小裁剪；
- 不允许返回数据集之外的 example（返回的 example_id 必来自数据集）。

## 7. 数据只读验证（scripts/validate_fewshot_dataset.py）

```bash
python scripts/validate_fewshot_dataset.py
```

对 23 条示例逐个检查：
1. 数据集可加载、id 唯一、缺字段报错；
2. 表 / 字段存在于真实 Schema；
3. SQL 必须以 `SELECT`/`WITH` 开头（只读）；
4. SQL 在真实数据库**只读连接**上解析并执行成功（写入会被只读层拒绝）。

结果：23/23 全部通过（返回行数见脚本输出），数据库未被修改。

## 8. API

```http
POST /api/fewshot/retrieve
Content-Type: application/json
```

请求示例：

```json
{
  "question": "近30天销售额最高的商品有哪些？",
  "tables": ["orders", "order_items", "products"],
  "columns": ["orders.order_date", "orders.status", "..."],
  "scenario": "product_sales_ranking",
  "top_k": 3
}
```

响应（HTTP 200）：

```json
{
  "success": true,
  "result": {
    "question": "近30天销售额最高的商品有哪些？",
    "matches": [
      {
        "example_id": "ex_001",
        "score": 0.92,
        "question": "...",
        "scenario": "product_sales_ranking",
        "tables": ["..."],
        "columns": ["..."],
        "sql": "SELECT ...",
        "explanation": "..."
      }
    ]
  },
  "error": ""
}
```

错误状态码约定：

| 场景 | HTTP | 说明 |
|---|---|---|
| question 空/空白/超长、top_k 越界、columns 非「表.字段」、tables 非字符串 | 422 | 参数校验 |
| 数据集加载失败（文件缺失/JSON 非法/表字段不存在等） | 500 | `Few-shot dataset error: ...` |
| 未预期异常 | 500 | 固定文案，不回显 traceback |

依赖关系：

```text
API
 ↓
FewShotRetriever
 ↓
FewShotDataset
```

**禁止 `Retriever -> MimoProvider` / `Retriever -> OpenAI SDK`**（本模块不满足）。未修改前端。

## 9. 测试结果

新增三个测试文件（不依赖 Mimo）：

- `test_fewshot_dataset.py`：默认数据集规模/唯一 id/表与字段存在/SQL 非空，
  以及 JSON 非法、缺字段、重复 id、不存在表/字段、字段表不匹配、空 SQL 的报错；
- `test_fewshot_retriever.py`:三类代表性问题 Top 命中（ex_001 / 用户维度 / ex_003）、
  score 降序与同分稳定排序、top_k=1/3/5、top_k=0 报错、top_k 超大裁剪、
  返回 id 均来自数据集、相同 Schema 得分不低于不相关、score 在 0~1；
- `test_fewshot_api.py`：正常请求、空/空白 question、top_k=0/51/1000、columns
  格式非法、tables 类型非法、数据集异常 500、返回结构正确。

运行：

```bash
pytest -q                    # 全部通过（357 passed，含 Task 14.3 新增）
python -m compileall backend scripts/test_fewshot_retrieval.py scripts/validate_fewshot_dataset.py
```

## 10. 真实验证（scripts/test_fewshot_retrieval.py）

```bash
python scripts/test_fewshot_retrieval.py
```

真实 SQLite + Few-shot Dataset + 规则型 Retriever（不调用 Mimo）结果：

- 「近30天销售额最高的商品有哪些？」-> Top1 ex_001（0.88，商品销售排名）
- 「哪个地区的用户最多？」-> 用户维度示例（ex_002 已于 Task 14.3 因泄漏移除，
  现命中 users 维度示例，如 ex_007 活跃用户数）
- 「哪个商品类别销售额最高？」-> Top1 ex_003（0.925，类别销售排名）

## 11. 局限性

1. 中文关键词表覆盖有限，新颖表达可能匹配偏差（后续可扩展词表/同义词）；
2. 规则检索无法理解深层语义（如「复购」「客单价」等复杂口径），
   需要人工补充对应示例或升级检索手段；
3. 检索得分只代表「相似度」，不代表答案正确性；
4. 数据集为人工整理基线，随业务口径演进需人工维护。

## 12. 当前限制（禁止进入的后续能力）

```text
SQL Generator：未实现
SQL Validator：未实现
SQL Executor：未实现
SQL Repair：未实现
LangGraph：未接入
Multi-turn：未实现
Chart / Conclusion Generation：未实现
RAG / 向量检索：未实现（当前为规则型）
```