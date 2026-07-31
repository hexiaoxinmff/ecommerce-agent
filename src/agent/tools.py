"""工具节点：模拟订单 / 物流查询（生产环境可替换为真实 ERP / 物流 API）。"""
import random

# 演示用订单库
_ORDERS = {
    "YS20240001": {"status": "已发货", "logistics": "顺丰 SF1234567890，今日已揽收，预计明日晚间送达"},
    "YS20240002": {"status": "运输中", "logistics": "京东 JD0098765432，已到达【武汉转运中心】，预计后天送达"},
    "YS20240003": {"status": "已签收", "logistics": "顺丰 SF1234560000，已于昨日 14:22 签收"},
    "YS20240004": {"status": "待发货", "logistics": "订单已支付，仓库正在打包，预计今日 18:00 前发出"},
}


def lookup_order(order_no: str) -> dict:
    """查询订单状态与物流轨迹。"""
    if order_no in _ORDERS:
        info = _ORDERS[order_no]
        return {"order_no": order_no, "status": info["status"], "logistics": info["logistics"]}
    # 对未知订单号给出确定性的“未找到”结果（演示用，不随机）
    return {
        "order_no": order_no,
        "status": "未找到",
        "logistics": "未查询到该订单，请确认订单号格式（如 YS20240001）或联系人工客服核实。",
    }
