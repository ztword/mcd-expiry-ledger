# MCP 集成说明 · MCP_INTEGRATION

本文档按大赛要求，说明「麦麦到期清单」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## 1. 接入方式

| 项 | 值 |
|---|---|
| Server | 麦当劳中国官方 MCP（远程托管） |
| Endpoint | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（JSON-RPC 2.0，支持 SSE 响应） |
| 鉴权 | `Authorization: Bearer <MCP_TOKEN>` + `Mcp-Session-Id` 会话续传 |
| 客户端实现 | `mcd_expiry_ledger/client.py`（标准库 `urllib` 手写，零第三方依赖） |

客户端细节：完整实现 `initialize` 握手（含 `notifications/initialized`）、`tools/list`、`tools/call`；同时兼容 `application/json` 与 `text/event-stream` 两种响应；对 401（Token 无效）、429（600 次/分钟限流）做了语义化报错。

## 2. 使用的 Tool 清单（8 个）

### 2.1 `query-my-coupons` — 我的优惠券

- **调用时机**：扫描第一步，读取账户全部已领券。
- **使用的字段**：`couponName`、`faceValue`、`count`、`endTime`、`description`。
- **业务价值**：券是账户里最容易"无声死亡"的资产，`endTime` 驱动倒计时，`faceValue` 折算成元参与优先级排序。

### 2.2 `query-store-coupons` — 门店限定券

- **调用时机**：紧跟全量券扫描，补充"仅某门店可用"的限定券。
- **业务价值**：这类券的可用面最窄、最容易被遗忘，单独标注"仅当前门店可用"。

### 2.3 `available-coupons` — 麦麦省可领券列表 🏷️

- **调用时机**：扫描"还没领到手里"的券。
- **业务价值**：**未领取的券是纯白嫖资产**——不需要消费就能锁定面值。项目把它列为清算计划第 0 步。

### 2.4 `auto-bind-coupons` — 一键领券 🏷️

- **调用时机**：清算计划第 0 步的执行工具（由用户在自己的 Agent 里确认后调用）。
- **设计边界**：本仓库只给出"应当执行"的建议，不静默调用任何产生真实消耗的工具。

### 2.5 `query-my-account` — 积分账户

- **使用的字段**：`availablePoints`、`expiringPoints`、`pointsExpireTime`。
- **业务价值**：把积分从"一个数字"变成"一笔会过期的钱"。`expiringPoints` 被单独拆成一条更高优先级的资产——即将过期的积分应当最先被消耗。

### 2.6 `query-lottery-info` — 积分抽奖活动信息 🏷️

- **使用的字段**：`freeDrawCount`、`activityEndTime`、`prizeList`（奖品面值与概率）。
- **业务价值**：免费抽奖次数**按周期重置、过期作废**。项目用奖品池计算每次抽奖的期望价值（Σ 面值 × 概率），再乘剩余次数，把"抽奖机会"变成可排序的资产。这是全仓库最有独创性的估值环节。

### 2.7 `query-my-prizes` — 已中奖品 🏷️

- **使用的字段**：`prizeName`、`claimEndTime`、`claimRule`、`value`。
- **业务价值**：中了没领 = 没中。`claimEndTime` 驱动领取倒计时，临近截止的奖品会以"72 小时"级紧迫度置顶。

### 2.8 `mall-points-products` — 麦麦商城商品 🏷️

- **使用的字段**：`productName`、`points`、`endTime`。
- **业务价值**：为"积分去哪"提供出口。商城商品的下架时间与"即将过期积分"交叉后，能生成"这 1150 个快过期的积分，正好够兑 XX"这类可执行建议。

### 2.9 `campaign-calendar` — 活动日历

- **调用时机**：读取当月活动日历，仅保留"进行中"条目。
- **业务价值**：活动权益（如 1+1 随心配）随活动窗口关闭而失效，被纳入同一张倒计时表。

> 🏷️ 标记的 5 个工具（`available-coupons` / `auto-bind-coupons` / `query-lottery-info` / `query-my-prizes` / `mall-points-products`）属于大赛多数参赛项目未覆盖的低频高价值工具。

## 3. 调用流程

```
initialize ──► notifications/initialized
     │
     ▼
tools/list（能力发现，供 ping 命令自检）
     │
     ▼ 以下 8 个 tools/call 逐个执行，safe 模式（单点失败不中断）
     │
     ├── query-my-coupons      ──► Asset[coupon]×N
     ├── query-store-coupons   ──► Asset[coupon·store]×N
     ├── available-coupons     ──► Asset[coupon·claimable]×N
     ├── query-my-account      ──► Asset[point]×2 + 账户快照
     ├── query-lottery-info    ──► Asset[lottery]（期望值估值）
     ├── query-my-prizes       ──► Asset[prize]×N
     ├── mall-points-products  ──► Asset[mall_product]×N
     └── campaign-calendar     ──► Asset[campaign]×N
     │
     ▼
统一归一化：Asset{kind, value, expires_at, source_tool}
     │
     ▼
priority = value × urgency_weight(days_left)   →  排序
     │
     ▼
清算计划（含每步应调用的 MCP 工具）+ 单文件 HTML 报告
```

## 4. 限流与健壮性

- 官方限制 600 次/分钟。本项目单次 `scan` 恰好 8 次 `tools/call` + 1 次 `initialize` + 1 次 `tools/list`，距离限流阈值有两个数量级的余量。
- `call_tool(..., safe=True)`：任何单个工具的失败（网络抖动、Token 权限缺失、字段结构变更）只进入报告的「降级明细」区，不中断整体扫描。
- 所有日期字段经多格式容错解析（`2026-10-25 23:59:59` / 时间戳 / `2026年10月25日` 等）。

## 5. 数据边界

- 只读账户资产类工具，不读取任何他人数据。
- 不调用 `create-order` / `party-order-create` / `draw-lottery` 等产生真实资金或权益消耗的写操作工具（仅在计划文本中建议用户自行确认后调用）。
- Token 与账户数据全程不落盘、不外发。
