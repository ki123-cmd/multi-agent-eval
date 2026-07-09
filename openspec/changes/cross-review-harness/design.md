## Context

本机实测（2026-07-09，`codex-cli 0.143.0`，Windows 11）：

| sandbox | Codex 能否读文件 |
|---|---|
| `read-only` | ❌ `CreateProcessWithLogonW failed: 1385` |
| `workspace-write` | ❌ 同上 |
| `danger-full-access` | ✅ |

坏的是沙箱机制本身。而评审者必须只读 —— 二者不可兼得，故 **push 上下文是本机唯一正确解**，并非性能优化。

## Goals / Non-Goals

**Goals**
- 让「跨模型 vs 同模型隔离」这个对照可被真实测量
- 让静默故障不可能通过校验

**Non-Goals**
- 不做自动合并、不做无限 review loop
- 第一版不接 MCP（会破坏可观测性，模型可能在未预期时自行调用）
- 不追求 bit-exact 复现（两个 CLI 均无 seed）

## Decisions

### 决策 1：push 上下文，禁止工具调用
两侧评审者都无工具。理由有二：本机沙箱故障；以及即便没有该故障，双评审也必须看到逐字节相同的输入，否则重合率无法归因。

### 决策 2：canary 字段
verdict 必须回报 `first_changed_file` / `changed_file_count`。这两个值只有真读了 diff 才知道。答错即 `INVALID`。

**这是本设计相对原方案的核心增量**：原方案依赖「schema 通过 + 退出码 0」判断成功，而实测证明这两者在静默故障下**同时成立**。

### 决策 3：复用而非自建真值集
采用 `withmartian/code-review-benchmark`（MIT）的 136 条 golden comments。
- 覆盖 5 个真实仓库（sentry / grafana / keycloak / discourse / cal.com）的 50 个 PR
- 无需 Docker，offline 模式仅需公开 GitHub API
- **已知局限**：golden comment 仅有 `comment` + `severity`，**无 file/line**，故命中判定只能靠语义匹配，裁判偏差无法完全消除
- **已知局限**：这批 PR 早于模型知识截止（2026-01），存在记忆污染风险。缓解：另用其 online 模式思路抽取截止日后的新 PR 作为第二批

### 决策 4：裁判用第三方模型
依据 arXiv 2404.13076 / 2410.21819：LLM 判官偏爱自己（及风格熟悉）的生成。故裁判不能是 Claude 或 Codex。
本机可用 `ollama` 上的 `gpt-oss:120b-cloud`。
**残余风险**：它仍是 OpenAI 血统，对 Codex 输出可能存在熟悉度偏好。必须以人工抽检校准，并报告 κ。

### 决策 5：样本量与重复次数
- 配对 McNemar 设计，检测 15–20pp 的 TPR 差异（α=0.05、80% power、3 组两两比较 Bonferroni 校正）需 **55–140 个 golden item**。136 条恰好落在区间内。
- 原方案的「20–30 条」只够做**试点**以估计不一致率 `p_disc`，不足以支撑定量结论。
- 每 item 重复 **8 次**起（依据 arXiv 2512.06710 的 ICC 收敛区间；复杂推理任务需 ≥32）。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| golden set 记忆污染 | 第二批用截止日后的新 PR；对比两批的 TPR 差异 |
| 裁判血统偏差 | 人工抽检 10–20% + 报告 κ；不用判官团（arXiv 2605.29800：9 判官只值约 2 票独立信息） |
| `claude -p` 无 schema 强制 | 记录 `schema_failure_rate` 并与 Codex 并列报告，不掩盖该不对称 |
| 成本不对称 | `claude -p` 单次带约 1.8 万 cache-creation token 的系统提示开销；成本指标须扣除固定开销后再比 |
| 「跨模型更强」实为「某模型更擅长评审」 | 必须跑镜像臂（Codex 实现 → Codex 隔离评审） |

## Migration Plan

harness 为新增，无迁移。已存在的 `/santa-loop` 不在本变更范围内，但其三个已知缺陷（静默降级、`-m gpt-5.4` 非最强、双 PASS 后自动 `git push`）应在复用前单独修复。

## Open Questions

- 第二批「截止日后 PR」的抽取标准如何固化，才能既新鲜又有可信真值？
- 上下文共享臂（自审）在 CRB 场景下无定义（评审者没写这份代码），是否需要单独的「先实现后评审」实验族来测隔离维度？
