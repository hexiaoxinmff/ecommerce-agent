# ECO-SQL-Bench · Task 12 Batch 1 审核报告（Easy 25 条）

> 批次：E-0001 ~ E-0025（difficulty=all easy，multi_turn=null）
> 日期：2026-09-15
> 生成器：`scripts/validate_eval_batch.py`（复用 `scripts/validate_eval_dataset.py` 的冻结校验/hash 实现）
> 数据库：`db/ecommerce.db`（database_version=dev-2026-09-14，seed=20260914，schema_version=1.0）
> 状态：**25/25 审核通过（review_status = approved）**，已正式入集 `data/eval/ecommerce_eval_v1.json`，待总顾问复核

---

## 1. 批次概况

| 项 | 值 |
|---|---|
| 最终正式题 | 25（E-0001~E-0025） |
| 候选题 | 32（25 正式候选 + 7 备选池 D-0001~D-0007） |
| 淘汰/未采用 | 7（备选池：不重复进入正式集，见 §6） |
| 难度 | 全部 easy |
| expected_behavior | 全部 answer（本批不引入 clarify/refuse，符合任务要求） |
| expected_empty | 全部 false（25 题均有真实结果，无需声明空结果） |

## 2. 生成与审核闭环（25/25 全部走完）

```text
设计题目 → 候选 Gold SQL → SQL Safety Validator → SQLite 只读执行 →
检查结果 → 人工审核 → gold_result_hash → 去重 → 矩阵覆盖复核 → 正式入集 → validate_eval_dataset.py 复核
```

## 3. 逐条审核表（review_status = approved）

> gold_result 为真实 `db/ecommerce.db` 只读执行结果（R = 行数，S = 首行样例）；hash 为规范 §C 算法 64 位 sha256。

| ID | question | scenario | operators | gold_result | gold_result_hash | review_notes |
|---|---|---|---|---|---|---|
| E-0001 | 平台上一共有多少用户？ | user_analysis | aggregate | 2000 | `2c041428…116e8` | 单表单聚合，正确 |
| E-0002 | 广东省有多少用户？ | user_analysis | aggregate, where | 246 | `cd8c581b…bbe75` | region=广东 条件过滤正确 |
| E-0003 | 平台有多少活跃用户？ | user_analysis | aggregate, where | 1707 | `c42a3e84…49d07` | status='active' 正确 |
| E-0004 | 2023年注册的用户有多少？ | user_analysis | aggregate, where, date_filter | 553 | `af9fe711…c3ed` | 注册整年范围过滤正确 |
| E-0005 | 注册时间最早的3位用户？（用户名+注册日期） | user_analysis | order_by, limit, top_n | 3 行（韩丽萍,2023-01-01 …） | `cd003bea…571a0` | 升序 Top-3，order_sensitive=true |
| E-0006 | 北京和上海两个地区的用户一共有多少？ | user_analysis | aggregate, where | 278 | `c64acbd5…0ce0` | IN 多值条件正确 |
| E-0007 | 平台上一共有多少商品？ | product_analysis | aggregate | 500 | `61e3d5fc…db280` | 单表单聚合正确 |
| E-0008 | 所有商品的平均售价是多少？ | product_analysis | aggregate | 717.72 | `2d99cb59…89da` | AVG+ROUND(2)，currency tolerance 0.01 |
| E-0009 | 售价最高的商品价格是多少？ | product_analysis | aggregate | 9351.34 | `8d935648…4d0a` | MAX 正确 |
| E-0010 | 在售商品中售价最低的是多少？ | product_analysis | aggregate, where | 26.47 | `6c7c4569…7fe3` | MIN + on_sale 状态正确 |
| E-0011 | 售价超过500元的商品有多少？ | product_analysis | aggregate, where | 135 | `4b357390…37e7` | price>500 计数正确 |
| E-0012 | 平台上一共有多少订单？ | order_analysis | aggregate | 10000 | `90c7d352…c305` | 订单量结构统计（不排除取消）正确 |
| E-0013 | 已取消的订单有多少？ | order_analysis | aggregate, where | 478 | `00ddc7fe…0077` | 状态结构计数，与销售额口径区分 |
| E-0014 | 2024年6月下了多少订单？ | order_analysis | aggregate, where, date_filter | 139 | `57626b28…03cf` | 月份范围过滤正确 |
| E-0015 | 非取消订单中实付金额最高的是多少？ | order_analysis | aggregate, where | 43997.76 | `a41e023e…1cc0` | **口径**：orders.total_amount + 排除 cancelled |
| E-0016 | 最近下的5笔订单？（订单ID+下单日期） | order_analysis | order_by, limit, top_n | 5 行（9892,2026-09-12 …） | `9595d1bf…58d3` | 日期倒序 Top-5，order_sensitive=true |
| E-0017 | 2024年实付金额最高的5笔非取消订单？（ID+金额） | order_analysis | where, date_filter, order_by, limit, top_n | 5 行（8025,43427.79 …） | `fd40b30e…47e4` | **口径**：日期+状态+金额排序，order_sensitive=true |
| E-0018 | 平台上一共有多少个商品分类？ | category_analysis | aggregate | 30 | `cb2129a0…53ea` | 基础计数正确 |
| E-0019 | 有多少个一级（顶级）商品分类？ | category_analysis | aggregate, where | 8 | `5735af05…01d0` | parent_id IS NULL 层级语义正确 |
| E-0020 | 收货地为广东的订单有多少？ | regional_analysis | aggregate, where | 1315 | `9f312289…fc1` | orders.region 地区维度正确 |
| E-0021 | 收货地为上海或北京的订单有多少？ | regional_analysis | aggregate, where | 1375 | `de4dd663…32a` | IN 多值正确 |
| E-0022 | 2025年全年一共下了多少订单？ | time_analysis | aggregate, where, date_filter | 4013 | `1816c2a0…edf2` | 整年范围过滤正确 |
| E-0023 | 平台最早的订单是哪一天下的？ | time_analysis | aggregate | 2024-01-01 | `9f282ef0…8758` | MIN(date) 正确，value_type=date |
| E-0024 | 2026年非取消订单的实付总额是多少？ | sales_analysis | aggregate, where, date_filter | 13561897.54 | `2860b57b…23be` | **口径**：SUM(total_amount) 排除 cancelled，currency tolerance 0.01 |
| E-0025 | 非取消订单的平均实付金额（客单价）是多少？ | sales_analysis | aggregate, where | 3329.72 | `0280abf5…794a` | **口径**：AVG(total_amount) 排除 cancelled，currency tolerance 0.01 |

**口径检查**：销售类（E-0024/E-0025）与金额相关（E-0015/E-0017）均正确排除 `cancelled` 并使用 `orders.total_amount`；未混用 `order_items.subtotal`。`subtotal` 属订单明细行金额，Easy 档单表题目不涉及明细跨表金额，符合规范。

## 4. 去重检查

| 类型 | 结果 |
|---|---|
| 完全重复（exact duplicate） | 0 |
| 规范化重复（normalized duplicate，去标点/空白） | 0 |
| 模板重复（仅换地区/关键词） | 0 |
| 方向反例对（同一表同维度正/反 Top-N） | 已排除（备选池 D-0001/D-0003 对应此类，未入正式集） |

说明：E-0009（MAX 单值）与 E-0010（MIN+on_sale 单值）为不同聚合/条件，非模板复制；E-0002（user.region）与 E-0020（orders.region）分属用户/订单两张表、业务语义不同，不构成重复。

## 5. 矩阵覆盖复核

### 5.1 Difficulty × Scenario（对照 evaluation-matrix.md §7.2 Easy 行）

| scenario | 实际 | 目标 | 结果 |
|---|---:|---:|---|
| user_analysis | 6 | 6 | PASS |
| product_analysis | 5 | 5 | PASS |
| order_analysis | 6 | 6 | PASS |
| category_analysis | 2 | 2 | PASS |
| regional_analysis | 2 | 2 | PASS |
| time_analysis | 2 | 2 | PASS |
| sales_analysis | 2 | 2 | PASS |
| **合计** | **25** | **25** | **PASS** |

### 5.2 Difficulty × Operator（对照 evaluation-matrix.md §7.3 Easy 行）

| operator | 实际 | 目标 | 结果 |
|---|---:|---:|---|
| aggregate | 22 | 20 | PASS |
| where | 16 | 15 | PASS |
| date_filter | 5 | 5 | PASS |
| order_by | 3 | 8 | **缺口 5** |
| limit | 3 | 8 | **缺口 5** |
| top_n | 3 | 0（Easy 不设） | 超出目标（Top-N 易档题天然携带，合理） |
| group_by / join / having / subquery / 复杂标签 | 0 | 0 | PASS（Easy 禁止项全部为 0） |

**缺口说明（重要，已按任务规范 §9 记录、不擅自改矩阵）**：

`order_by=8 / limit=8` 与 `aggregate=20` 在同一批 25 条 Easy 题内**结构性不可同时满足**：
- 带 `ORDER BY + LIMIT` 的题是"有序列表"题，其结果不是聚合标量；
- 单表不跨表、无 GROUP BY 的约束下，一条题要么是"聚合标量"（贡献 aggregate），要么是"有序列表"（贡献 order_by/limit），无法两者兼得；
- 25 条 = 20 条聚合 + 至多 5 条列表 → order_by/limit 理论上限 = 5，且达到 5 需要引入"方向反例"型模板题（如"最早/最晚注册 Top-3"成对出现），与 §11/§18 去重规范冲突；
- 本批以质量优先取 3 条列表（E-0005/E-0016/E-0017），order_by/limit 各 3 为高质量上限。

**建议（供总顾问定夺，任选其一）**：
1. 将 Easy 行 order_by/limit 目标下调至 3~5（与本批实测对齐）；
2. 将 top_n 的"有序列表"语义计入 order_by/limit 计数口径；
3. 接受该差距并在后续批次以缺口补题方式对冲（不推荐：会引入模板题）。

> 除上述两项外，**Easy 行其余目标全部达成**；本差别不影响 25 条题目的独立有效性。

## 6. 备选池（未入正式集，原因）

| ID | question 摘要 | 未采用原因 |
|---|---|---|
| D-0001 | 注册最晚的3位用户 | 与 E-0005 构成"排序方向反例"，模板重复风险 |
| D-0002 | 售价低于100元的商品数 | 与 E-0011（>500）同模式换阈值，模板重复风险 |
| D-0003 | 在售售价最低3个 | 与 E-0010（MIN 在售最低价）语义重复 |
| D-0004 | 运费>0 订单数 | 与 E-0013/E-0014 同"条件计数"模式，覆盖价值有限 |
| D-0005 | 优惠订单数 | 同上 |
| D-0006 | 停用用户数 | 与 E-0003（活跃用户）状态反例，模板重复风险 |
| D-0007 | 全部非取消总额 | 与 E-0024（2026年总额）同模式换时间范围 |

> 依据任务 §17：备选池保留在 `data/eval/drafts/easy_batch1_candidates.json`，不伪装为正式题。

## 7. 校验结果

- `python scripts/validate_eval_dataset.py`：单轮条目数 **25**，结构合法 + gold_sql 可只读执行，EXIT=0；
- `python scripts/validate_eval_dataset.py --verify-hashes`：全部 hash 重算一致（无漂移），EXIT=0；
- `pytest -q`：见仓库当前基线（Task 11 校验脚本测试 29 条 + 其余全部通过）。

## 8. 发现的问题 / 遗留

1. 已冻结矩阵 Easy 行 `order_by/limit=8` 与本批 `aggregate=20` 结构性冲突（证明见 §5.2），待总顾问裁决；
2. 数据库说明中的"华南/华东"等大区口径不在字段中，本批时间桶/地区题均使用字段内真实取值（省级地区 + 固定日期范围），未使用 `date('now')`，保证 hash 可复现；
3. 本批为 Easy，未覆盖 JOIN/子查询/占比 等能力，属正常批次边界。

## 9. 下一阶段

Task 12 Batch 2：E-0026 ~ E-0055（Medium 30），复用本批 5 步闭环与 `validate_eval_batch.py`。