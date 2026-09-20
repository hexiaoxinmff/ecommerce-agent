# ECO-SQL-Bench · Task 12 Batch 2 审核报告（Medium 30 条）

> 批次：E-0026 ~ E-0055（difficulty=medium，multi_turn=null，expected_behavior=answer）
> 日期：2026-09-15
> 生成器：`scripts/validate_eval_batch.py`（复用 `scripts/validate_eval_dataset.py` 的冻结校验/hash 实现，本批新增 Medium 支持：draft 内置 `operator_targets`、id 合并入集）
> 数据库：`db/ecommerce.db`（database_version=dev-2026-09-14，seed=20260914，schema_version=1.0）
> 状态：**30/30 审核通过（review_status = approved）**，已正式入集 `data/eval/ecommerce_eval_v1.json`（与 Easy 25 合并共 55 条），待总顾问复核

---

## 1. 批次概况

| 项 | 值 |
|---|---|
| 最终正式题 | 30（E-0026~E-0055） |
| 候选池总量 | 42（30 正式候选 + 12 备选池 D-0008~D-0019） |
| 淘汰/未采用 | 12（备选池：不重复进入正式集，保留备选，见 §7） |
| 难度 | 全部 medium |
| expected_behavior | 全部 answer |
| expected_empty | 全部 false（30 题均有真实非空结果） |
| 子查询 / 多表 JOIN | 0 / 0（Medium 禁止项全部未使用，见 §5.3） |

## 2. 生成与审核闭环（30/30 全部走完）

```text
按矩阵 §7.2/§7.3 设计题目（场景配额固定，禁止项硬边界）
  → 候选 Gold SQL（< 2 表 JOIN / 无子查询）
  → SQL Safety Validator（check_sql_safety + SchemaCatalog）
  → SQLite 只读执行（db/ecommerce.db）
  → 结果人工核验（行数 / 边界值 / 并列 Top-N / 口径）
  → gold_result_hash（normalize_result_hash）
  → 完全重复 + 规范化重复检测
  → 矩阵覆盖复核（场景配额 + operator 最低目标）
  → 入集（与 E-0001~E-0025 合并，hash 校验 55/55）
```

## 3. 逐条审核表（review_status = approved）

> gold_result 为 `db/ecommerce.db` 真实只读执行结果（R = 行数，首行与末行样例）；hash 为规范 §C 64 位 sha256。</br>
> 全部 30 条 hash 已重新执行核对一致（`--verify-hashes`，无漂移）。

| ID | question 摘要 | scenario | operators | gold_result | gold_result_hash [前12] | review_notes |
|---|---|---|---|---|---|---|
| E-0026 | 2024年起注册用户按年分布 | user_analysis | where,group_by,date_group,aggregate,date_filter | 3 行（2024:532, 2025:553, 2026:362） | `57baaac3ff24` | GROUP BY+date_group；注册年份结构统计 |
| E-0027 | 各地区的用户数量分布 | user_analysis | group_by,aggregate | 15 行（广东 246 … 重庆 69） | `136c3c48fa61` | 单表 GROUP BY（users.region 全量分布） |
| E-0028 | 累计下单≥13次用户 | user_analysis | join,group_by,having,aggregate | 5 行（罗冬梅 14, 杨勇/孙嘉懿/彭伟/高志明 13） | `ad5803063a69` | 两表 JOIN+HAVING；订单数=结构统计（口径同 E-0012） |
| E-0029 | 售价四档商品数 | product_analysis | case_when,group_by,aggregate | 4 档（<100:90, 100-500:275, 500-2000:88, ≥2000:47） | `b3a60c07ddc5` | CASE WHEN 分档（26.47~9351.34 真实区间） |
| E-0030 | 在售商品>20款分类 | product_analysis | where,aggregate,join,group_by,having | 10 行（家用电器 30 … 图书 21） | `000197e67100` | JOIN+WHERE(on_sale)+HAVING 阈值过滤 |
| E-0031 | 低价(<100)款数Top5分类 | product_analysis | where,aggregate,join,group_by,order_by,limit,top_n | 5 行（洗护清洁 22 … 护肤 6） | `92f1d4dd9496` | Top-5 边界无并列（6 vs 4）；order_sensitive=true |
| E-0032 | 各分类最高/最低售价 | product_analysis | aggregate,join,group_by | 22 行（手机通讯 7790.44/39.79 …） | `78c8580ec982` | 双聚合 MAX+MIN，全叶子分类 |
| E-0033 | 平均售价>1500 分类 | product_analysis | aggregate,join,group_by,having | 3 行（家用电器/电脑办公/手机通讯） | `5d7a768966d4` | HAVING AVG 阈值，高价分类识别 |
| E-0034 | 在售最贵5款商品 | ranking | where,join,order_by,limit,top_n | 5 行（恒源祥笔记本 9351.34 …） | `3f07dbe7e28e` | Top-5 边界无并列；ranking+order_sensitive |
| E-0035 | 一级分类子分类数 | category_analysis | aggregate,join,group_by | 8 行（家居/数码家电/服饰鞋包…各3、图书/母婴各2） | `43b750d8047f` | 分类自关联（join 一次，非 multiple_join） |
| E-0036 | 无商品挂载的分类 | category_analysis | aggregate,join,group_by,having | 8 行（8 个一级分类，商品挂叶子） | `69b5467b133c` | LEFT JOIN+HAVING COUNT=0，层级模型可解释 |
| E-0037 | 挂载商品Top5分类 | category_analysis | aggregate,join,group_by,order_by,limit,top_n | 5 行（家用电器 33 … 休闲零食 27） | `64accf2a87c3` | Top-5 边界无并列（27 vs 26） |
| E-0038 | 售价最高商品所属分类 | category_analysis | aggregate,join,group_by,order_by,limit,top_n | 1 行（电脑办公 9351.34） | `e5c5a0bed8d7` | GROUP BY MAX+LIMIT 1（Top-1） |
| E-0039 | 各订单状态订单数 | order_analysis | group_by,aggregate | 5 行（completed 6072 … cancelled 478） | `e5f18e0cbfd0` | 结构统计含取消，口径同 E-0012 |
| E-0040 | 2026年实付>5000订单数 | order_analysis | where,date_filter,aggregate | 1 行（794） | `f0f804b2aa77` | 金额+日期+状态三条件，total_amount 口径 |
| E-0041 | 各状态平均实付金额 | order_analysis | where,aggregate,group_by,order_by | 4 行（pending 3516.39 … completed 3276.5） | `30e21a9cf2c2` | GROUP BY status + AVG，排除 cancelled |
| E-0042 | 实付销售额Top10地区 | sales_analysis | where,aggregate,group_by,order_by,limit,top_n | 10 行（广东 419.88万 … 湖北 170.07万） | `3455fe8cd7b0` | 地区 SUM(total_amount) Top-10，边界无并列 |
| E-0043 | 2025年每月实付销售额 | sales_analysis | where,aggregate,date_group,date_filter,group_by | 12 行（2025-01 725433.47 … 12月 1608091.51） | `f08514d73724` | date_group 月度趋势，全年窗+排除 cancelled |
| E-0044 | 订单实付三档数量 | sales_analysis | where,aggregate,case_when,group_by,order_by | 3 档（<5000:7658, 5000-20000:1740, ≥20000:124） | `947f4fe28a6f` | CASE WHEN 金额分层；与 E-0024 时间窗题区分 |
| E-0045 | 客单价Top5地区 | sales_analysis | where,aggregate,group_by,order_by,limit,top_n | 5 行（四川 3691.05 … 3354.24） | `d4cf0982a0b4` | AVG(total_amount) 客单价 Top-5，无并列 |
| E-0046 | 2025年优惠金额合计 | sales_analysis | where,date_filter,aggregate | 1 行（592582.15） | `defc9c496a47` | SUM(discount_amount)，仅优惠>0 订单 |
| E-0047 | 2024~2026年度订单数 | time_analysis | aggregate,date_group,group_by | 3 行（2024:1661, 2025:4013, 2026:4326） | `197608f05366` | date_group 年度趋势，结构统计 |
| E-0048 | 2026年订单量Top5月份 | time_analysis | where,aggregate,date_filter,date_group,group_by,order_by,limit,top_n | 5 行（08月 614 … 03月 493） | `eab6d15b769b` | 月份 Top-5 边界无并列（493 vs 486） |
| E-0049 | 2024年各季度订单数 | time_analysis | where,aggregate,date_filter,case_when,group_by,date_group | 4 行（Q1 213 … Q4 614） | `5d8b95ee6e0f` | CASE WHEN 季度划分+GROUP BY 表达式 |
| E-0050 | 2026工作日/周末订单数 | time_analysis | where,aggregate,case_when,group_by,date_filter,order_by | 2 行（工作日 3091, 周末 1235） | `d5b01f515898` | strftime %w + CASE WHEN，周内分析 |
| E-0051 | 各收货地区订单量分布 | regional_analysis | aggregate,group_by | 15 行（广东 1315 … 重庆 363） | `3aa909949f9d` | orders.region 全量分布（结构统计） |
| E-0052 | 实付销售额>200万地区 | regional_analysis | where,aggregate,group_by,having | 7 行（广东 419.88万 … 北京 205.68万） | `38b66cab738e` | HAVING SUM 阈值分层；与 E-0042 Top-N、E-0051 计数区分 |
| E-0053 | 2026年7-8月订单量Top5地区 | regional_analysis | where,aggregate,date_filter,group_by,order_by,limit,top_n | 5 行（广东 163 … 北京 100） | `62135bdb083a` | 时间窗+地区 grouping Top-5，边界无并列（100 vs 75） |
| E-0054 | 平均售价Top5分类 | ranking | aggregate,join,group_by,order_by,limit,top_n | 5 行（家用电器 2765.38 … 运动装备 953.26） | `cf6d84c8ecb8` | AVG 全量统计 Top-5，边界无并列 |
| E-0055 | 累计消费Top5用户 | ranking | where,aggregate,join,group_by,order_by,limit,top_n | 5 行（宋嘉琪 92043.83 … 张俊熙 78236.82） | `0fe157dc71b9` | users×orders 累计消费 Top-5，边界无并列 |

**口径检查**：涉及销售额/客单价/优惠（E-0042~E-0046、E-0052、E-0055）全部排除 `cancelled`；金额一律使用 `orders.total_amount`（订单最终实付），未混用 `order_items.subtotal`（明细行金额，Medium 两表 JOIN 内无跨三表明细销售额题，符合禁止 `multiple_join`）；订单数/状态分布类（E-0026~E-0028、E-0039、E-0047、E-0050~E-0051）按结构统计口径不排除取消（与 E-0012 一致）。

## 4. 去重检查

| 类型 | 结果 |
|---|---|
| 完全重复（exact duplicate） | 0 |
| 规范化重复（normalized duplicate） | 0 |
| 跨批重复（与 E-0001~E-0025 规范化比对） | 0（脚本扫描 55 条 question 无重复） |
| 模板重复 | 0（见下） |

**模板重复专项核查**：
- E-0051（地区订单量分布）与 E-0052（地区销售额>200万）：同分组维度但聚合不同（COUNT vs SUM+HAVING），且 E-0052 金额口径排除 cancelled，语义分属"结构分布"与"销售规模分层"，非同一逻辑换常量；
- E-0044（订单金额三档）与 Easy E-0024（2026 全年总额）：一个做 CASE WHEN 分层统计、一个做整窗求和，逻辑不同形；已在设计期主动排除"仅换时间窗"的 E-0044 原型（原"2026 上半年销售额"与 E-0024 同模板，已替换为本三档题）；
- E-0042（销售额 Top-10 地区）与 E-0052（销售额>200 万地区）：Top-N 排名 vs HAVING 阈值两种题型，SQL 语义不同；
- E-0027（用户地区分布）与 E-0051（订单地区分布）、E-0026（注册年份分布）：维度/表均不同，不构成模板；
- 排序方向反例（如"累计消费最低 5 用户"）已放入备选池 D-0014 排除，未入正式集（延续 Batch 1 约定）。

## 5. 矩阵覆盖复核

### 5.1 Difficulty × Scenario（对照 evaluation-matrix.md §7.2 Medium 行）

| scenario | 实际 | 目标 | 结果 |
|---|---:|---:|---|
| user_analysis | 3 | 3 | PASS |
| product_analysis | 5 | 5 | PASS |
| category_analysis | 4 | 4 | PASS |
| order_analysis | 3 | 3 | PASS |
| sales_analysis | 5 | 5 | PASS |
| time_analysis | 4 | 4 | PASS |
| regional_analysis | 3 | 3 | PASS |
| ranking | 3 | 3 | PASS |
| **合计** | **30** | **30** | **PASS** |

### 5.2 Difficulty × Operator（对照 evaluation-matrix.md §7.3 Medium 行）

| operator | 实际 | 目标（最低/范围） | 结果 |
|---|---:|---:|---|
| aggregate | 29 | ≥18 | PASS |
| where | 17 | ≥15 | PASS |
| group_by | 27 | ≥15 | PASS |
| order_by | 13 | ≥12 | PASS |
| limit | 10 | ≥10 | PASS |
| join（2 表） | 12 | ≥10 | PASS |
| top_n | 10 | 6~12 | PASS |
| having | 5 | 5~10 | PASS |
| date_filter | 8 | ≥8 | PASS |
| date_group | 5 | 4~8 | PASS |
| case_when | 4 | 1~4 | PASS |

### 5.3 Medium 禁止项检查（矩阵 §7.3 硬边界）

```text
subquery = 0   ratio = 0   multiple_join = 0
nested_subquery = 0   conditional_aggregation = 0
comparison_to_average = 0   multi_dimension_grouping = 0
```

## 6. Easy 与 Medium 差异核查（结构复杂度是否真正上升）

30 题中具有明确 Medium 结构提升（较 Easy 增加 SQL 结构 / 业务维度 / 聚合逻辑 / 数据关系理解至少一项）的判定：

| 判定 | 数量 | 说明 |
|---|---:|---|
| 真正 Medium 结构提升 | **30** | GROUP BY 分布（如 E-0027/0035/0047）、两表 JOIN（E-0028/0030/0032/0055）、HAVING（E-0028/0030/0033/0036/0052）、日期分组（E-0026/0043/0047/0048/0049）、Top-N 排名（8 题）、CASE WHEN 分层（E-0029/0044/0049/0050） |
| 疑似 Easy 换皮 | **0** | 无仅换词/换阈值的题目；每题的聚合层级或分组维度均高于 Easy 38 题基线 |

> 验证方法：逐题对照 §6 分级规则——若去掉 JOIN/GROUP BY/HAVING/Top-N/时间维度后题目几乎不变，即判为 Easy 换皮。本批无此类。

## 7. 备选池（12 条，未入正式集，原因）

| ID | question 摘要 | 未采用原因 |
|---|---|---|
| D-0008 | 2025 年各月订单数 | 与 E-0048（2026 月 Top-5）同按月模板，覆盖价值重叠 |
| D-0009 | 2026 年各地区销售额 | 与 E-0042（销售额 Top-10）同模板（仅改时间窗） |
| D-0010 | 挂载商品 20~30 个分类 | 与 E-0030 同为"分类商品数+HAVING"，阈值区间换法 |
| D-0011 | 2026 年各地区订单量 | 与 E-0051 同分布模板（仅加年度窗） |
| D-0012 | 2024 下半年订单数 | 与 E-0040 同"时间窗+计数+排除取消"模式 |
| D-0013 | 注册最早 10 位用户 | 与 Easy E-0005 同模板（序排行数 3→10） |
| D-0014 | 累计消费最低 5 用户 | 排序方向反例（与 E-0055 成对），Batch 1 已约定排除此类 |
| D-0015 | 在售商品<5 款分类 | HAVING 反阈值；实际零行风险高，需 expected_empty 特判 |
| D-0016 | 售价>3000 元商品分类分布 | 与 E-0031（<100）同结构换阈值 |
| D-0017 | 2026 年各月优惠金额 | 与 E-0046 同模板（改时间窗） |
| D-0018 | 活跃用户地区分布 | 与 E-0027 同模板（加 status 条件） |
| D-0019 | 2025 年各状态订单数 | 与 E-0039 同模板（改年度窗） |

> 备选池保留于 `data/eval/drafts/medium_batch2_candidates.json` 的 `backups` 字段，不伪装为正式题。

## 8. 校验结果

- `python scripts/validate_eval_dataset.py`：单轮 **55** 条（Easy 25 + Medium 30），结构合法 + gold_sql 全部可只读执行，EXIT=0；
- `python scripts/validate_eval_dataset.py --verify-hashes`：**55/55** hash 重算一致（无漂移），EXIT=0；
- `python scripts/validate_eval_batch.py --drafts data/eval/drafts/medium_batch2_candidates.json`：30/30 通过 + 场景配额 + operator 覆盖全达标，EXIT=0；
- `python scripts/validate_eval_batch.py --drafts ... --commit`：正式入集合并成功（55 条），EXIT=0；
- `pytest -q`：**311 passed**（新增 4 条 Batch 2 合同测试：难度/禁止项/枚举/ID 范围+配额）。

## 9. 数据库安全

- 全部 gold_sql 顶层 `SELECT/WITH`，经 `check_sql_safety` 只读校验（禁止 INSERT/UPDATE/DELETE/DROP/ALTER）；
- 连接使用 `mode=ro` + `PRAGMA query_only=ON` 只读链路；
- 数据库核验（行数未变）：users 2000 / orders 10000 / order_items 30457 / products 500 / categories 30；
- seed=20260914 未变，schema_version=1.0 未变。

## 10. 发现的问题 / 遗留

1. 整体 55 条对 §7.4 题集级最低覆盖仍有缺口（Hard/Extra Hard 尚未生成，属规划内分批缺口，非本批缺陷）；
2. Top-N 边界已全部人工核对无并列（D7 规范），但评测 Runner 阶段仍需实现"并列键内部顺序忽略"逻辑；
3. E-0036 结果全部为一级分类（商品只挂叶子分类属数据库设计既有事实），题面与结果已由业务解释覆盖，无口径歧义；
4. `validate_eval_batch.py` 支持了 draft 级 `operator_targets` 与合并入集（向后兼容 Batch 1：无 `operator_targets` 时回落到 Easy 目标表）。

## 11. 下一阶段

Task 12 Batch 3：E-0056 ~ E-0085（Hard 30 条），复用本批 5 步闭环；首启多表 JOIN/子查询/HAVING 组合与占比能力。