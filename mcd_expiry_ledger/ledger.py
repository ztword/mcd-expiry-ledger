"""Asset lifecycle engine: scan, normalise, value, and liquidate.

Everything in a McDonald's China account decays:
    coupons     expire by date
    points      expire at the end of a window, sometimes revoked wholesale
    lotteries   have free draws that silently reset every period
    prizes      must be claimed before the claim window closes
    campaigns   only pay off while they are running

Nobody had ever put those five clocks on one page before.  This module does.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

__all__ = [
    "Asset", "ScanResult", "LedgerEngine",
    "POINTS_PER_YUAN", "URGENCY_BANDS",
]

# ----------------------------------------------------------------- constants

#: Rough redemption power of one McDonald's point, used only to rank things
#: against each other.  Configurable so nobody mistakes this for a price promise.
POINTS_PER_YUAN = 100.0

#: (max days left, label, css tier, weight) sorted ascending.
URGENCY_BANDS: List[tuple] = [
    (0,     "已过期",    "dead",   0.0),
    (1,     "今天到期",  "critical", 10.0),
    (3,     "72小时",    "critical", 8.0),
    (7,     "本周",      "warn",     5.0),
    (14,    "两周内",    "warn",     3.0),
    (30,    "本月内",    "steady",   1.5),
    (10**6, "安全期",    "calm",     1.0),
]

_KIND_META = {
    "coupon":       ("优惠券",   "🎟️", "直接使用 / 随单核销"),
    "point":        ("积分",     "🪙", "积分商城兑换实物或虚拟商品"),
    "lottery":      ("抽奖机会", "🎰", "消耗次数的免费抽奖"),
    "prize":        ("已中奖品", "🎁", "在有效期内领取"),
    "mall_product": ("可兑商品", "🛍️", "积分兑换下单"),
    "campaign":     ("进行中活动", "📅", "活动窗口内参与"),
}

_DATE_PATTERNS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%Y.%m.%d", "%Y年%m月%d日",
]


def parse_when(value: Any) -> Optional[datetime]:
    """Best-effort date parser tolerant of every shape the MCP tools return."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text[:len(pattern) + 4], pattern)
        except ValueError:
            continue
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)),
                            int(match.group(3)))
        except ValueError:
            return None
    return None


def urgency_of(days_left: Optional[float]) -> tuple:
    """Map remaining days onto a fixed urgency band."""
    if days_left is None:
        return ("未知", "calm", 1.0)
    if days_left < 0:
        return URGENCY_BANDS[0][1], URGENCY_BANDS[0][2], URGENCY_BANDS[0][3]
    for limit, label, tier, weight in URGENCY_BANDS[1:]:
        if days_left <= limit:
            return label, tier, weight
    return URGENCY_BANDS[-1][1], URGENCY_BANDS[-1][2], URGENCY_BANDS[-1][3]


# ------------------------------------------------------------------ datamodel


@dataclass
class Asset:
    """One decaying thing in the account, normalised across all sources."""

    kind: str
    source_tool: str
    title: str
    detail: str = ""
    value: float = 0.0          # estimated CNY worth
    quantity: int = 1
    expires_at: Optional[datetime] = None
    action: str = ""
    action_tool: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    # -- derived -------------------------------------------------------------

    @property
    def days_left(self) -> Optional[float]:
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now()
        return round(delta.total_seconds() / 86400.0, 2)

    @property
    def days_left_int(self) -> Optional[int]:
        value = self.days_left
        return None if value is None else int(value)

    @property
    def urgency(self) -> tuple:
        return urgency_of(self.days_left)

    @property
    def urgency_label(self) -> str:
        return self.urgency[0]

    @property
    def urgency_tier(self) -> str:
        return self.urgency[1]

    @property
    def priority(self) -> float:
        """Ranking score: worth multiplied by how fast it is burning."""
        _, _, weight = self.urgency
        return round(self.value * weight, 2)

    @property
    def kind_label(self) -> str:
        return _KIND_META.get(self.kind, (self.kind, "•", ""))[0]

    @property
    def kind_icon(self) -> str:
        return _KIND_META.get(self.kind, ("", "•", ""))[1]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        data["days_left"] = self.days_left_int
        data["urgency"] = self.urgency_label
        data["urgency_tier"] = self.urgency_tier
        data["priority"] = self.priority
        data["expires_at"] = (self.expires_at.strftime("%Y-%m-%d")
                              if self.expires_at else None)
        return data


@dataclass
class ScanResult:
    assets: List[Asset] = field(default_factory=list)
    tools_ok: List[str] = field(default_factory=list)
    tools_failed: Dict[str, str] = field(default_factory=dict)
    account_snapshot: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # -- aggregates ----------------------------------------------------------

    @property
    def total_value(self) -> float:
        return round(sum(a.value * (a.quantity or 1) for a in self.assets), 2)

    @property
    def expiring_7d(self) -> List[Asset]:
        return [a for a in self.assets
                if a.days_left is not None and 0 <= a.days_left <= 7]

    @property
    def expiring_30d(self) -> List[Asset]:
        return [a for a in self.assets
                if a.days_left is not None and 0 <= a.days_left <= 30]

    @property
    def at_risk_value(self) -> float:
        """Money that evaporates if you do nothing for a week."""
        return round(sum(a.value * (a.quantity or 1) for a in self.expiring_7d), 2)

    @property
    def dead_count(self) -> int:
        return len([a for a in self.assets
                    if a.days_left is not None and a.days_left < 0])

    def by_kind(self) -> Dict[str, List[Asset]]:
        buckets: Dict[str, List[Asset]] = {}
        for asset in self.assets:
            buckets.setdefault(asset.kind, []).append(asset)
        return buckets

    def sorted_assets(self) -> List[Asset]:
        return sorted(self.assets, key=lambda a: (-a.priority, str(a.expires_at)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "summary": {
                "total_value": self.total_value,
                "at_risk_value": self.at_risk_value,
                "asset_count": len(self.assets),
                "expiring_7d": len(self.expiring_7d),
                "expiring_30d": len(self.expiring_30d),
                "dead_count": self.dead_count,
            },
            "tools_ok": self.tools_ok,
            "tools_failed": self.tools_failed,
            "account_snapshot": self.account_snapshot,
            "assets": [a.to_dict() for a in self.sorted_assets()],
        }


# ----------------------------------------------------------------- extraction


def _as_list(payload: Any, *keys: str) -> List[Dict[str, Any]]:
    """Drill into the many envelope shapes the MCP tools use."""
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    candidates: List[Any] = [payload]
    for _ in range(4):
        nxt: List[Any] = []
        for item in candidates:
            if isinstance(item, dict):
                hit = False
                for key in keys:
                    if key in item:
                        nxt.append(item[key])
                        hit = True
                if not hit:
                    nxt.extend(item.values())
            elif isinstance(item, list):
                nxt.extend(item)
        if not nxt:
            break
        candidates = nxt
        found = [x for x in candidates if isinstance(x, list)]
        if found:
            flat: List[Dict[str, Any]] = []
            for group in found:
                flat.extend([x for x in group if isinstance(x, dict)])
            if flat:
                return flat
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _pick(record: Dict[str, Any], *names: str, default: Any = None) -> Any:
    lowered = {str(k).lower(): v for k, v in record.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, ""):
            return lowered[name.lower()]
    return default


def _money(record: Dict[str, Any], *names: str) -> float:
    raw = _pick(record, *names)
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw)
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else 0.0


# --------------------------------------------------------------------- engine


class LedgerEngine:
    """Turns raw MCP payloads into a single, ranked, decaying asset ledger."""

    def __init__(self, client: Any, points_per_yuan: float = POINTS_PER_YUAN) -> None:
        self.client = client
        self.points_per_yuan = points_per_yuan

    # -- individual scanners -------------------------------------------------

    def _scan_coupons(self, result: ScanResult) -> None:
        payload = self.client.call_tool("query-my-coupons", safe=True)
        for record in _as_list(payload, "coupons", "list", "data", "items"):
            expires = parse_when(_pick(record, "endTime", "expireTime",
                                       "validEndTime", "endDate", "expireDate",
                                       "有效期至", "失效时间"))
            value = _money(record, "faceValue", "discount", "amount",
                           "couponValue", "面值", "优惠金额")
            result.assets.append(Asset(
                kind="coupon",
                source_tool="query-my-coupons",
                title=str(_pick(record, "couponName", "name", "title",
                                "券名称", default="未命名优惠券")),
                detail=str(_pick(record, "description", "rule", "desc",
                                 "使用规则", default="")),
                value=value or 5.0,
                quantity=int(_money(record, "count", "quantity", "数量") or 1),
                expires_at=expires,
                action="点单时用掉它（calculate-price 会自动判可用性）",
                action_tool="calculate-price",
                raw=record,
            ))
        result.tools_ok.append("query-my-coupons")

        # Store-scoped coupons only appear when a store context exists.
        scoped = self.client.call_tool("query-store-coupons", safe=True)
        for record in _as_list(scoped, "coupons", "list", "data"):
            expires = parse_when(_pick(record, "endTime", "expireTime",
                                       "validEndTime", "endDate"))
            result.assets.append(Asset(
                kind="coupon",
                source_tool="query-store-coupons",
                title=str(_pick(record, "couponName", "name", "title",
                                default="门店券")),
                detail="仅当前门店可用" + str(_pick(record, "description",
                                                 "rule", default="")),
                value=_money(record, "faceValue", "discount", "amount") or 5.0,
                expires_at=expires,
                action="在这家门店点单时核销",
                action_tool="calculate-price",
                raw=record,
            ))
        result.tools_ok.append("query-store-coupons")

        # Claimable-but-unclaimed coupons are the purest form of free money.
        claimable = self.client.call_tool("available-coupons", safe=True)
        claimed = 0
        for record in _as_list(claimable, "coupons", "list", "data"):
            expires = parse_when(_pick(record, "endTime", "expireTime",
                                       "validEndTime", "endDate"))
            result.assets.append(Asset(
                kind="coupon",
                source_tool="available-coupons",
                title=str(_pick(record, "couponName", "name", "title",
                                default="待领券")),
                detail="还没领到手里 —— 《麦麦省》可一键领取",
                value=_money(record, "faceValue", "discount", "amount") or 5.0,
                expires_at=expires,
                action="auto-bind-coupons 一键领取",
                action_tool="auto-bind-coupons",
                raw=record,
            ))
            claimed += 1
        if claimed:
            result.account_snapshot["claimable_coupons"] = claimed
        result.tools_ok.append("available-coupons")

    def _scan_points(self, result: ScanResult) -> None:
        payload = self.client.call_tool("query-my-account", safe=True)
        record = payload if isinstance(payload, dict) else {}
        if isinstance(payload, list) and payload:
            record = payload[0] if isinstance(payload[0], dict) else {}
        for key, value in record.items():
            if isinstance(value, (int, float)):
                result.account_snapshot[key] = value

        usable = _money(record, "availablePoints", "usablePoints", "points",
                        "可用积分", "积分")
        expiring_soon = _money(record, "expiringPoints", "expirePoints",
                               "即将过期积分", "soonExpirePoints")
        expire_at = parse_when(_pick(record, "pointsExpireTime", "expireTime",
                                     "过期时间"))

        if usable:
            result.assets.append(Asset(
                kind="point",
                source_tool="query-my-account",
                title="可用积分 %.0f" % usable,
                detail="按 %d 积分 ≈ 1 元折算可用于排序" % int(self.points_per_yuan),
                value=round(usable / self.points_per_yuan, 2),
                quantity=1,
                expires_at=expire_at,
                action="去麦麦商城兑换，别等积分清零",
                action_tool="mall-points-products",
                meta={"points": usable},
                raw=record,
            ))
        if expiring_soon:
            result.assets.append(Asset(
                kind="point",
                source_tool="query-my-account",
                title="即将过期积分 %.0f" % expiring_soon,
                detail="这部分最先被回收 —— 优先消耗",
                value=round(expiring_soon / self.points_per_yuan, 2),
                quantity=1,
                expires_at=expire_at,
                action="优先兑换掉，它们的倒计时最短",
                action_tool="mall-create-order",
                meta={"points": expiring_soon, "sub_type": "expiring"},
                raw=record,
            ))
        result.tools_ok.append("query-my-account")

    def _scan_lottery(self, result: ScanResult) -> None:
        info = self.client.call_tool("query-lottery-info", safe=True)
        record = info if isinstance(info, dict) else {}
        if isinstance(info, list) and info:
            record = info[0] if isinstance(info[0], dict) else {}

        free_draws = _money(record, "freeDrawCount", "drawCount", "freeTimes",
                            "availableTimes", "剩余抽奖次数", "抽奖次数")
        expires = parse_when(_pick(record, "endTime", "activityEndTime",
                                   "endDate", "活动结束时间"))
        prizes = _as_list(record, "prizeList", "prizes", "奖品列表")
        expected = 0.0
        if prizes:
            total = sum(_money(p, "value", "price", "faceValue", "市场价") or 0
                        for p in prizes)
            ratio = sum(_money(p, "probability", "rate", "chance", "中奖概率")
                        or 0 for p in prizes)
            # Fall back to a uniform prior when the pool hides its odds.
            expected = total * (ratio / 100.0 if ratio > 1 else 1.0 / len(prizes))

        if free_draws or _pick(record, "status", "activityStatus"):
            result.assets.append(Asset(
                kind="lottery",
                source_tool="query-lottery-info",
                title="免费抽奖 %.0f 次" % free_draws,
                detail="奖品池 %d 项，换算期望价值 ¥%.2f / 次" % (len(prizes), expected),
                value=round(expected * max(free_draws, 0), 2),
                quantity=int(free_draws or 0),
                expires_at=expires,
                action="次数通常按周期重置 —— 过期作废，今天就抽掉",
                action_tool="draw-lottery",
                meta={"prize_pool": len(prizes), "expected_each": round(expected, 2)},
                raw=record,
            ))
        result.tools_ok.append("query-lottery-info")

        won = self.client.call_tool("query-my-prizes", safe=True)
        for record in _as_list(won, "prizes", "list", "data", "records"):
            expires = parse_when(_pick(record, "claimEndTime", "expireTime",
                                       "endTime", "领取截止时间", "有效期至"))
            result.assets.append(Asset(
                kind="prize",
                source_tool="query-my-prizes",
                title=str(_pick(record, "prizeName", "name", "title",
                                "奖品名称", default="已中奖品")),
                detail=str(_pick(record, "claimRule", "description", "desc",
                                 default="中奖后需要在窗口内领取")),
                value=_money(record, "value", "price", "faceValue", "市场价") or 10.0,
                expires_at=expires,
                action="已中奖别忘领 —— 逾期等于没中",
                action_tool=None,
                raw=record,
            ))
        result.tools_ok.append("query-my-prizes")

    def _scan_mall(self, result: ScanResult) -> None:
        products = self.client.call_tool("mall-points-products", safe=True)
        for record in _as_list(products, "products", "list", "data", "items"):
            points = _money(record, "points", "pointPrice", "needPoints",
                            "所需积分", "兑换积分")
            expires = parse_when(_pick(record, "endTime", "offShelfTime",
                                       "activityEndTime", "endDate"))
            result.assets.append(Asset(
                kind="mall_product",
                source_tool="mall-points-products",
                title=str(_pick(record, "productName", "name", "title",
                                "商品名称", default="商城商品")),
                detail="%.0f 积分可兑" % points,
                value=round(points / self.points_per_yuan, 2),
                quantity=1,
                expires_at=expires,
                action="库存有限的商品会提前下架，看准就兑",
                action_tool="mall-create-order",
                meta={"points": points},
                raw=record,
            ))
        result.tools_ok.append("mall-points-products")

    def _scan_campaigns(self, result: ScanResult) -> None:
        payload = self.client.call_tool("campaign-calendar", safe=True)
        for record in _as_list(payload, "campaigns", "activities", "list",
                               "data", "items"):
            status = str(_pick(record, "status", "activityStatus", "状态",
                               default="")).lower()
            if status and status not in ("进行中", "ongoing", "running",
                                         "processing", "1", "in_progress"):
                continue
            expires = parse_when(_pick(record, "endTime", "endDate",
                                       "活动结束时间", "结束时间"))
            result.assets.append(Asset(
                kind="campaign",
                source_tool="campaign-calendar",
                title=str(_pick(record, "campaignName", "activityName",
                                "name", "title", "活动名称", default="进行中活动")),
                detail=str(_pick(record, "description", "desc", "简介",
                                 default="活动日历中的进行中条目")),
                value=_money(record, "value", "benefit", "面值") or 8.0,
                expires_at=expires,
                action="活动窗口关闭后权益同时失效",
                action_tool=None,
                raw=record,
            ))
        result.tools_ok.append("campaign-calendar")

    # -- public API ----------------------------------------------------------

    def scan(self) -> ScanResult:
        """Run the full sweep, tolerating any tool that refuses to answer."""
        result = ScanResult()
        scanners: List[tuple] = [
            ("_scan_coupons", self._scan_coupons),
            ("_scan_points", self._scan_points),
            ("_scan_lottery", self._scan_lottery),
            ("_scan_mall", self._scan_mall),
            ("_scan_campaigns", self._scan_campaigns),
        ]
        for label, func in scanners:
            try:
                func(result)
            except Exception as exc:  # noqa: BLE001
                result.tools_failed[label] = "%s: %s" % (type(exc).__name__, exc)
        result.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    def build_plan(self, result: ScanResult, top: int = 8) -> List[Dict[str, Any]]:
        """Produce an ordered, executable liquidation plan."""
        plan: List[Dict[str, Any]] = []
        for asset in result.sorted_assets()[:top]:
            if asset.days_left is not None and asset.days_left < 0:
                continue
            label, _, _ = asset.urgency
            plan.append({
                "step": len(plan) + 1,
                "asset": asset.title,
                "kind": asset.kind_label,
                "icon": asset.kind_icon,
                "value": asset.value,
                "urgency": label,
                "days_left": asset.days_left_int,
                "action": asset.action,
                "tool": asset.action_tool,
            })
        claimable = result.account_snapshot.get("claimable_coupons", 0)
        if claimable:
            pending = [a for a in result.assets
                       if a.source_tool == "available-coupons"]
            pending_value = round(sum(a.value * (a.quantity or 1)
                                      for a in pending), 2)
            plan.insert(0, {
                "step": 0,
                "asset": "%d 张待领券" % claimable,
                "kind": "优惠券",
                "icon": "🎟️",
                "value": pending_value,
                "urgency": "立刻",
                "days_left": 0,
                "action": "先一键领取，再谈别的",
                "tool": "auto-bind-coupons",
            })
        for index, item in enumerate(plan):
            item["step"] = index + 1
        return plan
