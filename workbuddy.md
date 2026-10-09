# workbuddy.md — WorkBuddy 开发对话上下文（专项奖励材料）

本项目从选题、架构设计到代码实现，全程在腾讯 WorkBuddy 中完成。本文档按要求保留开发过程的关键对话上下文。

## 项目信息

- **项目名称**：麦麦到期清单（mcd-expiry-ledger）
- **开发工具**：腾讯 WorkBuddy（Agent 模式）
- **开发周期**：2026-10-09 单日完成选题 → 调研 → 开发 → 文档 → 参赛提交
- **仓库**：https://github.com/ztword/mcd-expiry-ledger

## 开发对话记录（关键节点摘录）

### 1. 选题阶段 — 竞争情报驱动决策

> **用户**：理解征文内容：https://builderx.csdn.net/activity-site/m-code/pages?utm_medium=ad.590
>
> **WorkBuddy**：解析出活动全貌——基于麦当劳 MCP 开发 Skill、开源至 GitHub、按 Star 数排名、10月25日截止、前 100 名有奖、用 WorkBuddy 开发另有 3000 AI 积分。
>
> **用户**：直接帮我开发能够拿奖的项目
>
> **WorkBuddy**：没有直接写代码，而是先做了完整的竞争情报收集：
> - 拉取官方 `M-China/mcd-mcp-server` 仓库，得到全部 33 个 MCP 工具清单及版本日志；
> - 拉取大赛仓库 `RANKING.md`，发现开赛首日第一名仅 19 Star；
> - 拉取全部 149 个参赛 Issue 标题做竞争分析，识别出 4 大红海（省钱类 25+、营养类 15+、点餐类 20+、人格/wrapped 类 15+）与真正的蓝海（`query-lottery-info` / `query-my-prizes` / `mall-points-products` / `available-coupons` 等工具几乎无人深度使用）。
>
> **结论**：不做"第 26 个省钱助手"。做"账户里所有会过期的东西"的统一清算视图——一个覆盖 8 个工具、含 5 个稀缺工具的资产生命周期引擎。

### 2. 架构决策（WorkBuddy 提出并执行）

1. **零依赖**：MCP Streamable HTTP 客户端用 `urllib` 手写（含 SSE 解析、Session 续传、401/429 语义化报错），不引入任何第三方包。理由：评审 clone 下来第一分钟就能跑，依赖安装是最沉默的劝退环节。
2. **Demo 沙箱**：内置虚构数据源，无 Token 离线演示完整链路。理由：绝大多数参赛项目 clone 后先撞 401——把体验门槛降到零，才留得住随手给 Star 的人。
3. **估值公式**：`priority = 价值(元) × 紧迫度权重`，积分按 100 积分≈1 元折算（仅排序用），抽奖按奖品池期望值折算。
4. **降级不中断**：任何单个工具失败只进入报告"降级明细"，扫描继续。
5. **只读边界**：绝不静默调用 `draw-lottery` / `create-order` 等真实消耗工具，只在计划中给出建议。

### 3. 实现产出（全部由 WorkBuddy 在本会话内生成）

| 模块 | 说明 |
|---|---|
| `client.py` | 零依赖 MCP 客户端（SSE / Session / 错误语义） |
| `ledger.py` | 资产生命周期引擎（6 类资产归一化、估值、清算计划） |
| `report.py` | 自包含 HTML 报告（内联 CSS + 手写 SVG 环图） |
| `demo.py` | 无 Token 离线沙箱 |
| `cli.py` | `demo` / `scan` / `ping` / `tools` 四个子命令 |

验证：`python -m mcd_expiry_ledger demo` 全链路跑通，8 个工具调用全部成功、0 失败，输出待清算总额 ¥643.70 / 7 天内将蒸发 ¥424.50 / 20 项资产（含 1 项已过期识别）。

### 4. 参赛文件清单（WorkBuddy 生成）

- `README.md`（含竞争分析依据的项目定位）
- `CONTEST_DECLARATION.md`（原创性/合规性/敏感信息声明）
- `MCP_INTEGRATION.md`（8 工具调用明细与业务价值）
- `mcp-config.example.json`（脱敏配置）
- `SKILL.md`（标准 Skill 描述）
- 本文件 `workbuddy.md`

## 一句话总结

WorkBuddy 在这个项目里承担了**竞争情报分析 → 差异化选题 → 架构决策 → 全量编码 → 文档工程 → 参赛提交**的完整链路，是一个从 0 到 1 的真实开发案例，而非代码补全工具。
