# Task 20：E-0086 单例 dry-run（Fan-out Hint 最小干预验证）

**Question**: 累计消费金额超过全平台用户平均累计消费2倍、且累计下单超过8笔的用户有哪些？（请给出用户名、累计金额、订单数与购买商品种数）

## 1. 原始生成（正式 Agent 组件，temperature=0）
```sql
WITH user_stats AS ( SELECT u.id, u.username, SUM(o.total_amount) AS total_spent, COUNT(DISTINCT o.id) AS order_count, COUNT(DISTINCT oi.product_id) AS product_count FROM users u JOIN orders o ON u.id = o.user_id JOIN order_items oi ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY u.id ), platform_avg AS ( SELECT AVG(total_spent) AS avg_spent FROM user_stats ) SELECT us.username, ROUND(us.total_spent, 2) AS total_spent, us.order_count, us.product_count FROM user_stats us, platform_avg pa WHERE us.total_spent > pa.avg_spent * 2 AND us.order_count > 8 ORDER BY us.total_spent DESC
```

- detector_alarm = **True**
- hint_injected  = **True**
- 生成耗时 32.29s

## 2. Hint 注入后重新生成
```sql
WITH user_order_stats AS (SELECT o.user_id, COUNT(DISTINCT o.id) AS order_count, SUM(o.total_amount) AS total_spent FROM orders o WHERE o.status != 'cancelled' GROUP BY o.user_id), user_product_stats AS (SELECT o.user_id, COUNT(DISTINCT oi.product_id) AS product_count FROM orders o JOIN order_items oi ON oi.order_id = o.id WHERE o.status != 'cancelled' GROUP BY o.user_id), platform_avg AS (SELECT AVG(total_spent) AS avg_spent FROM user_order_stats) SELECT u.username, ROUND(uos.total_spent, 2) AS total_spent, uos.order_count, ups.product_count FROM user_order_stats uos JOIN users u ON u.id = uos.user_id JOIN user_product_stats ups ON ups.user_id = uos.user_id CROSS JOIN platform_avg pa WHERE uos.total_spent > pa.avg_spent * 2 AND uos.order_count > 8 ORDER BY uos.total_spent DESC
```

- 重新生成耗时 9.36s

## 3. EX 对比
- **原始 SQL**：exec=True, EX=False（结果集合不一致）
- **Hint 后 SQL**：exec=True, EX=True（）

## 4. 结论
- Detector 触发：是
- Hint 注入：是
- Fan-out 消除（不再出现 SUM(o.total_amount) 直连放大）：**已确认**（通过最终 SQL 结构复核：`SUM(o.total_amount)` 已移至订单粒度 CTE user_order_stats，明细层仅 COUNT(DISTINCT product_id)；并经 DB 直连执行验证结果与 Gold 一致）