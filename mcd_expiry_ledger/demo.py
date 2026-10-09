"""Demo mode: a fully synthetic, no-token sandbox that exercises every code path.

Why this exists
---------------
Almost every other entry in the contest needs a personal MCP token before it can
show *anything*.  That is a terrible first impression: a star-giver clones the
repo, hits a 401, and leaves.

``python -m mcd_expiry_ledger demo`` boots a fake in-process MCP server that
returns realistic (but entirely invented) payloads, so the pipeline can be seen
end to end with zero credentials and zero network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

__all__ = ["DemoClient", "build_snapshot"]

_NOW = datetime.now()


def _d(days: float) -> str:
    return (_NOW + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def build_snapshot() -> Dict[str, Dict[str, Any]]:
    """Return the canned tool responses keyed by MCP tool name."""
    return {
        "query-my-coupons": {
            "coupons": [
                {"couponId": "CN-8821", "couponName": "麦辣鸡腿堡买一送一",
                 "faceValue": 21.5, "count": 1, "endTime": _d(1.2),
                 "description": "限正餐时段使用，不可与其他优惠叠加"},
                {"couponId": "CN-7734", "couponName": "早餐套餐立减 ¥6",
                 "faceValue": 6.0, "count": 2, "endTime": _d(3.5),
                 "description": "每日 05:00-10:30 可用"},
                {"couponId": "CN-6610", "couponName": "麦乐送免配送费",
                 "faceValue": 7.0, "count": 1, "endTime": _d(9.0),
                 "description": "满 ¥25 可用"},
                {"couponId": "CN-5590", "couponName": "甜筒兑换券",
                 "faceValue": 6.5, "count": 1, "endTime": _d(23.0),
                 "description": "任意消费后可 6.5 元换购"},
                {"couponId": "CN-4401", "couponName": "薯条免费升级大份",
                 "faceValue": 4.0, "count": 1, "endTime": _d(58.0),
                 "description": "升级大份薯条"},
                {"couponId": "CN-3390", "couponName": "已过期咖啡券",
                 "faceValue": 9.0, "count": 1, "endTime": _d(-2.0),
                 "description": "这张是故意留下的，用来展示过期识别"},
            ]
        },
        "query-store-coupons": {
            "coupons": [
                {"couponId": "ST-1002", "couponName": "本店限定·板烧鸡腿堡 ¥15.9",
                 "discount": 8.0, "endTime": _d(0.6),
                 "description": "仅该门店可用"},
            ]
        },
        "available-coupons": {
            "coupons": [
                {"couponId": "AB-2201", "couponName": "麦麦省·任意小食 ¥9.9",
                 "amount": 8.0, "endTime": _d(5.0)},
                {"couponId": "AB-2202", "couponName": "麦麦省·双人餐立减 ¥12",
                 "amount": 12.0, "endTime": _d(11.0)},
                {"couponId": "AB-2203", "couponName": "麦麦省·早餐组合 ¥8.8",
                 "amount": 5.0, "endTime": _d(16.0)},
            ]
        },
        "query-my-account": {
            "availablePoints": 4820,
            "usedPoints": 1260,
            "frozenPoints": 0,
            "expiringPoints": 1150,
            "pointsExpireTime": _d(12.0),
        },
        "query-lottery-info": {
            "status": "进行中",
            "activityEndTime": _d(6.0),
            "freeDrawCount": 3,
            "prizeList": [
                {"prizeName": "巨无霸兑换券", "value": 25, "probability": 5},
                {"prizeName": "免费薯条券", "value": 12, "probability": 15},
                {"prizeName": "积分 × 200", "value": 2, "probability": 40},
                {"prizeName": "谢谢参与", "value": 0, "probability": 40},
            ],
        },
        "query-my-prizes": {
            "prizes": [
                {"prizeName": "麦旋风免费券", "value": 12,
                 "claimEndTime": _d(2.0), "claimRule": "中奖后 7 天内需领取"},
                {"prizeName": "限定周边·汉堡钥匙扣", "value": 39,
                 "claimEndTime": _d(19.0), "claimRule": "需到店出示核销码"},
            ]
        },
        "mall-points-products": {
            "products": [
                {"productName": "麦麦懂食系列·薯条捏捏玩具", "points": 1500,
                 "endTime": _d(26.0)},
                {"productName": "限定汉堡回车键", "points": 3200,
                 "endTime": _d(8.0)},
                {"productName": "¥20 代金券（2000 积分）", "points": 2000,
                 "endTime": _d(41.0),
                 "offShelfTime": _d(41.0)},
            ]
        },
        "campaign-calendar": {
            "campaigns": [
                {"campaignName": "1+1=12 随心配", "status": "进行中",
                 "value": 12, "endTime": _d(4.0)},
                {"campaignName": "麦辣鸡腿堡第二份半价", "status": "进行中",
                 "value": 10, "endTime": _d(13.0)},
                {"campaignName": "早餐会员日", "status": "已结束",
                 "value": 8, "endTime": _d(-5.0)},
            ]
        },
    }


class DemoClient:
    """Drop-in replacement for ``McpClient`` with the same surface area."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.snapshot = build_snapshot()
        self.call_log: List[str] = []

    # mimic McpClient --------------------------------------------------------

    def initialize(self) -> Dict[str, Any]:
        return {"serverInfo": {"name": "mcd-demo-sandbox", "version": "1.0.0"}}

    def list_tools(self) -> List[Dict[str, Any]]:
        return [{"name": name} for name in self.snapshot]

    def ping(self) -> Dict[str, Any]:
        return {"endpoint": "demo://sandbox", "session": False,
                "server": "mcd-demo-sandbox", "tool_count": len(self.snapshot),
                "tools": list(self.snapshot)}

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                  safe: bool = False) -> Any:
        self.call_log.append(name)
        if name not in self.snapshot:
            if safe:
                return None
            raise KeyError("demo sandbox has no tool %r" % name)
        # Return a deep copy so callers can never mutate our fixtures.
        return json.loads(json.dumps(self.snapshot[name], ensure_ascii=False))
