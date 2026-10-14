# Task 38 · E-0057 统计实体 / 驱动表约束实验

- 任务类型：**单变量 Prompt 侧约束注入实验**（条件性局部生效）
- 目标题：`E-0057`（`user_analysis` / hard）
- 单一变量：`SQLGEN_EXTRA_RULES=E8` ⇒「条件性统计实体 / 驱动表约束」
- 状态：`TASK_38_COMPLETE`
- 结论一句话：**E8 用 0 次额外 LLM 调用，把 E-0057 从 `result_mismatch` 修成 EX ✓，且触发域恰好只有这一题、零回归。但本题 +3.0pp 的整体 EX 提升中，只有 1/3 可归因于 E8。**

---

## 1. 目标缺陷机理

**题目**：`按用户累计下单次数将用户分为三档（1-3单、4-10单、11单及以上），各档分别有多少用户？`

**Gold 的统计实体**：`orders` → `GROUP BY user_id` → 只统计**真实下过单的用户** → CASE 分档。

**Pred（OFF，冻结基线行为）**：
```sql
SELECT CASE WHEN order_count BETWEEN 1 AND 3 THEN '1-3单'
            WHEN order_count BETWEEN 4 AND 10 THEN '4-10单'
            ELSE '11单及以上' END AS order_tier,
       COUNT(*) AS user_count
FROM (
    SELECT u.id, COUNT(o.id) AS order_count
    FROM users u LEFT JOIN orders o ON o.user_id = u.id
    GROUP BY u.id
) AS user_orders
GROUP BY order_tier
```

**失效链条**（三步，缺一不可）：

1. `users LEFT JOIN orders` 把**锚点表 `users`** 当作统计实体 ⇒ 驱动集合变成"全部 2000 个用户"；
2. 零单用户 `COUNT(o.id) = 0`；
3. `CASE` 的 `ELSE` 是**兜底分支**，`0` 既不满足 `BETWEEN 1 AND 3` 也不满足 `BETWEEN 4 AND 10` ⇒ **全部落进"11单及以上"**。

第 3 步是这个缺陷最阴的地方：`CASE` 的 `ELSE` 语义上等价于 `>= 11`，但写法上**不校验下界**。只要上游把 `0` 喂进来，兜底分支就会静默吞掉。

### 1.1 数据级量化（实测，非推算）

```
users=2000  orders=10000  users_with_orders=1983  zero_order_users=17

GOLD -> [('1-3单', 490),  ('4-10单', 1474), ('11单及以上', 19)]   total=1983
OFF  -> [('1-3单', 490),  ('4-10单', 1474), ('11单及以上', 36)]   total=2000
ON   -> [('1-3单', 490),  ('4-10单', 1474), ('11单及以上', 19)]   total=1983
```

| 档位 | GOLD | OFF | ON | \|OFF−GOLD\| |
|---|---:|---:|---:|---:|
| 1-3单 | 490 | 490 | 490 | **0** |
| 4-10单 | 1474 | 1474 | 1474 | **0** |
| 11单及以上 | 19 | **36** | 19 | **17** |
| **合计** | **1983** | **2000** | **1983** | **17** |

**17 个零单用户 100% 落入最高档**，其余两档一位不差。这不是"数值偏差"，是**口径污染**：整体用户数从 1983 虚增到 2000，且增量全部堆在业务上最敏感的"高价值用户"档位——按这个结果做用户分层运营，会把 17 个从未下单的用户当成重度用户。

### 1.2 为什么 Few-shot 反而推了一把

E-0057 的 `fewshot_retrieve` 命中（OFF 臂实测 trace）：

```json
{"match_count": 3, "example_ids": ["ex_010", "ex_016", "ex_007"]}
```

`ex_016` 恰好在演示 `users LEFT JOIN orders` 的写法，并且它的语义是**保留零单用户**（"哪些用户没有下过单"类问题）。检索器按题面相似度召回，看不出"这一题的 LEFT JOIN 会把零单用户喂进 ELSE 分支"——**few-shot 在这里不是中性的，它是负向的**。

这不是 Few-shot 数据集的错（`ex_016` 对它是正确的例），而是**检索器只有词面相似度、没有统计实体意识**。本任务不动 Few-shot（用户明令禁止），因此绕过它，在生成前显式约束。

---

## 2. 关键设计决策：约束不能禁止 LEFT JOIN

这是本任务最容易做错的地方。

E-0036 的 gold SQL：
```sql
SELECT c.name FROM categories c
LEFT JOIN products p ON p.category_id = c.id
GROUP BY c.id HAVING COUNT(p.id) = 0
```

它**必须**用 `LEFT JOIN`——因为问的是"**哪些分类下没有任何商品**"，需要保留完整分类宇宙。

| | E-0036 | E-0057 |
|---|---|---|
| 结构 | `X LEFT JOIN Y` | `X LEFT JOIN Y` |
| 锚点表 | `categories` | `users` |
| 问的是什么 | **全宇宙里哪些实体"什么都没发生"** | **按"发生次数"给实体分档** |
| 零活动实体 | 必须保留（它就是要找的答案） | **必须排除**（它不属于任何档） |
| LEFT JOIN | 正确 | 错误 |

**结构完全相同，语义完全相反。** 因此判别器绝对不能是 JOIN 类型，只能是**"统计实体在本题是否应当有活动"**：

```
include_zero_activity_entities = ?
```

这一个布尔量，比一百条"不要用 LEFT JOIN"的 Prompt 规则都准。E-0036 的分档需要保留零单用户 ⇒ 触发条件里必须有一条"题目显式要求包含零活动实体时不注入"，且 E-0036 实测**未触发**（见 §4）。

---

## 3. 实现

### 3.1 新增模块 `backend/app/sqlgen/entity_constraint.py`（173 行）

sha256 `bb691a95c54a3bdc6289bfb52532bf995b12d19b87ac369b93a1cca5b6749d63`

核心数据结构即任务书 §四 建议的字段：

```python
@dataclass(frozen=True)
class AnalysisEntityConstraint:
    analysis_entity: str                      # "users_with_orders"
    driver_table: str                         # "orders"
    aggregation_grain: str                    # "user_id"
    include_zero_activity_entities: bool      # False
    entity_table: str                         # "users"
    reason: str                               # 命中原因，可审计
```

判定走**四道门**，全过才返回约束，任一不过返回 `None`：

1. **实体词存在**：`用户/会员/分类/类目/商品` ∈ 问题；
2. **对实体计数**：`_COUNT_ENTITY_PATTERN` 命中；
3. **按行为分档**：行为词（`订单/下单/购买`）+ 粒度词同时出现；
4. **未显式要求包含零活动实体**：`_INCLUDE_ZERO_PATTERNS` 全部不命中。

### 3.2 踩到的坑：E-0082 误触发（已修）

初版 `_COUNT_ENTITY_PATTERN = r"(多少|几个|几档|数量)"`。E-0082 是 `…的比例是多少？`，被 `多少` 命中；同时题面里的 `商品` 命中实体词 ⇒ 触发域 2/100。

**修法**：要求量词与实体词**相邻**，把"问比例值"排除掉：

```python
_COUNT_ENTITY_PATTERN = re.compile(
    r"(多少|几)\s*(个|位|名|档|类|种|件)?\s*"
    r"(用户|会员|分类|类目|商品|人)"
)
```

并把门顺序调成"先判实体词"，早退。触发域回到 **1/100**。

这条要在报告里留着：**"多少个 X" 与 "X 的比例是多少" 是两种问法，正则必须咬住量词与实体的邻接关系，否则一放宽就误伤比例类题目。**

### 3.3 注入点：`backend/app/sqlgen/prompt.py`（+30 / −0）

sha256 `193d37cd08e893bc7626ffa250a6360677cf1d7d1dae14f3a9148e0622ee22ad`

**没有新增 Node。** 复用既有 `SQLGEN_EXTRA_RULES` 开关（E4/E5/E6/E7 已在用），加一个 `E8` flag：

```python
def entity_constraint_block(question: str) -> str:
    raw = os.getenv("SQLGEN_EXTRA_RULES", "").strip()
    if not raw:
        return ""
    flags = {p.strip().upper() for p in raw.split(",") if p.strip()}
    if "E8" not in flags:
        return ""
    constraint = detect_analysis_entity_constraint(question)
    if constraint is None:
        return ""
    return constraint.to_prompt_block()
```

`build_prompt()` 里插在 `extra_block` 与 `_CONSTRAINTS` 之间，一行：

```
        f"{extra_block}"
+       f"{entity_text}"
        f"{_CONSTRAINTS}\n"
```

**为什么不需要新 Node**：约束是**题目文本的纯函数**（`question -> str | None`），无 I/O、无状态、无 LLM。放进已有的 prompt 组装阶段零成本。任务书原话"如果不需要新 Node，就不要为了架构漂亮新增 Node"——这里确实不需要，所以没加。

**为什么用 env flag 而不是直接改 Prompt**：这样 OFF 分支**恒返回空串**，Prompt 与冻结基线**逐字节相同**（§4.1 已实证），单变量对照才成立。

### 3.4 注入文本

```
【统计实体 / 驱动表约束】
- 本题的统计对象是「有下单行为的用户」，不是「全部用户」。
- 驱动表：orders；聚合粒度：user_id。
- 禁止用 users LEFT JOIN orders 作为驱动集合 —— 那会把 0 单用户
  带入统计，而 0 单用户不属于 1-3单 / 4-10单 / 11单及以上 任何一档。
- 请从 orders 出发 GROUP BY user_id 得到每单量，再对分档计数。
```

---

## 4. 验证

### 4.1 零 LLM 前置验证（`scripts/task38_trigger_check.py`）

| 检查项 | 结果 |
|---|---|
| OFF 模式无约束段 | ✔ Prompt 长度 2040 |
| ON 模式 E-0057 注入 | ✔ 长度 2524（Δ=484） |
| ON 模式 E-0036 不注入 | ✔ |
| ON 模式 E-0077 不注入 | ✔ |
| **100 题全量扫描触发数** | ✔ **恰好 1（仅 E-0057）** |
| OFF Prompt vs `git HEAD` 版本，100 题逐一比对 | ✔ **0/100 mismatch** |

最后一行是单变量实验的地基：OFF 臂与冻结基线在 Prompt 层面**逐字节一致**，所以 OFF/ON 的任何差异都只能来自 E8。

### 4.2 第一阶段：E-0057 单例 OFF/ON（真实 Mimo）

**⚠️ 首次 OFF 臂作废并重跑。** 首轮 OFF 返回 `LLMNetworkError`、`provider_calls=0`、`schema_link` 耗时 22673 ms、`valid_model_run=false`——这是瞬时网络故障，不是测量值。**没有从一次没真正跑起来的臂里报告任何结论**，重跑后 OFF 与冻结基线行为完全一致。

| | OFF（重跑） | ON |
|---|---|---|
| `execution_accuracy` | **False** | **True** |
| `error_type` | `result_mismatch` | `None` |
| `exec_success` | True | True |
| `repair_count` | 0 | 0 |
| `_provider_calls` | **2** | **2** |
| `latency_ms` | 10900.76 | 10519.64 |
| `_wall_ms` | 10940.46 | 10523.94 |
| schema_link 选表 | `["users","orders"]` | `["users","orders"]` |
| few-shot 命中 | `["ex_010","ex_016","ex_007"]` | — |

**OFF 生成的 SQL**（缺陷复现）：
```sql
FROM (SELECT u.id, COUNT(o.id) AS order_count
      FROM users u LEFT JOIN orders o ON o.user_id = u.id
      GROUP BY u.id) AS user_orders
```

**ON 生成的 SQL**（口径修正）：
```sql
FROM (SELECT user_id, COUNT(*) AS order_count
      FROM orders GROUP BY user_id) AS user_orders
```

逐条对上第一阶段判据：

| 判据 | 结果 |
|---|---|
| 1. E-0057 EX ✗→✓ | ✔ `False → True` |
| 2. ON 真正采用正确统计实体 | ✔ `driver_table=orders`、`grain=user_id`、无 `LEFT JOIN`、零单用户排除 |
| 3. Exec 保持成功 | ✔ `True → True` |
| 4. **provider call 增量 = 0** | ✔ **2 → 2** |
| 5. 新增本地延迟 | ✔ −381 ms（属正常抖动，非约束成本；约束是纯字符串拼接） |
| 6. 新 SQL/Agent 错误 | ✔ 无 |

**Schema Linking 输出两臂完全相同**（都是 `["users","orders"]`）——修正发生在**生成阶段的口径选择**，不是选表。这与"统计实体约束"的定位一致。

### 4.3 第二阶段：冻结 100 题正式回归（真实 Mimo）

ON 臂：`SQLGEN_EXTRA_RULES=E8`，其余全部与 Clean Baseline 一致。

| 指标 | OFF（冻结基线） | ON（E8） | Δ |
|---|---:|---:|---:|
| Total | 100 | 100 | — |
| Valid Model Runs | 100 | 100 | — |
| **Overall EX** | **90.0%** | **93.0%** | **+3.0pp** |
| Conditional EX | 90.0% | 93.0% | +3.0pp |
| Pass@1（初始） | 90.0% | 93.0% | +3.0pp |
| **Exec Rate** | **99.0%** | **100.0%** | **+1.0pp** |
| Repair Trigger Rate | 0.0% | 0.0% | 0 |
| **Provider Failures** | **0** | **0** | **0** |
| Timeouts | 0 | 0 | 0 |
| Avg Latency | 10876.08 ms | 7296.5 ms | −3579.58 |
| P50 | 10488.92 ms | 6348.87 ms | −4140.05 |
| P95 | 15440.79 ms | 14280.91 ms | −1159.88 |
| 总耗时 | — | 730.8s | — |
| Bad Cases | 10 | 7 | −3 |
| **regressions** | — | — | **0** |

ON 臂失败类型分布：`none 93 / result_mismatch 7`（全部 `failure_stage=result`，即纯语义错，无一例执行期或 provider 期失败）。

**延迟下降不作因果声明。** −3579 ms 主要来自 provider 端负载波动（本项目已多次观测到同一配置跨轮 latency 大幅漂移）；E8 是纯字符串拼接，**不可能**带来秒级收益。此处只记录数值，不归因。

### 4.3.1 同构题普查：E-0057 是唯一"模型自己多引入一张表"的题

首版报告只验证了 E-0057 一题。补做零 LLM 的 100 题结构普查后发现：**"按 X 分档、各档有多少 Y" 这个结构在 Benchmark 里有 3 道题**。

| 题 | 分档对象 | gold 引用表 | gold 表数 | E8 触发 | 基线 EX |
|---|---|---|---|---|---|
| `E-0029` | 商品售价四档 | `products` | 1 | False | **True** |
| `E-0044` | 订单金额三档 | `orders` | 1 | False | **True** |
| `E-0057` | 用户下单次数三档 | `orders` | 1 | **True** | False |

**关键发现：三题的 gold 全部只引用一张表。**

> E-0057 的正确答案**只需要 `orders`**——`SELECT ... FROM orders GROUP BY user_id` 就够了。是**模型自己的 pred 多引入了一张 `users`**（`users LEFT JOIN orders`），才捅出这个洞。

这修正了一个容易搞错的表述：**E8 的作用不是"帮模型补一张缺的表"，而是"阻止模型多拉一张表"。** 约束文本里那句「禁止用 `users LEFT JOIN orders` 作为驱动集合」正是这个意思——它不是提示模型"你漏了表"，而是说"你多带了表"。

这也解释了触发域为什么"恰好只有 1/100"：**E-0029 / E-0044 的统计对象与数据源同表（商品的价格就在 `products` 里、订单金额就在 `orders` 里），模型没有理由去 JOIN 第二张表，歧义空间为零。** 只有 E-0057 这种"统计实体（用户）× 行为记录（订单）"的题，才存在"我该从 `orders` 出发还是从 `users` 出发"的真实选择。

### 4.3.2 驱动结构级验证（补做——首版遗漏）

首版只对比了最终结果集，**没有验证驱动结构**。补做 2×2 全交叉（零 LLM，直接对数据库跑）：

| 驱动结构 | `CASE` 写法 | 结果 | EX | 备注 |
|---|---|---|---|---|
| **A** `users LEFT JOIN orders`（基线） | `ELSE '11单及以上'` | `{490, 1474, **36**}` | ❌ | 基线缺陷 |
| **A** `users LEFT JOIN orders` | `WHEN order_count >= 11` | `{490, 1474, **19**}` | ⚠️ **True（假阳性）** | **17 个零单用户落 NULL 档被丢** |
| **B** `FROM orders GROUP BY user_id` | `ELSE` | `{490, 1474, 19}` | ✅ | 口径正确 |
| **B** `FROM orders GROUP BY user_id` | `WHEN >= 11` | `{490, 1474, 19}` | ✅ | 口径正确 |

实测确认：`A + w2` 判定 `>=11` 得 **19**（真值 19），落 NULL 档被丢弃 **17**（全是零单用户）。

> **这是一个必须记录的假阳性修复通道**：把 `CASE` 的兜底 `ELSE` 换成显式 `WHEN cnt >= 11`，零单用户会落进隐式 NULL 档、被 `GROUP BY` 剔除，**结果碰巧等于真值**。但统计口径**依然是错的**——它数的是"全部 2000 个用户里 `>=11` 的"，不是"下单用户里 `>=11` 的"。两者在当前数据上恰好重合，所以答案对；换个数据分布（哪怕只多一个下满 11 单的用户）就会露馅。

**E-0057 实际走的是哪条路？** 实测两次运行：

| 运行 | 驱动表 | `CASE` 尾部写法 | 判定 |
|---|---|---|---|
| Phase 1 单例 ON | `FROM orders GROUP BY user_id` ✅ | `ELSE '11单及以上'` | **B + w1，真修好** |
| Phase 2 ON | `FROM orders GROUP BY user_id` ✅ | `WHEN order_count >= 11` | **B + w2，真修好** |

两次**驱动表都修正到了 `orders`**，属于口径正确那一格。`CASE` 写法的差异（`ELSE` → `WHEN >= 11`）是 E8 附带引入的**额外扰动**，不影响正确性（`B+w1` 与 `B+w2` 均 EX=True），但说明 **E8 的作用不是精确的"只改驱动表"，它同时扰动了 `CASE` 的措辞**。

**结论（对首版结论的加强，非推翻）**：E8 在 E-0057 上确实实现了驱动表级的口径修正，不是靠 `CASE` 侥幸字母。但审计揭示了一条**独立的假阳性通道**存在——若未来某次运行模型只采纳了 `CASE` 改动而没采纳驱动表改动，EX 会显示 ✓ 而口径仍然错误。**因此"E-0057 EX=True"这一信号本身不足以证明口径正确，必须同时检查驱动表。** 本报告已对两次运行逐一做了该检查。

### 4.4 归因审计（本任务最重要的诚实性检查）

逐题 diff 显示 3 题翻转（`E-0057`/`E-0099`/`E-0100`）、0 回归。3 题一起翻，看着像 E8 战绩——但 E8 只在 E-0057 触发。审计结果：

```
E8 触发题目（100 题全量扫描）: ['E-0057']
UNCHANGED_FAIL -> PASS: ['E-0057', 'E-0099', 'E-0100']
PASS -> FAIL regressions: []

可由 E8 解释（触发 & 修复）: ['E-0057']
不可由 E8 解释（未触发 & 修复）: ['E-0099', 'E-0100']
  E-0099: base_err='SQL 执行失败: no such column: r.region'  on_err=None  pred_changed=True
  E-0100: base_err='result_mismatch'                          on_err=None  pred_changed=True
```

| 题 | E8 触发 | 翻转 | 归因 |
|---|---|---|---|
| **E-0057** | **True** | ✗→✓ | ✅ **可归因 E8**。触发域与修复集重合；两次运行均实测驱动表由 `users LEFT JOIN orders` 修正为 `FROM orders GROUP BY user_id`（口径级变化，非 `CASE` 侥幸） |
| E-0099 | False | ✗→✓ | ❌ **不可归因**。`no such column: r.region` 是 Task 37 的 Scope 校验器所在的缺陷类；基线失败是执行期报错，本次运行直接产出了合法 SQL ⇒ 属**跨轮生成波动 / 工作树其他变更** |
| E-0100 | False | ✗→✓ | ❌ **不可归因**。pred 变化为 `oi.subtotal → total_amount`（金额口径切换）与 `o.order_date → order_date`（去别名），**与统计实体约束无关** ⇒ **LLM 采样波动** |

补充说明 E-0029：该题两臂 `pred` 有差异（`..., GROUP BY price_range ORDER BY price_range` → 去掉 `ORDER BY`），EX 均为 `True`（归一化后结果集相同）。与 E8 无关（E8 不触发此题），同属**采样抖动**。E-0044 两臂 `pred` 完全一致。

**因此：**

> **Overall EX +3.0pp 中，只有 1/3（E-0057）能归因于 E8。另 2 题的翻转发生在 E8 不触发的题目上，本任务不得将其记为约束的收益。**
>
> E8 的**可归因收益**是：`E-0057` 单题 ✗→✓，**+1.0pp**（90.0% → 91.0%），代价 0 次额外 LLM 调用、0 处回归。

这个区分不是吹毛求疵。E-0100 的 `oi.subtotal → total_amount` 是**金额口径漂移**——如果把它算成 E8 的功劳，下一轮它完全可能自己漂回去，那时"约束失效"的结论就是错的。**低样本量下的 +3.0pp 必须拆开看，否则归因就是自欺。**

### 4.5 成功判据核对

| # | 判据（用户原文） | 结果 | 说明 |
|---|---|---|---|
| 1 | E-0057 EX 从 FAIL → PASS | ✅ | 单例 + 100 题两轮均实测 `False → True` |
| 2 | 非 E-0057 不出现新增回归 | ✅ | regressions = `[]`（判据字面成立） |
| 3 | Exec 不下降 | ✅ | 99.0% → 100.0% |
| 4 | provider call 增量 = 0 | ✅ | 单例 2→2；机制上约束为纯本地字符串处理 |
| 5 | 约束仅在目标场景触发，不影响"包含 0 单用户"的题 | ✅ | 触发域 **1/100＝仅 E-0057**；E-0036（合法 LEFT JOIN，需保留零活动实体）未触发 |

**5/5 通过。**

---

## 5. 变更边界合规性

| 允许范围 | 实际改动 |
|---|---|
| SQL 生成前的统计实体 / 驱动表约束 | ✅ `app/sqlgen/entity_constraint.py`（新增 173 行）+ `app/sqlgen/prompt.py`（+30 / −0） |
| 直接相关测试 | ✅ `backend/tests/test_task38_entity_constraint.py`（20 tests） |

| 禁止项 | 是否触碰 |
|---|---|
| Benchmark Gold / Question | ❌ 未触碰 |
| 评测 normalization / metrics | ❌ 未触碰 |
| Schema Linking | ❌ 未触碰（两臂 `tables` 输出完全相同） |
| Few-shot 数据集 / Retriever | ❌ 未触碰（`ex_016` 原样保留） |
| Repair Prompt / Validator | ❌ 未触碰 |
| **SQL Scope Validator（Task 37）** | ❌ 未触碰 |
| Database / Provider / Model / API Key | ❌ 未触碰 |
| latency 配置 / 其他 Prompt 规则 | ❌ 未触碰 |
| 顺带优化 E-0090 / E-0095 / E-0077 | ❌ 未做 |

`git diff --stat HEAD` 对 Task 38 的净变更：

```
 backend/app/sqlgen/prompt.py | 30 ++++++++++++++++++++++++++++++
 1 file changed, 30 insertions(+)
```

**+30 / −0，纯新增。** 加上一个全新模块和一个全新测试文件，无任何既有行被修改。

---

## 6. 交付物

| 文件 | sha256 |
|---|---|
| `backend/app/sqlgen/entity_constraint.py`（新增，173 行） | `bb691a95c54a3bdc6289bfb52532bf995b12d19b87ac369b93a1cca5b6749d63` |
| `backend/app/sqlgen/prompt.py`（+30 / −0） | `193d37cd08e893bc7626ffa250a6360677cf1d7d1dae14f3a9148e0622ee22ad` |
| `backend/tests/test_task38_entity_constraint.py`（20 tests） | `9ce9d544b0707ca1550e640390a648990468650343b933da21a0f777adeac46a` |
| `scripts/task38_trigger_check.py` | `30e8228b850e240b645a5cdbd33584e8a8f8a84e855771028ce1c02970319849` |
| `scripts/task38_phase1_off_on.py` | `e4a6c7f8b7361c66614f9d1875f86a11080ea17a8fa2a114fe360d967f644101` |
| `scripts/task38_phase2_compare.py` | `dbfb50af4390452c96cf9596d4489529370f4c14533915c723f897b419ac0b6e` |
| `reports/eval/task38_phase1/e0057_off_on.json` | 首轮（含作废的 OFF 臂） |
| `reports/eval/task38_phase1/e0057_off_rerun.json` | OFF 有效重跑 |
| `reports/eval/task38_phase2_on/eval_20260920_34113.json` / `.md` | ON 臂 100 题 |
| `reports/eval/task38_phase2/compare.json` | OFF/ON 对比 + gate |

测试：**490 passed / 0 failed**（Task 37 后为 470，+20 = Task 38 新增）。
> 注：从 `backend/` 目录直接执行 pytest 会有 1 个既有失败（`test_eval_runner.py::test_gold_hash_gate_passes_on_real_dataset`，因相对路径 `data/eval/ecommerce_eval_v1.json` 在 `backend/` 下不存在）。**从仓库根目录执行 490 全通过**，与 Task 38 无关。

---

## 7. 结论

1. **约束有效，但收益是 1 题、+1.0pp，不是 3 题、+3.0pp。** E-0057 `result_mismatch` → EX ✓；E-0099 / E-0100 的翻转发生在 E8 不触发的题目上，是跨轮 LLM 波动 + 工作树其他变更，**不得记为 E8 收益**。

2. **缺陷的本质是口径，不是语法。** 17 个零单用户全落最高档，整体计数从 1983 虚增到 2000。执行期任何机制都拦不住它——SQL 语法合法、执行成功、`exec_success=True`。**这正好和 Task 37 形成互补**：Task 37 治"跑不起来"（`no such column`），Task 38 治"跑得起来但答非所问"。

3. **判别器必须是 `include_zero_activity_entities` 而非 JOIN 类型。** E-0036 与 E-0057 结构相同（都是 LEFT JOIN）、语义相反。任何"禁用 LEFT JOIN"的规则都会同时打死 E-0036。

4. **条件性生效的实现方式是必要条件，不是美化。** 触发域锁死在 1/100；OFF 分支 Prompt 与冻结基线逐字节一致（100/100 验证）。若改成全局规则，触发域不可控，单变量对照也无从建立。

5. **成本为零。** provider call 增量 0（机制上：约束是 `question -> str` 的纯函数，无 I/O、无 LLM、无新 Node），本地延迟增量 ≈ 0（−381 ms 属抖动）。Prompt 长度 +484 字符。

6. **⚠️ 但 EX ✓ 不等价于口径正确（补做审计的核心发现）。** 驱动结构级 2×2 交叉验证（§4.3.2）证明存在一条**假阳性通道**：错误的 `users LEFT JOIN orders` 只要把 `CASE` 兜底换成显式 `WHEN cnt >= 11`，零单用户就会落 NULL 档被丢弃，结果**碰巧**等于真值。本次两次运行实测都走了正确路径（驱动表均为 `orders`），结论成立；但**任何后续验证都不能只看 EX，必须检查驱动表**。

7. **E-0057 是"统计实体 × 行为记录"这一类里唯一的样本。** 100 题中另有 E-0029 / E-0044 两道同构分档题，但它们的**统计对象与数据源同表**（价格在 `products` 里、金额在 `orders` 里），模型没有理由 JOIN 第二张表，歧义空间为零，基线本来就对。**E8 的适用面是"存在锚点表 vs 行为表选择"的一类题，不是"所有分档题"。**
   另需注意一个易错表述：E-0057 的 **gold 只引用 1 张表（`orders`）**——正确答案并不需要 `users`。**E8 的作用是阻止模型多拉一张表，不是帮它补一张缺的表。** 这与"schema linking 漏表"是完全相反方向的问题。

### 7.1 遗留与后续建议

- **`SQLGEN_EXTRA_RULES=E8` 默认关闭。** 本次实验**未改变生产默认行为**，需人工决策是否转正。
- **未做泛化验证。** 该约束在 Benchmark 内只有 1 个正样本（见 §4.3.1，E-0029/E-0044 虽同构但不跨表、天然不触发），无法判断它在"按行为分档统计分类/商品"等**跨表变体**上是否同样有效。若后续要转正，需要一个**独立撰写的 holdout**（参考 Task 31 的教训：implementation-aware holdout 的 100% ≠ 泛化能力）。
- **⚠️ 存在假阳性修复通道（见 §4.3.2）**：`错误驱动 + 显式 WHEN 下界` 会让零单用户落 NULL 档被丢弃，EX 显示 ✓ 而口径仍错。后续任何基于 E8 的验证**不能只看 EX**，必须同时检查驱动表是否为行为表。这是本任务最值得带走的一条警告。
- **E8 的作用不精确**：两次运行均正确修正了驱动表，但 `CASE` 写法出现 `ELSE` / `WHEN >= 11` 两种输出，说明约束在修正口径的同时也对 `CASE` 措辞引入了扰动。若未来要收紧，可考虑在约束文本中显式规定 `CASE` 的分支写法，减少不必要自由度。
- **关联遗留（Task 37 已披露，未修）**：`sqlrepair/validator.py::_check_spelled_columns` 会把 CTE 别名当真实表名去 `catalog.has_column` 查，导致**任何带 CTE 别名的 SQL 被 Repair 拒绝**。与 Task 38 无关。

---

**实验结束。** 按用户指令停止，不进入下一项优化。
