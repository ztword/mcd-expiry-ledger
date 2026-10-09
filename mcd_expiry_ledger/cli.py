"""Command line entry points: demo / scan / ping / tools.

    python -m mcd_expiry_ledger demo     # no token needed
    python -m mcd_expiry_ledger ping     # check your MCP connection
    python -m mcd_expiry_ledger scan     # real account sweep -> report.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .client import DEFAULT_ENDPOINT, McpClient, McpError
from .demo import DemoClient
from .ledger import LedgerEngine
from .report import render_html

__all__ = ["main", "build_engine", "run"]

TOKEN_ENV = "MCD_MCP_TOKEN"


def build_engine(token: str, endpoint: str, demo: bool) -> LedgerEngine:
    if demo or not token:
        return LedgerEngine(DemoClient())
    return LedgerEngine(McpClient(token=token, endpoint=endpoint))


def run(token: str = "", endpoint: str = DEFAULT_ENDPOINT, demo: bool = False,
        top: int = 8) -> Dict[str, Any]:
    """Execute a full ledger sweep and return the structured result."""
    engine = build_engine(token, endpoint, demo)
    result = engine.scan()
    plan = engine.build_plan(result, top=top)
    return {"result": result, "plan": plan}


def _write_report(result: Any, plan: List[Dict[str, Any]], path: str) -> str:
    html = render_html(result, plan)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return path


def _print_console(result: Any, plan: List[Dict[str, Any]], quiet: bool = False) -> None:
    if quiet:
        return
    line = "─" * 62
    print(line)
    print("  麦麦到期清单 · mcd-expiry-ledger")
    print(line)
    if isinstance(getattr(result, "tools_ok", None), list) and result.tools_ok:
        if "sandbox" in " ".join(result.tools_ok) or isinstance(
                getattr(result, "account_snapshot", {}), dict):
            pass
    print("  待清算总额    ¥%.2f" % result.total_value)
    print("  7天内将蒸发   ¥%.2f" % result.at_risk_value)
    print("  资产总数      %d 项（其中 %d 项已过期）"
          % (len(result.assets), result.dead_count))
    print(line)
    header = "  %-3s %-34s %10s  %s" % ("#", "资产", "估值", "紧迫度")
    print(header)
    print(line)
    for item in plan:
        name = ("%s %s" % (item["icon"], item["asset"]))[:32]
        print("  %-3d %-34s ¥%9.2f  %s"
              % (item["step"], name, item["value"], item["urgency"]))
    print(line)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcd-expiry-ledger",
        description="麦麦到期清单：把麦当劳账户里所有会过期的东西放到一张倒计时表上。",
    )
    parser.add_argument("command", nargs="?", default="demo",
                        choices=["demo", "scan", "ping", "tools"],
                        help="demo=无 Token 演示（默认）；scan=真实账户扫描；"
                             "ping=连通性自检；tools=列出可用工具")
    parser.add_argument("--token", default=os.environ.get(TOKEN_ENV, ""),
                        help="麦当劳 MCP Token，也可设环境变量 %s" % TOKEN_ENV)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help="MCP Server 地址，默认 %s" % DEFAULT_ENDPOINT)
    parser.add_argument("--out", default="mcd-expiry-report.html",
                        help="HTML 报告输出路径")
    parser.add_argument("--json", dest="as_json", default="",
                        help="同时输出 JSON 到指定路径")
    parser.add_argument("--top", type=int, default=8, help="清算计划条数")
    parser.add_argument("--quiet", action="store_true", help="只写文件不打印")
    args = parser.parse_args(argv)

    try:
        if args.command == "ping":
            if not args.token:
                print("× 缺少 MCP Token（用 --token 或设置环境变量 %s）" % TOKEN_ENV)
                print("  申请地址：https://open.mcd.cn/mcp")
                return 2
            info = McpClient(args.token, args.endpoint).ping()
            print("✓ 已连接 %s" % info["endpoint"])
            print("  服务端：%s" % info.get("server"))
            print("  工具数：%d" % info["tool_count"])
            for name in info["tools"]:
                print("    · %s" % name)
            return 0

        if args.command == "tools":
            names = McpClient(args.token or "demo", args.endpoint).list_tools() \
                if args.token else DemoClient().list_tools()
            for item in names:
                print("· %s" % (item.get("name") if isinstance(item, dict) else item))
            return 0

        demo_mode = (args.command == "demo") or not args.token
        if args.command == "scan" and not args.token:
            print("! scan 需要 Token，本次自动回落到 demo 沙箱")
            print("  申请地址：https://open.mcd.cn/mcp\n")

        bundle = run(args.token, args.endpoint, demo=demo_mode, top=args.top)
        result, plan = bundle["result"], bundle["plan"]

        if demo_mode:
            print("ℹ demo 沙箱模式：数据为虚构用例，用于展示完整链路\n")

        _print_console(result, plan, quiet=args.quiet)
        path = _write_report(result, plan, args.out)
        if not args.quiet:
            print("\n  HTML 报告 → %s" % path)
        if args.as_json:
            with open(args.as_json, "w", encoding="utf-8") as handle:
                json.dump(result.to_dict(), handle, ensure_ascii=False, indent=2)
            if not args.quiet:
                print("  JSON 数据  → %s" % args.as_json)
        return 0

    except McpError as exc:
        print("\n× MCP 调用失败：%s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
