"""Self-contained HTML report generator (no CDN, no build step).

The whole report is one file that renders anywhere: inline CSS, hand-rolled SVG
charts, no JavaScript framework.  Open it in a browser, screenshot it, share it.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List

from .ledger import Asset, ScanResult

__all__ = ["render_html"]

_PALETTE = {
    "dead":     "#9ca3af",
    "critical": "#e11d48",
    "warn":     "#f59e0b",
    "steady":   "#0ea5e9",
    "calm":     "#10b981",
}

_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#14171a;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:920px;margin:0 auto;padding:32px 20px 72px}
.hero{background:linear-gradient(135deg,#ffc72c 0%,#ffb800 45%,#ff9500 100%);
 border-radius:20px;padding:34px 34px 28px;color:#14171a;box-shadow:0 14px 40px rgba(255,181,0,.28)}
.hero h1{margin:0;font-size:30px;letter-spacing:-.4px;font-weight:800}
.hero .sub{margin-top:8px;font-size:15px;opacity:.82;font-weight:500}
.tagrow{margin-top:18px;display:flex;gap:8px;flex-wrap:wrap}
.tag{background:rgba(20,23,26,.1);border:1px solid rgba(20,23,26,.14);
 border-radius:999px;padding:4px 12px;font-size:12.5px;font-weight:600}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:26px}
.stat{background:rgba(255,255,255,.72);border-radius:14px;padding:14px 16px;backdrop-filter:blur(6px)}
.stat .k{font-size:11.5px;opacity:.68;font-weight:700;letter-spacing:.4px}
.stat .v{font-size:25px;font-weight:800;margin-top:3px;letter-spacing:-.6px}
.stat .u{font-size:12px;font-weight:600;opacity:.62}
.stat.danger .v{color:#b91c1c}
section{margin-top:34px}
h2{font-size:19px;font-weight:800;margin:0 0 4px;letter-spacing:-.2px;display:flex;align-items:center;gap:9px}
h2::before{content:"";width:5px;height:19px;border-radius:3px;background:#ffb800}
.hint{color:#6b7280;font-size:13px;margin:0 0 14px}
.card{background:#fff;border:1px solid #e8eaed;border-radius:16px;padding:20px;
 box-shadow:0 1px 3px rgba(16,24,40,.05)}
.timeline{display:flex;flex-direction:column;gap:10px}
.row{display:grid;grid-template-columns:118px 1fr auto;gap:14px;align-items:center;
 border:1px solid #eceff2;border-radius:12px;padding:11px 14px;background:#fcfcfd}
.row .when{font-size:12.5px;font-weight:800;letter-spacing:-.1px}
.row .bar{height:9px;border-radius:6px;background:#eef0f3;overflow:hidden;margin-top:6px}
.row .bar i{display:block;height:100%;border-radius:6px}
.row .amt{font-size:14.5px;font-weight:800;white-space:nowrap;letter-spacing:-.3px}
.name{font-size:14px;font-weight:700}
.note{font-size:12px;color:#6b7280;margin-top:1px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-size:11.5px;color:#6b7280;font-weight:800;letter-spacing:.4px;
 padding:9px 10px;border-bottom:2px solid #eceef1}
td{padding:11px 10px;border-bottom:1px solid #f2f4f6;vertical-align:top}
tr:last-child td{border-bottom:none}
.step{display:inline-flex;align-items:center;justify-content:center;width:23px;height:23px;
 border-radius:7px;background:#14171a;color:#fff;font-size:12px;font-weight:800}
.pill{display:inline-block;padding:2.5px 9px;border-radius:999px;font-size:11.5px;font-weight:700;white-space:nowrap}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.kv{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed #eceff2;font-size:13px}
.kv:last-child{border-bottom:none}
.kv b{font-variant-numeric:tabular-nums}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:#4b5563}
.legend span{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.dot{width:9px;height:9px;border-radius:3px;display:inline-block}
footer{margin-top:40px;text-align:center;color:#9ca3af;font-size:12px;line-height:1.9}
code{background:#f3f4f6;border-radius:5px;padding:1.5px 6px;font-size:12px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}
 .row{grid-template-columns:1fr;gap:5px}.row .amt{text-align:left}}
"""


def _e(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def _tier_color(tier: str) -> str:
    return _PALETTE.get(tier, _PALETTE["calm"])


def _fmt_when(asset: Asset) -> str:
    days = asset.days_left_int
    if days is None:
        return "无期限"
    if days < 0:
        return "已过期 %d 天" % abs(days)
    if days == 0:
        return "今天到期"
    return "%d 天后" % days


def _donut(by_kind: Dict[str, List[Asset]]) -> str:
    """Hand-rolled SVG donut so the report stays dependency-free."""
    total = sum(sum(a.value * (a.quantity or 1) for a in items)
                for items in by_kind.values())
    if total <= 0:
        return ""
    colors = ["#ffb800", "#e11d48", "#0ea5e9", "#10b981", "#8b5cf6", "#f97316"]
    radius, circumference = 54.0, 2 * 3.14159265 * 54.0
    offset = 0.0
    segments: List[str] = []
    for index, (kind, items) in enumerate(
            sorted(by_kind.items(),
                   key=lambda kv: -sum(a.value * (a.quantity or 1) for a in kv[1]))):
        value = sum(a.value * (a.quantity or 1) for a in items)
        length = value / total * circumference
        color = colors[index % len(colors)]
        segments.append(
            '<circle cx="70" cy="70" r="%.0f" fill="none" stroke="%s" stroke-width="22"'
            ' stroke-dasharray="%.2f %.2f" stroke-dashoffset="%.2f">'
            '<title>%s ¥%.2f</title></circle>'
            % (radius, color, max(length - 2, 0.4), circumference,
               -offset, _e(items[0].kind_label), value)
        )
        offset += length
    return (
        '<svg width="140" height="140" viewBox="0 0 140 140" role="img">'
        '<circle cx="70" cy="70" r="54" fill="none" stroke="#f0f1f3" stroke-width="22"/>'
        + "".join(segments) +
        '<text x="70" y="66" text-anchor="middle" font-size="21" font-weight="800">¥%.0f</text>'
        '<text x="70" y="84" text-anchor="middle" font-size="10" fill="#6b7280">待清算总额</text>'
        '</svg>' % total
    )


def _timeline(result: ScanResult) -> str:
    rows: List[str] = []
    assets = [a for a in result.sorted_assets()
              if a.days_left is None or a.days_left >= 0]
    ceiling = max([a.priority for a in assets] or [1.0])
    for asset in assets[:14]:
        tier = asset.urgency_tier
        color = _tier_color(tier)
        width = max(6.0, min(100.0, asset.priority / ceiling * 100.0))
        rows.append(
            '<div class="row">'
            '<div><div class="when" style="color:%s">%s</div>'
            '<div class="note">%s</div></div>'
            '<div><div class="name">%s %s</div>'
            '<div class="note">%s</div>'
            '<div class="bar"><i style="width:%.1f%%;background:%s"></i></div></div>'
            '<div class="amt" style="color:%s">¥%.2f</div>'
            '</div>' % (
                color, _e(_fmt_when(asset)),
                _e(asset.expires_at.strftime("%m-%d") if asset.expires_at else "—"),
                _e(asset.kind_icon), _e(asset.title),
                _e(asset.kind_label + " · " + (asset.detail or "")[:44]),
                width, color, color,
                asset.value * (asset.quantity or 1),
            )
        )
    return "".join(rows) or '<p class="hint">没有在倒计时的资产，恭喜。</p>'


def _plan_table(plan: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for item in plan:
        tier = ("critical" if item["days_left"] is not None and item["days_left"] <= 3
                else "warn" if item["days_left"] is not None and item["days_left"] <= 14
                else "calm")
        rows.append(
            "<tr><td><span class=\"step\">%d</span></td>"
            "<td><b>%s %s</b><div class=\"note\">%s</div></td>"
            "<td nowrap>¥%.2f</td>"
            "<td><span class=\"pill\" style=\"background:%s22;color:%s\">%s</span></td>"
            "<td>%s%s</td></tr>" % (
                item["step"], _e(item["icon"]), _e(item["asset"]),
                _e(item["kind"]), item["value"],
                _tier_color(tier), _tier_color(tier), _e(item["urgency"]),
                _e(item["action"]),
                (" <code>%s</code>" % _e(item["tool"])) if item["tool"] else "",
            )
        )
    return "".join(rows)


def render_html(result: ScanResult,
                plan: List[Dict[str, Any]],
                title: str = "麦麦到期清单") -> str:
    """Render the full report as one standalone HTML document."""
    by_kind = result.by_kind()
    parts: List[str] = ["<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
                        '<meta name="viewport" content="width=device-width,initial-scale=1">',
                        "<title>%s</title><style>%s</style></head><body><div class=\"wrap\">"
                        % (_e(title), _CSS)]

    # hero
    parts.append(
        '<div class="hero"><h1>%s</h1>'
        '<div class="sub">你的每一张券、每一分积分、每一次抽奖机会，都在倒计时。</div>'
        '<div class="tagrow"><span class="tag">🍔 McDonald\'s China MCP</span>'
        '<span class="tag">🔌 %d 个工具已调用</span>'
        '<span class="tag">🧾 %d 项资产</span>'
        '<span class="tag">🕒 %s</span></div>'
        '<div class="stats">'
        '<div class="stat"><div class="k">待清算总额</div><div class="v">¥%.0f</div>'
        '<div class="u">按券面值与积分折算估算</div></div>'
        '<div class="stat danger"><div class="k">7天内将蒸发</div><div class="v">¥%.0f</div>'
        '<div class="u">什么都不做就会失去</div></div>'
        '<div class="stat"><div class="k">30天内到期</div><div class="v">%d</div>'
        '<div class="u">项资产进入倒计时</div></div>'
        '<div class="stat"><div class="k">已过期</div><div class="v">%d</div>'
        '<div class="u">项资产已失效</div></div>'
        '</div></div>' % (
            _e(title), len(result.tools_ok), len(result.assets),
            _e(datetime.now().strftime("%Y-%m-%d %H:%M")),
            result.total_value, result.at_risk_value,
            len(result.expiring_30d), result.dead_count,
        )
    )

    # timeline
    legend = "".join(
        '<span><i class="dot" style="background:%s"></i>%s</span>' % (color, _e(label))
        for color, label in [
            (_PALETTE["critical"], "≤3天"), (_PALETTE["warn"], "≤2周"),
            (_PALETTE["steady"], "≤1月"), (_PALETTE["calm"], "安全期"),
        ]
    )
    parts.append(
        '<section><h2>到期倒计时</h2>'
        '<p class="hint">按「价值 × 紧迫度」排序，红条越短越紧急。</p>'
        '<div class="card"><div class="timeline">%s</div><div class="legend">%s</div></div>'
        '</section>' % (_timeline(result), legend)
    )

    # composition + snapshot
    snapshot = "".join(
        '<div class="kv"><span>%s</span><b>%s</b></div>' % (_e(k), _e(v))
        for k, v in list(result.account_snapshot.items())[:7]
    ) or '<div class="kv"><span>账户快照不可用</span><b>—</b></div>'
    composition = "".join(
        '<div class="kv"><span>%s %s</span><b>%d 项</b></div>' % (
            _e(items[0].kind_icon), _e(items[0].kind_label), len(items))
        for _, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1]))
    )
    parts.append(
        '<section class="grid2">'
        '<div><h2>构成分析</h2><p class="hint">各类资产的待清算金额占比。</p>'
        '<div class="card" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">'
        '%s<div style="flex:1;min-width:180px">%s</div></div></div>'
        '<div><h2>账户快照</h2><p class="hint">来自 <code>query-my-account</code> 的原始数据。</p>'
        '<div class="card">%s</div></div>'
        '</section>' % (_donut(by_kind), composition, snapshot)
    )

    # plan
    parts.append(
        '<section><h2>清算计划</h2>'
        '<p class="hint">照着从上往下做，一次别漏。</p>'
        '<div class="card"><table><thead><tr><th>#</th><th>资产</th><th>估值</th>'
        '<th>紧迫度</th><th>建议动作 / 调用工具</th></tr></thead><tbody>%s</tbody></table>'
        '</div></section>' % _plan_table(plan)
    )

    # provenance
    failed = "".join(
        '<li><code>%s</code> — %s</li>' % (_e(k), _e(v))
        for k, v in result.tools_failed.items()
    )
    parts.append(
        '<section class="grid2">'
        '<div><h2>工具溯源</h2><p class="hint">这份报告由以下 MCP 工具真实拼装。</p>'
        '<div class="card" style="font-size:13px">%s</div></div>'
        '<div><h2>降级明细</h2><p class="hint">失败的调用不会中断整体扫描。</p>'
        '<div class="card" style="font-size:13px">%s</div></div>'
        '</section>' % (
            "".join('<span class="pill" style="background:#fff8e6;color:#b45309;margin:3px 4px 3px 0">%s</span>'
                    % _e(t) for t in result.tools_ok),
            ("<ul style='margin:0;padding-left:18px;color:#6b7280'>%s</ul>" % failed)
            if failed else '<span style="color:#10b981;font-weight:700">✓ 全部调用成功</span>',
        )
    )

    parts.append(
        '<footer>由 <b>mcd-expiry-ledger</b> 生成 · 数据来自 McDonald\'s China 官方 MCP Server<br>'
        '金额为按券面值与积分折算的排序估算，不构成任何价格承诺 · © 2026</footer>'
        '</div></body></html>'
    )
    return "".join(parts)
