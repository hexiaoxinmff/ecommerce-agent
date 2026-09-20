"""电商演示数据生成器（纯数据生成，不直接写数据库文件）。

- 固定随机种子，每次运行生成完全一致的数据；
- 不依赖外部网络，不依赖 LLM；
- 业务语义符合真实电商场景（中文商品名、省市地区、状态、金额口径）。

实际建库、建表、写入与索引由 init_db.py 完成。
单独运行本脚本仅做干跑（打印各表生成数量），不产生任何文件。
"""

import random
from datetime import date, timedelta

# 固定随机种子（保证每次重新生成可复现）
SEED = 20260914

# 订单时间范围（库内时间统一使用 ISO "YYYY-MM-DD" 一种格式）
DATE_START = date(2024, 1, 1)
DATE_END = date(2026, 9, 12)
REGISTER_START = date(2023, 1, 1)
REGISTER_END = date(2026, 8, 31)

# 数据规模目标（允许随机生成造成少量偏差）
TARGET_USERS = 2_000
TARGET_ORDERS = 10_000
TARGET_PRODUCTS = 500

# 省级地区（订单/用户两级都使用）
REGIONS = [
    "广东", "江苏", "浙江", "山东", "上海", "北京", "四川", "湖北",
    "河南", "福建", "湖南", "安徽", "辽宁", "陕西", "重庆",
]
REGION_WEIGHTS = [0.12, 0.10, 0.09, 0.08, 0.07, 0.07, 0.07, 0.06,
                  0.06, 0.06, 0.05, 0.05, 0.04, 0.04, 0.04]

# 常见中文姓与名（约 40 × 80 组合，抽样 2000 保证用户名唯一且真实感强）
SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "吴", "周",
    "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗",
    "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹",
    "彭", "曾", "肖", "田", "董", "袁", "潘", "于", "蒋", "蔡",
]
GIVEN_NAMES = [
    "伟", "芳", "娜", "敏", "静", "磊", "军", "洋", "勇", "艳",
    "杰", "娟", "涛", "明", "超", "秀兰", "霞", "平", "刚", "桂英",
    "文", "辉", "建华", "志强", "子轩", "雨桐", "浩然", "欣怡", "梓涵", "语嫣",
    "明轩", "思远", "嘉懿", "若曦", "泽宇", "博文", "俊杰", "雨欣", "诗涵", "佳琪",
    "天佑", "文博", "昊然", "一鸣", "瑞霖", "俊熙", "美玲", "丽华", "淑芬", "国栋",
    "志明", "海燕", "玉兰", "国庆", "德明", "春梅", "冬梅", "美娟", "雪梅", "金凤",
    "长海", "永强", "晓峰", "晓燕", "丽萍", "红梅", "桂兰", "亚男", "少华", "景辉",
    "新宇", "紫萱", "梦琪", "子墨", "亦菲", "宇轩", "嘉琪", "致远", "晓彤", "家豪",
]

# 邮箱拼音片段池（保证邮箱唯一：拼音片段 + 序号 + 保留域名）
PINYIN_SURNAMES = [
    "wang", "li", "zhang", "liu", "chen", "yang", "huang", "zhao", "wu", "zhou",
    "xu", "sun", "ma", "zhu", "hu", "guo", "he", "gao", "lin", "luo",
]
PINYIN_GIVEN = [
    "wei", "fang", "na", "min", "jing", "lei", "jun", "yang", "yong", "yan",
    "jie", "tao", "ming", "chao", "xia", "ping", "gang", "xin", "yuan", "chen",
]

# 用户状态（活跃/停用）
USER_STATUSES = ["active", "inactive"]
USER_STATUS_WEIGHTS = [0.85, 0.15]

# 订单状态（含取消；取消订单最终实付为 0）
ORDER_STATUSES = ["completed", "shipped", "paid", "pending", "cancelled"]
ORDER_STATUS_WEIGHTS = [0.60, 0.15, 0.10, 0.10, 0.05]

# 每个订单的明细行数（1~5 行，加权）
ITEM_COUNT_CHOICES = [1, 2, 3, 4, 5]
ITEM_COUNT_WEIGHTS = [0.10, 0.25, 0.30, 0.20, 0.15]

# 单行购买数量（1~5 件，加权）
QUANTITY_CHOICES = [1, 2, 3, 4, 5]
QUANTITY_WEIGHTS = [0.60, 0.25, 0.10, 0.03, 0.02]

# 订单级优惠（约 30% 订单享受，按明细合计比例减免）
DISCOUNT_RATES = [0.05, 0.10, 0.15, 0.20, 0.25]
DISCOUNT_PROBABILITY = 0.30

# 运费（大额订单免运费）
SHIPPING_FEES = [6.0, 8.0, 12.0, 15.0]
FREE_SHIPPING_THRESHOLD = 399.0
FREE_SHIPPING_PROBABILITY = 0.30

# 品牌池（商品名 = 品牌 + 品类 + 型号后缀，保证业务合理）
BRANDS = [
    "小米", "华为", "美的", "格力", "海尔", "联想", "苏泊尔", "九阳",
    "安踏", "李宁", "回力", "南极人", "恒源祥", "得力", "晨光", "公牛",
    "良品铺子", "三只松鼠", "花西子", "完美日记", "珀莱雅", "飞科",
    "海澜之家", "优衣库", "无印良品", "骆驼", "探路者", "迪卡侬",
    "乐高", "费雪", "帮宝适", "美赞臣", "光明", "伊利",
]
MODEL_SUFFIXES = [
    "Pro", "Max", "Plus", "青春版", "旗舰款", "2025款",
    "经典款", "轻享版", "臻享款", "X1", "X2", "Air",
]

# 分类体系：8 个一级分类 + 22 个叶子分类（共 30 个）
# 叶子分类下挂商品模板：(商品通用名, 最低价, 最高价)
CATALOG = {
    "数码家电": {
        "手机通讯": [("智能手机", 1999, 7999), ("蓝牙耳机", 129, 1899),
                     ("智能手表", 499, 2999), ("手机保护壳", 19, 129)],
        "电脑办公": [("笔记本电脑", 2999, 9999), ("机械键盘", 199, 999),
                     ("无线鼠标", 59, 299), ("显示器", 699, 2999)],
        "家用电器": [("空调", 1999, 5999), ("冰箱", 1599, 6999),
                     ("洗衣机", 999, 4999), ("电饭煲", 199, 999),
                     ("扫地机器人", 999, 3999)],
    },
    "服饰鞋包": {
        "男装": [("男士T恤", 39, 199), ("男士衬衫", 99, 399),
                 ("男士夹克", 199, 899), ("男士牛仔裤", 99, 499)],
        "女装": [("连衣裙", 99, 599), ("女士针织衫", 89, 399),
                 ("女士风衣", 199, 999), ("半身裙", 69, 399)],
        "鞋靴箱包": [("运动鞋", 129, 899), ("休闲皮鞋", 159, 699),
                     ("双肩背包", 79, 499), ("行李箱", 199, 1299)],
    },
    "美妆个护": {
        "护肤": [("面霜", 69, 599), ("精华液", 129, 999),
                 ("防晒霜", 49, 399), ("面膜套装", 39, 299)],
        "彩妆": [("口红", 59, 399), ("粉底液", 99, 599), ("眼影盘", 69, 399)],
        "洗护清洁": [("洗发水", 29, 199), ("沐浴露", 25, 159),
                     ("洗衣液", 29, 129), ("牙膏套装", 19, 89)],
    },
    "食品生鲜": {
        "休闲零食": [("坚果礼盒", 39, 199), ("薯片组合", 19, 79),
                     ("巧克力礼盒", 49, 299), ("饼干大礼包", 25, 129)],
        "粮油调味": [("食用油", 49, 199), ("大米", 39, 159), ("酱油料酒组合", 19, 89)],
        "生鲜果蔬": [("水果礼盒", 59, 299), ("海鲜大礼包", 129, 599),
                     ("有机蔬菜组合", 39, 199)],
    },
    "家居生活": {
        "家纺": [("四件套", 99, 599), ("羽绒被", 199, 1299), ("乳胶枕", 59, 399)],
        "家具": [("书桌", 199, 999), ("布艺沙发", 999, 3999), ("床头柜", 159, 699)],
        "厨具家饰": [("炒锅", 89, 499), ("餐具套装", 59, 299), ("收纳盒组合", 29, 199)],
    },
    "运动户外": {
        "运动服饰": [("速干T恤", 49, 199), ("运动卫衣", 99, 399), ("瑜伽裤", 69, 299)],
        "运动装备": [("篮球", 59, 299), ("羽毛球拍", 89, 599), ("跑步机", 1299, 4999)],
        "户外用品": [("帐篷", 199, 999), ("登山包", 129, 699), ("户外折叠椅", 59, 299)],
    },
    "图书文娱": {
        "图书": [("小说", 25, 99), ("经管类图书", 39, 159), ("少儿绘本", 29, 129)],
        "文创文具": [("钢笔", 39, 399), ("手账本", 25, 129)],
    },
    "母婴玩具": {
        "母婴用品": [("婴儿纸尿裤", 69, 259), ("婴儿奶粉", 159, 499),
                     ("婴儿推车", 399, 1999)],
        "儿童玩具": [("积木套装", 79, 499), ("遥控汽车", 59, 399), ("毛绒玩具", 39, 199)],
    },
}


def _round2(value: float) -> float:
    """金额统一保留两位小数。"""
    return round(value, 2)


def gen_categories(rng: random.Random) -> list[dict]:
    """生成 8 个一级分类 + 22 个叶子分类（含 parent_id 层级）。"""
    categories = []
    for top_name, leaves in CATALOG.items():
        top_id = len(categories) + 1
        categories.append({"id": top_id, "name": top_name, "parent_id": None})
        for leaf_name in leaves:
            categories.append({
                "id": len(categories) + 1,
                "name": leaf_name,
                "parent_id": top_id,
            })
    return categories


def gen_products(rng: random.Random, categories: list[dict]) -> list[dict]:
    """为每个叶子分类生成商品模板数量的商品（总计约 500 个）。"""
    leaf_ids = {c["name"]: c["id"] for c in categories if c["parent_id"] is not None}
    # 展平所有商品模板
    templates = []
    for top_name, leaves in CATALOG.items():
        for leaf_name, tpls in leaves.items():
            for generic, lo, hi in tpls:
                templates.append((leaf_ids[leaf_name], generic, lo, hi))

    # 500 个商品均分到 75 个模板：先每模板 6 个，剩余 50 个随机追加
    base, remainder = divmod(TARGET_PRODUCTS, len(templates))
    counts = [base] * len(templates)
    for idx in rng.choices(range(len(templates)), k=remainder):
        counts[idx] += 1

    products = []
    used_names = set()
    for idx, (category_id, generic, lo, hi) in enumerate(templates):
        for _ in range(counts[idx]):
            brand = rng.choice(BRANDS)
            suffix = rng.choice(MODEL_SUFFIXES)
            name = f"{brand}{generic}{suffix}"
            # 保证商品名唯一（极少冲突时追加代数后缀）
            attempt = 1
            while name in used_names:
                attempt += 1
                name = f"{brand}{generic}{suffix}{attempt}代"
            used_names.add(name)
            products.append({
                "id": len(products) + 1,
                "name": name,
                "category_id": category_id,
                "price": _round2(rng.uniform(lo, hi)),
                "status": "on_sale" if rng.random() < 0.92 else "off_sale",
            })
    return products


def gen_users(rng: random.Random) -> list[dict]:
    """生成约 2000 个用户：唯一用户名、唯一邮箱、地区、注册时间、状态。"""
    # 无放回抽样保证用户名唯一（先按序去重，确保样本池本身无重复且顺序确定）
    name_pool = list(dict.fromkeys(s + g for s in SURNAMES for g in GIVEN_NAMES))
    assert len(name_pool) >= TARGET_USERS, "名字组合池不足，无法生成足够唯一用户名"
    usernames = rng.sample(name_pool, TARGET_USERS)
    register_days = (REGISTER_END - REGISTER_START).days

    users = []
    for i, username in enumerate(usernames):
        py_surname = rng.choice(PINYIN_SURNAMES)
        py_given = rng.choice(PINYIN_GIVEN)
        email = f"{py_surname}{py_given}{i:04d}@example.com"
        reg_offset = rng.randint(0, register_days)
        users.append({
            "id": i + 1,
            "username": username,
            "email": email,
            "region": rng.choices(REGIONS, weights=REGION_WEIGHTS, k=1)[0],
            "register_date": (REGISTER_START + timedelta(days=reg_offset)).isoformat(),
            "status": rng.choices(USER_STATUSES, weights=USER_STATUS_WEIGHTS, k=1)[0],
        })
    return users


def gen_orders_and_items(
    rng: random.Random,
    users: list[dict],
    products: list[dict],
) -> tuple[list[dict], list[dict]]:
    """生成订单与订单明细。

    金额口径：
    - order_items.subtotal = unit_price × quantity（明细行金额）
    - orders.total_amount   = 明细合计 − 订单级优惠 + 运费（最终实付金额）
    - 取消订单 final 实付为 0、无优惠与运费
    因此两者天然存在可解释的业务差异。
    """
    total_days = (DATE_END - DATE_START).days
    n_products = len(products)

    orders: list[dict] = []
    items: list[dict] = []
    item_id = 0
    for order_idx in range(TARGET_ORDERS):
        user = rng.choice(users)
        user_id = user["id"]

        # 下单时间：整体偏向近期（幂次变换），且不早于用户注册时间
        t = rng.random() ** 0.85
        order_day = DATE_START + timedelta(days=int(t * total_days))
        register_day = date.fromisoformat(user["register_date"])
        if order_day < register_day:
            clamp = min((register_day + timedelta(days=rng.randint(0, 30))), DATE_END)
            order_day = clamp

        status = rng.choices(ORDER_STATUSES, weights=ORDER_STATUS_WEIGHTS, k=1)[0]

        # 收货地区：70% 与用户地区一致，30% 为其他地区
        if rng.random() < 0.70:
            region = user["region"]
        else:
            region = rng.choices(REGIONS, weights=REGION_WEIGHTS, k=1)[0]

        order_id = order_idx + 1

        # 生成明细行
        n_lines = rng.choices(ITEM_COUNT_CHOICES, weights=ITEM_COUNT_WEIGHTS, k=1)[0]
        chosen = rng.sample(range(n_products), k=n_lines)
        subtotal_sum = 0.0
        for product_idx in chosen:
            product = products[product_idx]
            quantity = rng.choices(QUANTITY_CHOICES, weights=QUANTITY_WEIGHTS, k=1)[0]
            unit_price = product["price"]
            subtotal = _round2(unit_price * quantity)
            subtotal_sum = _round2(subtotal_sum + subtotal)
            item_id += 1
            items.append({
                "id": item_id,
                "order_id": order_id,
                "product_id": product["id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })

        if status == "cancelled":
            discount = 0.0
            shipping = 0.0
            total = 0.0
        else:
            # 订单级优惠（约 30% 订单）
            if rng.random() < DISCOUNT_PROBABILITY:
                rate = rng.choice(DISCOUNT_RATES)
                discount = _round2(subtotal_sum * rate)
            else:
                discount = 0.0
            # 运费：大额订单免运费，小额订单部分免运费
            if subtotal_sum - discount >= FREE_SHIPPING_THRESHOLD:
                shipping = 0.0
            elif rng.random() < FREE_SHIPPING_PROBABILITY:
                shipping = 0.0
            else:
                shipping = float(rng.choice(SHIPPING_FEES))
            total = _round2(subtotal_sum - discount + shipping)

        orders.append({
            "id": order_id,
            "user_id": user_id,
            "order_date": order_day.isoformat(),
            "status": status,
            "region": region,
            "discount_amount": discount,
            "shipping_fee": shipping,
            "total_amount": total,
        })

    return orders, items


def generate_all() -> dict[str, list[dict]]:
    """按固定种子一次性生成全部表数据。"""
    rng = random.Random(SEED)
    categories = gen_categories(rng)
    products = gen_products(rng, categories)
    users = gen_users(rng)
    orders, order_items = gen_orders_and_items(rng, users, products)
    return {
        "categories": categories,
        "products": products,
        "users": users,
        "orders": orders,
        "order_items": order_items,
    }


if __name__ == "__main__":
    # 干跑：只打印生成数量，不产生任何文件
    data = generate_all()
    for table, rows in data.items():
        print(f"{table}: {len(rows)}")
    print("干跑完成（未写入任何文件）。")