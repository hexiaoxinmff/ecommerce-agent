/**
 * 静态 Demo 数据（阶段 3-任务 1）
 *
 * 重要：以下全部为静态演示数据，用于验证 UI/UX v1.0 视觉与交互。
 * 未接入后端、未接入 Mimo API、未连接 SQLite 真实查询。
 * 接入真实数据后应删除本文件或替换为接口请求。
 */

/** 首页 KPI（演示数据） */
export const kpiData = [
  { id: "sales", label: "本月销售额", value: "¥7,662,921", unit: "元", trend: "+12.4%", up: true },
  { id: "orders", label: "订单量", value: "1,284", unit: "单", trend: "+8.1%", up: true },
  { id: "users", label: "用户数", value: "2,000", unit: "人", trend: "+3.2%", up: true },
  { id: "arpu", label: "客单价", value: "¥352.6", unit: "元/单", trend: "-1.8%", up: false },
];

/** 销售趋势（演示数据，单位：万元） */
export const salesTrend = {
  months: ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
  values: [612, 645, 623, 689, 701, 668, 712, 698, 745, 731, 758, 766],
};

/** 分类销售（演示数据，单位：万元） */
export const categorySales = [
  { name: "家用电器", value: 218 },
  { name: "电脑办公", value: 186 },
  { name: "手机通讯", value: 172 },
  { name: "家具", value: 124 },
  { name: "运动装备", value: 98 },
];

/** Top 商品（演示数据） */
export const topProducts = [
  { rank: 1, name: "星耀 AI 智能音箱 Pro", sales: 486, amount: "¥164,340" },
  { rank: 2, name: "极光 4K 智能电视 65 英寸", sales: 342, amount: "¥402,960" },
  { rank: 3, name: "轻云笔记本电脑 14 英寸", sales: 318, amount: "¥529,470" },
  { rank: 4, name: "灵犀无线降噪耳机", sales: 296, amount: "¥93,240" },
  { rank: 5, name: "远航智能手表 S8", sales: 274, amount: "¥141,100" },
];

/** 数据库状态（真实开发库规模，来源于 database-schema.md） */
export const dbStatus = {
  file: "ecommerce.db",
  type: "SQLite",
  connected: true,
  stats: [
    { label: "表", value: "5" },
    { label: "用户", value: "2,000" },
    { label: "分类", value: "30" },
    { label: "商品", value: "500" },
    { label: "订单", value: "10,000" },
    { label: "订单明细", value: "30,457" },
  ],
};

/** 示例问题（与 PRD 场景一致） */
export const exampleQuestions = [
  "本月销售额是多少？",
  "哪个商品销量最高？",
  "华东地区注册用户有多少？",
  "各省份订单量分别有多少？",
  "2025 年每月销售额趋势？",
  "销售额 Top 10 的商品是哪些？",
];

/** Agent 7 阶段（最小 Text2SQL 基线链，与 UI-UX v1.0 一致） */
export const agentStages = [
  "问题理解",
  "Schema 匹配",
  "Few-shot",
  "SQL 生成",
  "SQL 校验",
  "SQL 执行",
  "结果生成",
];

/** 演示分析结果（点击「开始分析」后的模拟结果） */
export const demoResult = {
  question: "本月销售额是多少？",
  value: "¥7,662,921",
  unit: "元",
  note: "Demo 模式：暂未连接后端，结果为静态演示数据",
};

/** 汇报模式下的侧边核心图表（演示数据） */
export const presentationChart = {
  months: ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
  values: [668, 712, 698, 745, 731, 758, 766],
};

/* =========================================================
   智能分析页 Demo 数据（阶段 3-任务 2）
   全部为静态演示数据，未连接后端 / Mimo / SQLite / LangGraph
   ========================================================= */

/** 智能分析页示例问题（项目真实场景） */
export const analysisExamples = [
  "本月销售额是多少？",
  "最近三个月销售额趋势如何？",
  "销售额最高的 5 个商品是什么？",
  "哪个商品类别销售额最高？",
  "各地区订单量分别是多少？",
];

/** 智能分析页 Demo SQL（仅展示文本，非真实后端生成） */
export const analysisSql = `SELECT
    SUM(total_amount) AS sales
FROM orders
WHERE strftime('%Y-%m', order_date) = '2026-09'
  AND status != 'cancelled';`;

/** 各阶段详情（Demo 模拟真实 Agent 输出） */
export const stageDetails = {
  understanding: {
    intent: "查询销售额",
    period: "2026-09",
    metric: "销售额",
    filter: "排除取消订单",
  },
  schema: {
    tables: ["orders", "order_items"],
    fields: ["orders.total_amount", "orders.order_date", "orders.status"],
  },
  fewshot: {
    count: 2,
    scenarios: ["月度销售额查询", "时间范围销售统计"],
  },
  validation: [
    { name: "语法检查", ok: true },
    { name: "只读检查", ok: true },
    { name: "危险操作检查", ok: true },
  ],
  execution: {
    engine: "SQLite",
    status: "执行完成",
    cost: "128 ms",
    rows: "1 row",
  },
};

/** 错误状态 Demo：SQL 校验失败 */
export const validationError = {
  title: "SQL 校验未通过",
  reason: "查询包含不允许的写操作",
};

/** Agent Trace 时间线（Demo 模拟） */
export const analysisTrace = [
  { time: "17:26:01", text: "问题解析完成" },
  { time: "17:26:02", text: "Schema 匹配完成" },
  { time: "17:26:02", text: "Few-shot 检索完成" },
  { time: "17:26:03", text: "SQL 生成完成" },
  { time: "17:26:03", text: "SQL 校验通过" },
  { time: "17:26:03", text: "SQL 执行完成" },
  { time: "17:26:04", text: "结果生成完成" },
];

/** 分析结果（Demo） */
export const analysisResult = {
  value: "¥7,662,921",
  label: "2026 年 9 月实际销售额",
  trend: "+12.4%",
  up: true,
  orders: "1,284",
  arpu: "¥352.6",
};

