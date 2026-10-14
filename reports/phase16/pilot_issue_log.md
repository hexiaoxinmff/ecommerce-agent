# Phase 16 Pilot 问题池（pilot_issue_log）

> 登记规则：试点期间每个问题一条，先观察不抢修；同一问题**连续出现 ≥3 次**才进入候选产品问题。
> 试点期修复策略见 `pilot_plan.md` §9（只允许小修复）；大动作一律 Status = deferred。
> Severity：**P0** = 可能造成错误业务决策；**P1** = 明显影响使用；**P2** = 体验问题；**P3** = 优化项。
>
> Category ∈ technical / schema_error / business_semantic / user_intent_ambiguity / concept_not_exists / other
> Status ∈ observing / candidate / fixing / fixed / deferred / wontfix

字段：Issue ID、Date、User、Original Question、Observed Behavior、Expected Behavior、
Category、Severity、Reproducible、Frequency、User Impact、Proposed Action、Status。

---

## 预登记问题（Phase 15 已知，试点期观察真实发生率，不预先修复）

### ISSUE-PRE-001（= 观察项 A：Unsupported Concept）

- **Date**: 2026-10-02（Phase 15 陷阱题实测日；试点期待真实用户复现）
- **User**: 评测脚本 → 待真实用户
- **Original Question**: 有多少 VIP 用户？
- **Observed Behavior**: 静默答 1707（实为 active 用户数），不声明概念不存在，不解释换算
- **Expected Behavior**: 声明库中无「VIP」概念，说明最接近的可用概念（如活跃用户），或引导用户澄清
- **Category**: concept_not_exists
- **Severity**: P1（若试点中真实用户因此做出错误业务决策 → 升 P0）
- **Reproducible**: yes（Phase 15 实测）
- **Frequency**: 待试点统计
- **User Impact**: 用户可能把「活跃用户」当「VIP 用户」做运营决策
- **Proposed Action**: 试点结束按真实样本设计 Unsupported / Ambiguous Intent Policy（不预先设计拒答规则）
- **Status**: observing

### ISSUE-PRE-002（= 观察项 B：Ambiguous Time）

- **Date**: 2026-10-02（Phase 15 陷阱题实测日）
- **User**: 评测脚本 → 待真实用户
- **Original Question**: 最近卖得怎么样？
- **Observed Behavior**: 静默自选 30 天窗口且不声明「最近」被解释成了什么
- **Expected Behavior**: 明示自选时间范围（如「按最近 30 天（数据截至 2026-09-12）统计」），或反问澄清
- **Category**: user_intent_ambiguity（**注意：此类不直接算 Agent 错误**，需区分用户未给出明确条件）
- **Severity**: P2（取决于用户是否接受 Agent 的解释，试点期升级/降级）
- **Reproducible**: yes（Phase 15 实测）
- **Frequency**: 待试点统计
- **User Impact**: 用户可能在不知情下拿了非预期时间窗的数字
- **Proposed Action**: 观察「Agent 自选 + 明示」与「用户需要补充」两种情况的真实接受度，期末决策
- **Status**: observing

### ISSUE-PRE-003（不可回答问题：响亮失败但文案技术性不可读）

- **Date**: 2026-10-02（Phase 15 实测）
- **User**: 评测脚本 → 待真实用户
- **Original Question**: 退款金额一共有多少？
- **Observed Behavior**: 从「编造 0 元」进步为响亮失败（success=false），但报错文案为技术性内容
  （「tables 出现 Schema Linking 未提供的表」），业务用户不可读
- **Expected Behavior**: 业务可读的边界说明（库中无退款数据/概念）
- **Category**: technical（文案可读性）
- **Severity**: P1
- **Reproducible**: yes（Phase 15 实测）
- **Frequency**: 待试点统计
- **User Impact**: 用户看到技术报错会失去信任，尽管系统行为本身是对的
- **Proposed Action**: 若试点期复现 → 对应 Phase 15 P1-2「错误文案中文化」，按 §9 小修复通道处理
- **Status**: observing

---

## 试点期新增问题（逐条添加）

| Issue ID | Date | User | Original Question | Observed Behavior | Expected Behavior | Category | Severity | Reproducible | Frequency | User Impact | Proposed Action | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
