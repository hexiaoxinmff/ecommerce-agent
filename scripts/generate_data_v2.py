"""第二公司（B 公司）演示数据生成器（纯数据生成，不直接写数据库文件）。

Phase 13 跨数据库迁移验证专用。与 A 库（scripts/generate_data.py）的关系：
- 不是复制改名：表名 / 字段名 / 表关系 / 业务枚举 / 数据规模 / 时间范围全部不同；
- 固定随机种子（20260928），每次运行生成完全一致的数据；
- 不依赖外部网络，不依赖 LLM；不读写任何数据库文件。

B 公司业务设定：连锁零售会员制门店。
金额口径：
- order_lines.line_total = deal_price × qty（明细行金额）；
- sales_orders.payment_due = 明细合计 − 优惠券抵扣 + 配送费（应付金额）；
- 作废订单（order_state = 'voided'）抵扣 / 配送费 / 应付全为 0（明细保留）；
- deal_price 是成交单价快照（约 15% 明细低于吊牌价 list_price），与 A 库
  unit_price 恒等于标价不同。
"""

import random
from datetime import date, timedelta

# 固定随机种子（保证每次重新生成可复现）
SEED = 20260928

# 订单时间范围（B 是新公司，仅有近一年数据，与 A 库 2024-01 起步不同）
DATE_START = date(2025, 10, 1)
DATE_END = date(2026, 9, 20)
JOIN_START = date(2025, 8, 1)
JOIN_END = date(2026, 8, 31)

# 数据规模目标（与 A 库数量级不同：更小的公司）
TARGET_MEMBERS = 1_200
TARGET_ORDERS = 6_000
TARGET_ITEMS = 150

# 城市（城市粒度，与 A 库省级粒度不同；订单表无城市列，需 JOIN members）
CITIES = [
    "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安", "重庆",
    "长沙", "郑州", "青岛", "沈阳", "苏州", "宁波", "合肥",
]
CITY_WEIGHTS = [0.14, 0.11, 0.09, 0.08, 0.07, 0.07, 0.07, 0.07,
                0.06, 0.06, 0.05, 0.05, 0.04, 0.02, 0.02]

# 常见中文姓与名（生成会员姓名，保证唯一）
SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "吴", "周",
    "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗",
    "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹",
]
GIVEN_NAMES = [
    "伟", "芳", "娜", "敏", "静", "磊", "军", "洋", "勇", "艳",
    "杰", "娟", "涛", "明", "超", "秀兰", "霞", "平", "刚", "桂英",
    "文", "辉", "建华", "志强", "子轩", "雨桐", "浩然", "欣怡", "梓涵", "语嫣",
    "晨曦", "若彤", "亦辰", "悦然", "慕晴", "书瑶", "泓毅", "灿", "锐", "蔓",
]

# 会员等级与状态（A 库没有等级维度；状态用整数 is_active 而非文本）
TIERS = ["gold", "silver", "bronze"]
TIER_WEIGHTS = [0.15, 0.30, 0.55]
ACTIVE_WEIGHTS = [0.87, 0.13]  # [1, 0]

# 订单状态（作废叫 voided；与 A 库 cancelled 命名与含义不同）
ORDER_STATES = ["completed", "shipped", "paid", "pending", "voided"]
ORDER_STATE_WEIGHTS = [0.60, 0.15, 0.10, 0.11, 0.04]

# 每个订单的明细行数（1~4 行，与 A 库 1~5 不同）
LINE_COUNT_CHOICES = [1, 2, 3, 4]
LINE_COUNT_WEIGHTS = [0.15, 0.35, 0.30, 0.20]

# 单行购买数量（1~5 件）
QTY_CHOICES = [1, 2, 3, 4, 5]
QTY_WEIGHTS = [0.58, 0.26, 0.10, 0.04, 0.02]

# 成交价快照：约 15% 明细按 9 折成交（A 库成交价恒等于标价）
DEAL_DISCOUNT_PROBABILITY = 0.15
DEAL_DISCOUNT_RATE = 0.90

# 优惠券抵扣（约 25% 订单享受，按明细合计比例抵扣）
COUPON_RATES = [0.03, 0.05, 0.08, 0.10, 0.15]
COUPON_PROBABILITY = 0.25

# 配送费（大额订单免配送费）
DELIVERY_FEES = [5.0, 8.0, 10.0]
FREE_DELIVERY_THRESHOLD = 299.0
FREE_DELIVERY_PROBABILITY = 0.35

# 品牌（快消零售品牌，与 A 库数码家电品牌完全不同）
BRANDS = [
    "金龙鱼", "鲁花", "海天", "伊利", "蒙牛", "农夫山泉", "元气森林",
    "康师傅", "统一", "娃哈哈", "立白", "蓝月亮", "舒肤佳", "潘婷",
    "多芬", "维达", "清风", "心相印", "百草味", "三只松鼠", "良品铺子",
    "旺旺", "奥利奥", "乐事", "雀巢", "德芙", "青岛啤酒", "乌苏",
    "洽洽", "喜之郎",
]
SPEC_SUFFIXES = ["家庭装", "便携装", "经典款", "尊享款", "礼盒装", "量贩装"]

# 类目体系：6 个单层类目 × 5 个商品模板 × 5 个商品（关系差异：A 库两级层级）
# (商品通用名, 最低吊牌价, 最高吊牌价)
CATALOG = {
    "生鲜食品": [
        ("有机蔬菜", 5, 30), ("新鲜水果", 8, 60), ("冷鲜猪肉", 15, 80),
        ("冷鲜牛肉", 30, 150), ("鲜鸡蛋", 8, 25),
    ],
    "粮油调味": [
        ("长粒香大米", 20, 120), ("食用植物调和油", 40, 180), ("高筋面粉", 10, 60),
        ("生抽酱油", 6, 40), ("酿造食醋", 5, 30),
    ],
    "酒水饮料": [
        ("饮用天然水", 2, 10), ("碳酸饮料", 3, 15), ("复合果汁", 5, 25),
        ("精酿啤酒", 4, 20), ("浓香型白酒", 50, 800),
    ],
    "个护美妆": [
        ("洗发露", 25, 120), ("沐浴乳", 20, 90), ("滋润面霜", 60, 400),
        ("含氟牙膏", 8, 40), ("香皂", 4, 25),
    ],
    "家居清洁": [
        ("洗衣液", 20, 80), ("抽纸", 10, 50), ("垃圾袋", 5, 25),
        ("洗洁精", 8, 35), ("消毒液", 10, 45),
    ],
    "休闲零食": [
        ("每日坚果", 15, 90), ("曲奇饼干", 6, 40), ("原味薯片", 5, 25),
        ("水果硬糖", 8, 45), ("风干牛肉干", 15, 80),
    ],
}


def _round2(value: float) -> float:
    return round(value, 2)


def gen_departments(rng: random.Random) -> list[dict]:
    """生成 6 个单层类目（无 parent_id，与 A 库两级层级不同）。"""
    return [
        {"id": idx + 1, "dept_name": name}
        for idx, name in enumerate(CATALOG)
    ]


def gen_items(rng: random.Random, departments: list[dict]) -> list[dict]:
    """生成 150 个商品：6 类目 × 5 模板 × 5 商品，名称唯一。"""
    dept_ids = {d["dept_name"]: d["id"] for d in departments}
    templates = []
    for dept_name, tpls in CATALOG.items():
        for generic, lo, hi in tpls:
            templates.append((dept_ids[dept_name], generic, lo, hi))

    items = []
    used_names = set()
    for dept_id, generic, lo, hi in templates:
        for _ in range(5):
            brand = rng.choice(BRANDS)
            spec = rng.choice(SPEC_SUFFIXES)
            name = f"{brand}{generic}{spec}"
            attempt = 1
            while name in used_names:
                attempt += 1
                name = f"{brand}{generic}{spec}{attempt}号"
            used_names.add(name)
            items.append({
                "id": len(items) + 1,
                "item_title": name,
                "dept_id": dept_id,
                "list_price": _round2(rng.uniform(lo, hi)),
                "availability": (
                    "in_stock" if rng.random() < 0.93 else "discontinued"
                ),
            })
    return items


def gen_members(rng: random.Random) -> list[dict]:
    """生成约 1200 个会员：唯一姓名 / 编码、城市、入会日期、等级、状态。"""
    name_pool = list(dict.fromkeys(s + g for s in SURNAMES for g in GIVEN_NAMES))
    assert len(name_pool) >= TARGET_MEMBERS, "姓名组合池不足，无法生成足够唯一会员名"
    names = rng.sample(name_pool, TARGET_MEMBERS)
    join_days = (JOIN_END - JOIN_START).days

    members = []
    for i, member_name in enumerate(names):
        join_offset = rng.randint(0, join_days)
        members.append({
            "id": i + 1,
            "member_code": f"M{i + 1:06d}",
            "member_name": member_name,
            "city": rng.choices(CITIES, weights=CITY_WEIGHTS, k=1)[0],
            "joined_on": (JOIN_START + timedelta(days=join_offset)).isoformat(),
            "tier": rng.choices(TIERS, weights=TIER_WEIGHTS, k=1)[0],
            "is_active": 1 if rng.choices([1, 0], weights=ACTIVE_WEIGHTS, k=1)[0] else 0,
        })
    return members


def gen_orders_and_lines(
    rng: random.Random,
    members: list[dict],
    items: list[dict],
) -> tuple[list[dict], list[dict]]:
    """生成订单与订单明细。

    金额口径（与 A 库同构但字段名不同）：
    - order_lines.line_total = deal_price × qty；
    - sales_orders.payment_due = 明细合计 − coupon_deduction + delivery_charge；
    - 作废订单（voided）抵扣 / 配送费 / 应付全为 0（明细保留，与 A 库取消订单一致）。
    """
    total_days = (DATE_END - DATE_START).days
    n_items = len(items)

    orders: list[dict] = []
    lines: list[dict] = []
    line_id = 0
    for order_idx in range(TARGET_ORDERS):
        member = rng.choice(members)
        member_id = member["id"]

        # 下单时间：整体偏向近期（幂次变换），且不早于入会时间
        t = rng.random() ** 0.85
        order_day = DATE_START + timedelta(days=int(t * total_days))
        join_day = date.fromisoformat(member["joined_on"])
        if order_day < join_day:
            clamp = min((join_day + timedelta(days=rng.randint(0, 30))), DATE_END)
            order_day = clamp

        order_state = rng.choices(
            ORDER_STATES, weights=ORDER_STATE_WEIGHTS, k=1
        )[0]
        order_id = order_idx + 1

        n_lines = rng.choices(LINE_COUNT_CHOICES, weights=LINE_COUNT_WEIGHTS, k=1)[0]
        chosen = rng.sample(range(n_items), k=n_lines)
        lines_sum = 0.0
        for item_idx in chosen:
            item = items[item_idx]
            qty = rng.choices(QTY_CHOICES, weights=QTY_WEIGHTS, k=1)[0]
            # 成交价快照：约 15% 明细按 9 折成交（区别于 A 库恒等标价）
            if rng.random() < DEAL_DISCOUNT_PROBABILITY:
                deal_price = _round2(item["list_price"] * DEAL_DISCOUNT_RATE)
            else:
                deal_price = item["list_price"]
            line_total = _round2(deal_price * qty)
            lines_sum = _round2(lines_sum + line_total)
            line_id += 1
            lines.append({
                "id": line_id,
                "sales_order_id": order_id,
                "item_id": item["id"],
                "qty": qty,
                "deal_price": deal_price,
                "line_total": line_total,
            })

        if order_state == "voided":
            coupon = 0.0
            delivery = 0.0
            payment_due = 0.0
        else:
            if rng.random() < COUPON_PROBABILITY:
                rate = rng.choice(COUPON_RATES)
                coupon = _round2(lines_sum * rate)
            else:
                coupon = 0.0
            if lines_sum - coupon >= FREE_DELIVERY_THRESHOLD:
                delivery = 0.0
            elif rng.random() < FREE_DELIVERY_PROBABILITY:
                delivery = 0.0
            else:
                delivery = float(rng.choice(DELIVERY_FEES))
            payment_due = _round2(lines_sum - coupon + delivery)

        orders.append({
            "id": order_id,
            "member_id": member_id,
            "placed_on": order_day.isoformat(),
            "order_state": order_state,
            "coupon_deduction": coupon,
            "delivery_charge": delivery,
            "payment_due": payment_due,
        })

    return orders, lines


def generate_all() -> dict[str, list[dict]]:
    """按固定种子一次性生成全部表数据。"""
    rng = random.Random(SEED)
    departments = gen_departments(rng)
    items = gen_items(rng, departments)
    members = gen_members(rng)
    orders, order_lines = gen_orders_and_lines(rng, members, items)
    return {
        "departments": departments,
        "items": items,
        "members": members,
        "sales_orders": orders,
        "order_lines": order_lines,
    }


if __name__ == "__main__":
    data = generate_all()
    for table, rows in data.items():
        print(f"{table}: {len(rows)} 行")
    # 干跑口径自检（不写库）
    orders = {o["id"]: o for o in data["sales_orders"]}
    sums: dict[int, float] = {}
    for line in data["order_lines"]:
        sums[line["sales_order_id"]] = _round2(
            sums.get(line["sales_order_id"], 0.0) + line["line_total"]
        )
    bad = 0
    for oid, order in orders.items():
        if order["order_state"] == "voided":
            continue
        expect = _round2(
            sums[oid] - order["coupon_deduction"] + order["delivery_charge"]
        )
        if abs(expect - order["payment_due"]) > 0.01:
            bad += 1
    print(f"payment_due 口径自检：{'PASS' if bad == 0 else f'FAIL({bad})'}")
