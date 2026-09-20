# 数据库 Schema 说明（Database Schema）

> 阶段：阶段 2-任务 2（电商 SQLite 数据库基线）
> 日期：2026-09-14
> 修订 2026-09-14：补充「统一销售统计口径」（实际销量/销售额类指标默认排除 cancelled 订单，见第 5 节）。
> 本文件是数据库结构的权威描述，供后续 Schema Linking / Text2SQL / 评测集制作统一参照。

---

## 1. 数据库概述

- **数据库文件**：`db/ecommerce.db`（生成物，不入 git；由 `scripts/init_db.py` 一键重建）。
- **数据库类型**：SQLite（Python 内置 `sqlite3`），单文件。
- **数据来源**：全部为**合成数据**，由 `scripts/generate_data.py` 依据固定随机种子（`SEED = 20260914`）规则生成，**可重复生成、不依赖网络、不依赖 LLM**，不包含任何真实个人数据。
- **重建方式**：

  ```text
  python scripts/init_db.py
  ```

  流程：删除旧库 → 建表 → 插入数据 → 建立索引 → 执行基本验证。生成脚本是数据的权威来源，数据库文件不作为唯一来源。
- **表数量**：5 张核心表（`users` / `categories` / `products` / `orders` / `order_items`）。
- **约束约定**：所有连接启用 `PRAGMA foreign_keys = ON`；库内时间统一为 ISO `YYYY-MM-DD` 一种格式（无时区字段，均为同一时区口径）。

### 数据规模（开发阶段）

| 表 | 目标数量 | 实际数量（2026-09-14 生成） |
|---|---:|---:|
| users | 约 2,000 | 2,000 |
| categories | 约 30 | 30 |
| products | 约 500 | 500 |
| orders | 约 10,000 | 10,000 |
| order_items | 约 30,000 | 30,457 |

---

## 2. 表结构

### 2.1 users（用户表）

业务含义：平台注册用户，支持用户查询、用户地区、注册时间、用户状态类问题。

| 字段 | 类型 | 非空 | 键 | 业务含义 |
|---|---|---:|---|---|
| id | INTEGER | 是 | 主键 | 用户 ID |
| username | TEXT | 是 | UNIQUE | 用户名（中文姓名，唯一） |
| email | TEXT | 是 | UNIQUE | 邮箱（合成数据，使用保留域名 example.com） |
| region | TEXT | 是 | | 用户所在省份（15 个省级地区之一） |
| register_date | DATE | 是 | | 注册日期（ISO `YYYY-MM-DD`，范围 2023-01-01 ~ 2026-08-31） |
| status | TEXT | 是 | CHECK | 状态：`active`（活跃）/ `inactive`（停用） |

### 2.2 categories（分类表）

业务含义：商品分类，支持两级层级（一级分类 + 叶子分类），共 30 个分类。

| 字段 | 类型 | 非空 | 键 | 业务含义 |
|---|---|---:|---|---|
| id | INTEGER | 是 | 主键 | 分类 ID |
| name | TEXT | 是 | UNIQUE | 分类名称（8 个一级 + 22 个叶子） |
| parent_id | INTEGER | 否 | 外键 → categories.id | 父分类 ID（一级分类为 NULL，支持层级） |

### 2.3 products（商品表）

业务含义：平台商品，商品统一挂在**叶子分类**上（不直接挂一级分类）。

| 字段 | 类型 | 非空 | 键 | 业务含义 |
|---|---|---:|---|---|
| id | INTEGER | 是 | 主键 | 商品 ID |
| name | TEXT | 是 | UNIQUE | 商品名称（品牌 + 品类 + 型号，唯一） |
| category_id | INTEGER | 是 | 外键 → categories.id | 所属叶子分类 ID |
| price | REAL | 是 | CHECK(price > 0) | 商品当前售价（元，两位小数） |
| status | TEXT | 是 | CHECK | 状态：`on_sale`（在售）/ `off_sale`（下架） |

### 2.4 orders（订单表）

业务含义：用户订单，支持用户、下单时间、订单状态、金额、收货区域等分析。

| 字段 | 类型 | 非空 | 键 | 业务含义 |
|---|---|---:|---|---|
| id | INTEGER | 是 | 主键 | 订单 ID |
| user_id | INTEGER | 是 | 外键 → users.id | 下单用户 ID |
| order_date | DATE | 是 | | 下单日期（ISO `YYYY-MM-DD`，范围 2024-01-01 ~ 2026-09-12，整体偏向近期） |
| status | TEXT | 是 | CHECK | 状态：`pending` / `paid` / `shipped` / `completed` / `cancelled` |
| region | TEXT | 是 | | 收货省份（70% 与用户地区一致） |
| discount_amount | REAL | 是 | CHECK(≥ 0) | 订单级优惠金额（约 30% 订单享受，按明细合计比例减免） |
| shipping_fee | REAL | 是 | CHECK(≥ 0) | 运费（大额订单免运费） |
| total_amount | REAL | 是 | CHECK(≥ 0) | **订单最终实付金额**（口径见第 4 节） |

### 2.5 order_items（订单明细表）

业务含义：订单明细行，一条记录对应"某订单购买的某商品"。

| 字段 | 类型 | 非空 | 键 | 业务含义 |
|---|---|---:|---|---|
| id | INTEGER | 是 | 主键 | 明细行 ID |
| order_id | INTEGER | 是 | 外键 → orders.id | 所属订单 ID |
| product_id | INTEGER | 是 | 外键 → products.id | 所购商品 ID |
| quantity | INTEGER | 是 | CHECK(quantity > 0) | 购买数量（1~5 件） |
| unit_price | REAL | 是 | CHECK(unit_price > 0) | 成交单价快照（取自商品当前售价） |
| subtotal | REAL | 是 | CHECK(subtotal ≥ 0) | **明细行金额**（口径见第 4 节） |

---

## 3. 表关系

```text
users (1) ────< (N) orders (1) ────< (N) order_items (N) >─── (1) products (N) >── (1) categories

users.id            → orders.user_id
orders.id           → order_items.order_id
products.id         → order_items.product_id
categories.id       → products.category_id
categories.parent_id → categories.id（自引用，两级层级）
```

所有外键关系均已通过 `PRAGMA foreign_key_list` 与孤儿行扫描验证（见 `tests/test_database.py`）。

---

## 4. 金额字段语义（重要口径，四端统一）

项目统一口径（数据生成 / Schema / Prompt 示例 / 评测数据必须一致）：

### 4.1 `order_items.subtotal`（明细行金额，line-item amount）

- 定义：**单个订单明细行金额**。
- 公式：`subtotal = unit_price × quantity`（保留两位小数）。
- 它只描述"这一行买了多少钱的商品"，**不含**任何订单级调整。

### 4.2 `orders.total_amount`（订单最终实付金额，final paid order amount）

- 定义：**整个订单最终支付金额**。
- 它可以在明细合计基础上叠加订单级因素：

  ```text
  total_amount = Σ(subtotal) − discount_amount + shipping_fee
  ```

- 现实中还可能包含税费/退款等其它订单级调整，因此：

  > **不能人为规定 `orders.total_amount = SUM(order_items.subtotal)` 永远相等。**

- 本库中的差异来源（可解释业务因素，非随机误差）：
  - `discount_amount`：约 30% 订单享受 5%~25% 订单级优惠；
  - `shipping_fee`：未达免运费门槛的部分订单收取 6~15 元运费；
  - `cancelled` 订单最终实付为 0（无优惠、无运费）。

### 4.3 数据内验证

- 全库校验：`total_amount` 与「明细合计 − 优惠 + 运费」不一致的订单数 = **0**（`scripts/init_db.py` 验证输出与测试均覆盖）。
- 存在大量订单 `Σ(subtotal) ≠ total_amount`（差异来自上述订单级因素），满足口径演示需求。

---

## 5. 典型查询场景

后续 Text2SQL 将覆盖的典型业务问题类型（本库字段已完备支撑）：

| 问题类型 | 示例 | 涉及表 |
|---|---|---|
| 总量统计 | 本月销售额是多少？订单总数？ | orders |
| 商品维度 | 哪个商品销量最高？ | orders + order_items + products |
| 分类维度 | 哪个分类销售额最高？（含一级分类汇总） | orders + order_items + products + categories |
| 地区维度 | 不同地区订单量如何？ | orders（region）/ users（region） |
| 时间趋势 | 某段时间销售趋势如何？ | orders（order_date，按月聚合）/ orders + order_items |
| 用户维度 | 某用户购买过什么商品？ | users + orders + order_items + products |
| 状态维度 | 订单状态分别有多少？ | orders（status） |
| 金额口径 | 明细合计与实付金额的差异来源 | orders + order_items |

### 5.1 统一销售统计口径（四端一致，重要）

取消订单（`cancelled`）仍保留 `order_items` 明细（用于记录"下了什么"），但其实付金额为 0，**明细不计入任何实际销售统计**。

因此项目中的**商品销量、商品销售额、分类销售额**以及其它"实际销售"类指标，默认必须排除取消订单：

```sql
-- 标准写法：通过 orders 关联并排除 cancelled
SELECT p.name, SUM(oi.quantity) AS sold
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
WHERE o.status != 'cancelled'
GROUP BY p.id
ORDER BY sold DESC;
```

```sql
-- 分类销售额同理
SELECT c.name, ROUND(SUM(oi.subtotal), 2) AS revenue
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
JOIN categories c ON c.id = p.category_id
WHERE o.status != 'cancelled'
GROUP BY c.id
ORDER BY revenue DESC;
```

> 该口径同样写入后续 SQL 生成 Prompt 与评测数据（gold SQL）中，`scripts/init_db.py` 的验证 SQL 与 `tests/test_database.py` 均已按此口径实现。

---

## 6. 索引清单

仅建立能明确服务常见查询的基础索引：

```text
idx_orders_user_id        ON orders(user_id)
idx_orders_order_date     ON orders(order_date)
idx_orders_status         ON orders(status)
idx_order_items_order_id  ON order_items(order_id)
idx_order_items_product_id ON order_items(product_id)
idx_products_category_id  ON products(category_id)
```