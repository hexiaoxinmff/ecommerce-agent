"""意图分布可视化看板生成器。

扫描 data/logs/conversations.jsonl（客服会话日志），按意图（intent）聚合，
生成一份自包含的 ECharts HTML 看板（饼图 + 柱状图 + 时间趋势），
可直接双击在浏览器打开，便于写入简历 / 演示。

若日志为空或不足，则自动生成一份演示数据，保证看板始终可看。

运行：python -m src.eval.intent_dashboard
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from config import settings

INTENT_COLORS = {
    "售前咨询": "#5B8FF9",
    "售后问题": "#61DDAA",
    "物流订单": "#65789B",
    "投诉建议": "#F6BD16",
    "闲聊": "#7262FD",
}


def load_logs():
    """读取会话日志，返回 list[{time, intent, query}]。"""
    logs = []
    p = settings.LOG_FILE
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                logs.append(d)
            except Exception:
                continue
    return logs


def _demo_logs():
    """日志不足时生成演示数据（12 天、各意图混合），保证看板可演示。"""
    base = datetime(2026, 7, 20, 9, 0, 0)
    intents = list(INTENT_COLORS.keys())
    weights = [22, 18, 14, 5, 7]  # 各意图出现次数
    logs = []
    day = 0
    for it, w in zip(intents, weights):
        for i in range(w):
            t = base + timedelta(days=day, hours=(i * 3) % 12)
            logs.append({"time": t.isoformat(), "intent": it, "query": f"演示-{it}-{i}"})
            day = (day + 1) % 12
    return logs


def aggregate(logs):
    intent_counter = Counter(d.get("intent", "未知") for d in logs)
    # 按天聚合
    by_day = defaultdict(Counter)
    for d in logs:
        try:
            day = datetime.fromisoformat(d["time"]).strftime("%m-%d")
        except Exception:
            day = "未知"
        by_day[day][d.get("intent", "未知")] += 1
    days = sorted(by_day.keys())
    return intent_counter, by_day, days


def build_html(intent_counter, by_day, days):
    labels = list(intent_counter.keys())
    values = [intent_counter[k] for k in labels]
    colors = [INTENT_COLORS.get(k, "#999") for k in labels]

    # 堆叠柱状图：每天各意图数量
    series = []
    for it in INTENT_COLORS:
        if it in labels:
            series.append({
                "name": it,
                "type": "bar",
                "stack": "total",
                "emphasis": {"focus": "series"},
                "itemStyle": {"color": INTENT_COLORS[it]},
                "data": [by_day[d].get(it, 0) for d in days],
            })

    total = sum(values)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>客服会话 · 意图分布看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  body {{ margin:0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background:#0f1115; color:#e6e6e6; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color:#9aa0a6; font-size: 13px; margin-bottom: 20px; }}
  .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom: 22px; }}
  .card {{ background:#1a1d24; border:1px solid #2a2e37; border-radius:10px;
          padding:14px 18px; min-width:120px; }}
  .card .num {{ font-size:24px; font-weight:700; }}
  .card .lbl {{ color:#9aa0a6; font-size:12px; margin-top:2px; }}
  .panel {{ background:#1a1d24; border:1px solid #2a2e37; border-radius:12px;
           padding:14px; margin-bottom:18px; }}
  .panel h2 {{ font-size:15px; margin:4px 6px 10px; font-weight:600; }}
  .row {{ display:flex; gap:18px; flex-wrap:wrap; }}
  .row > div {{ flex:1; min-width:340px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>云栖数码 · 智能客服会话意图分布</h1>
  <div class="sub">数据源：data/logs/conversations.jsonl ｜ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ 总会话数：{total}</div>

  <div class="cards">
    <div class="card"><div class="num">{total}</div><div class="lbl">总会话数</div></div>
    <div class="card"><div class="num">{len(labels)}</div><div class="lbl">意图类别</div></div>
    <div class="card"><div class="num">{labels[0] if labels else '-'}</div><div class="lbl">最高频意图</div></div>
    <div class="card"><div class="num">{days[0] if days else '-'} ~ {days[-1] if days else '-'}</div><div class="lbl">日期跨度</div></div>
  </div>

  <div class="panel">
    <h2>意图占比（饼图）</h2>
    <div id="pie" style="height:340px"></div>
  </div>

  <div class="panel">
    <h2>每日意图分布（堆叠柱状图）</h2>
    <div id="bar" style="height:380px"></div>
  </div>
</div>

<script>
  var pie = echarts.init(document.getElementById('pie'), 'dark');
  pie.setOption({{
    backgroundColor:'transparent',
    tooltip:{{ trigger:'item', formatter:'{{b}}: {{c}} ({{d}}%)' }},
    legend:{{ bottom:0, textStyle:{{color:'#bbb'}} }},
    series:[{{
      type:'pie', radius:['42%','68%'], center:['50%','46%'],
      itemStyle:{{ borderColor:'#1a1d24', borderWidth:2 }},
      label:{{ color:'#ddd' }},
      data:{json.dumps([{"name":k,"value":v,"itemStyle":{"color":c}} for k,v,c in zip(labels,values,colors)], ensure_ascii=False)}
    }}]
  }});

  var bar = echarts.init(document.getElementById('bar'), 'dark');
  bar.setOption({{
    backgroundColor:'transparent',
    tooltip:{{ trigger:'axis', axisPointer:{{type:'shadow'}} }},
    legend:{{ top:0, textStyle:{{color:'#bbb'}} }},
    grid:{{ left:40, right:20, top:36, bottom:40 }},
    xAxis:{{ type:'category', data:{json.dumps(days, ensure_ascii=False)}, axisLabel:{{color:'#aaa'}} }},
    yAxis:{{ type:'value', axisLabel:{{color:'#aaa'}}, splitLine:{{lineStyle:{{color:'#2a2e37'}}}} }},
    series:{json.dumps(series, ensure_ascii=False)}
  }});

  window.addEventListener('resize', function(){{ pie.resize(); bar.resize(); }});
</script>
</body>
</html>"""
    return html


def build_dashboard():
    """生成看板 HTML 字符串（best-effort 落盘缓存），返回即可直接响应。"""
    logs = load_logs()
    is_demo = False
    if len(logs) < 5:
        logs = _demo_logs()
        is_demo = True
    intent_counter, by_day, days = aggregate(logs)
    html = build_html(intent_counter, by_day, days)

    try:
        out_dir = settings.DATA_DIR / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "intent_dashboard.html").write_text(html, encoding="utf-8")
    except Exception:
        # 运行在非 root 或只读目录时（如 HF Spaces uid 1000）忽略写盘失败，仍返回 HTML
        pass
    return html


def main():
    html = build_dashboard()
    # 仅用于命令行打印统计
    logs = load_logs()
    intent_counter, by_day, days = aggregate(logs if len(logs) >= 5 else _demo_logs())
    print("意图统计：", dict(intent_counter))
    print(f"会话总数：{sum(intent_counter.values())} ｜ 日期：{days[0] if days else '-'} ~ {days[-1] if days else '-'}")
    print(f"看板 HTML 已生成（{len(html)} 字节）")


if __name__ == "__main__":
    main()
