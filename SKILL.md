---
name: mcd-expiry-ledger
description: 麦麦到期清单——扫描麦当劳中国账户里所有会过期的资产（券/积分/抽奖/奖品/活动），按"再等就会损失多少"排序，生成可执行的清算计划。基于官方 MCP，支持无 Token 演示模式。
---

# 麦麦到期清单（mcd-expiry-ledger）

## 何时使用本 Skill

当用户提到以下任何一类需求时使用：

- "麦当劳账户里有什么快过期了？"
- "我的积分/券/抽奖机会还能用多久？"
- "帮我把麦当劳的券都领了"
- "积分快过期了，该兑点什么？"
- "我中了什么奖品没领？"
- "给我一份麦当劳账户资产的清单/报告"

## 运行方式

本 Skill 是一个零依赖 Python 包，两种运行模式：

### 演示模式（无需任何凭据）

```bash
python -m mcd_expiry_ledger demo
```

内置离线沙箱（虚构数据），用于展示完整链路。首次接触本项目时先用它。

### 真实模式（需要用户自己的 MCP Token）

```bash
export MCD_MCP_TOKEN=用户的Token
python -m mcd_expiry_ledger scan          # 完整扫描 → mcd-expiry-report.html
python -m mcd_expiry_ledger ping          # 连通性自检
python -m mcd_expiry_ledger tools         # 列出可用工具
```

Token 申请地址：https://open.mcd.cn/mcp （登录 → 控制台 → 激活）
**永远不要向用户索要 Token 的明文值贴进对话**；引导用户设置环境变量。

## 产出物说明

- 终端：按优先级排序的清算清单（含估值与紧迫度）
- `mcd-expiry-report.html`：单文件可视化报告（倒计时条 / 构成环图 / 清算计划 / 工具溯源），可直接截图分享
- `--json data.json`：结构化数据输出

## 优先级算法

`priority = 价值(元) × 紧迫度权重`

| 剩余时间 | 权重 |
|---:|---:|
| ≤1 天 | ×10 |
| ≤3 天 | ×8 |
| ≤7 天 | ×5 |
| ≤14 天 | ×3 |
| ≤30 天 | ×1.5 |
| 更长 | ×1 |

积分按 100 积分 ≈ 1 元折算（仅用于排序）。抽奖按奖品池期望值（Σ 面值×概率）× 剩余次数估值。

## 安全边界（必须遵守）

1. **只读不写**：本 Skill 只调用查询类工具（`query-my-coupons` / `query-my-account` / `query-lottery-info` / `query-my-prizes` / `mall-points-products` / `campaign-calendar` / `available-coupons` / `query-store-coupons`）。
2. **写操作需确认**：清算计划中的 `auto-bind-coupons`（一键领券）、`draw-lottery`（抽奖）、`mall-create-order`（积分兑换）只作为"建议动作 + 工具名"输出。**在用户明确确认前，绝不能替用户执行这些工具。**
3. **凭据不落盘**：Token 仅经环境变量传入，不写入任何文件、日志或对话。
4. **失败降级**：单个工具失败不中断扫描，失败信息会出现在报告"降级明细"区，如实告知用户。
