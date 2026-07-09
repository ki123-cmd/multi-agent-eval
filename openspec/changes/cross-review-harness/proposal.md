## Why

我们要回答的问题是「Claude Code 与 Codex 的多智能体协作，收益是否抵得上成本」。目前公开材料无法回答它：`arXiv 2603.12123` 用**同一个模型**证明了收益来自**上下文隔离**，但它没有跨模型臂；而所有声称「跨模型多抓 40–60% 问题」的数字都溯源到无方法论的内容营销。**没人跑过「跨模型 vs 同模型隔离」的对照实验。**

同时，本机存在一个会让实验数据全部作废的静默故障：Codex 在 Windows 沙箱下起子进程失败（`CreateProcessWithLogonW failed: 1385`），却以退出码 0 返回 schema 合规的假 `FAIL`。任何依赖 Codex 自主读文件的方案（含官方插件）在本机都不可信。

## What Changes

- 新增 harness，把评审固化为**可复现、可判定、防静默故障**的脚本流程
- 所有评审者一律 **push 上下文**（stdin 灌入），prompt 明令禁止工具调用；**BREAKING**：不得使用 `codex exec review` / `/codex:review` 等依赖 Codex 自读文件的路径
- 新增 **canary 字段**：评审者必须回报只有真正读到 diff 才能得出的事实（首个变更文件名、变更文件数）。答错 → 本次运行判定 `INVALID`，不计入统计
- 复用 `withmartian/code-review-benchmark`（MIT）的 136 条 golden comments 作为真值集，不自建 fixture
- 评审输入以 **sha256 锚定**：同一 item 的所有臂必须看到逐字节相同的 package
- 裁判使用**第三方模型**（既非 Claude 亦非 Codex），并保留人工抽检

## Capabilities

### New Capabilities
- `review-package`: 从真实 PR 构造逐字节可复现的评审输入包
- `reviewer-adapter`: 以对称参数驱动 Claude / Codex 评审者，产出结构化 verdict
- `verdict-validation`: canary 校验与 schema 校验，把静默故障转为硬失败
- `experiment-runner`: 多臂实验编排、重复采样与指标落盘

### Modified Capabilities
（无，本仓库此前无 spec）

## Impact

- 新增 `harness/` 代码与 `harness/schema/verdict.schema.json`
- 依赖：`codex-cli 0.143.0`、`claude 2.1.205`、Python 3.10、公开 GitHub API（免认证）
- 外部数据：`withmartian/code-review-benchmark`（MIT，需单独 clone，不 vendored）
- **不依赖** Docker、MCP、`codex-plugin-cc`
