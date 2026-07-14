# Shell 路径：协作场景与上下文传递实验设计

更新日期：2026-07-14

## 1. 实验目标

> **在 CC + Codex 协作中，采用什么协作场景、传递什么上下文，才能真正提升产出质量？**

**主问题**：交接包内容（Context Payload）如何影响跨模型协作的增益。

**为什么这是空白**：
- 已有工作证明「独立上下文 review 优于同上下文 self-review」（Cross-Context Review, arXiv 2603.12123），但**没有研究"独立上下文里应该放什么"**。
- 官方 Codex 插件的实际行为（只喂 `last_assistant_message`，连 diff 都没有）恰恰是上下文最贫瘠的一种，而它是事实上最多人用的路径——**这个 gap 本身就是研究动机**。
- 现有工程实现（metaswarm / claude-codex-collab / codex-review skill 等）都各自拍脑袋决定喂什么，**没有对照数据**。

---

## 2. 为什么固定用 shell-out

交互路径（shell-out / MCP / plugin）**不是本实验的自变量**——同一个 Codex + 同一份输入 = 同样的输出。路径固定为 shell-out 一条，预算全部投入到真正的研究问题上。

选 shell-out 的理由只有一个：**它是唯一能让我们完全控制自变量的通道。**

| 实验要求 | shell-out | plugin |
|---|---|---|
| 输入可控（能任意构造交接包） | ✅ 自己写文件 | ❌ 输入写死 |
| 输出可结构化（强制 JSON schema 便于打分） | ✅ | ❌ 自由文本 / `ALLOW:`\|`BLOCK:` |
| case 间零污染 | ✅ `--ephemeral` | ❌ app-server 会话 + `state.json` + `--resume-last` |

**plugin 为什么不能当实验台**（读 `codex@openai-codex` v1.0.6 源码得到的实况）：

- `commands/review.md:39` 明写 `does not support staged-only review, unstaged-only review, or extra focus text`——被审对象固定是 local git state，**注入不了自定义交接包**。而交接包正是本实验的自变量。
- `scripts/stop-review-gate-hook.mjs:48-57`：Stop hook 喂给 Codex 的**只有 `last_assistant_message`**，连 diff 都没有，Codex 得自己去仓库里翻。
- 输出契约写死为首行 `ALLOW:` / `BLOCK:`，拿不到结构化缺陷列表 → 因变量测不了。

**plugin 的两个"优势"在实验里都不成立**：

- *"hook 保证一定执行"*——实验里 runner 脚本才是触发器，`codex exec` 写在脚本里就是 100% 执行。何况 `review.md` / `transfer.md` 的 frontmatter 都是 `disable-model-invocation: true`，模型本来就不能自主调用。
- *"app-server 有会话记忆"*——这在实验里是**跨 case 污染源**，我们要的恰恰是 `--ephemeral`。

---

## 3. 实验因子

### 3.0 前置 Blocker：写审方向必须先钉死

已检索到 **《Cross-Model LLM Code Review: Should you use Claude to review Codex or vice versa?》**（Agentic SE @ KDD '26, 2026-08-10, Jeju；Xiang / Zhang / Zhang / Xu）。记法 `A`=Claude Opus 4.7、`O`=Codex GPT-5.5，两字母为「写者-审者」序（`AO` = Claude 写 + Codex 审）。

**二手摘要称：方向不对称——Codex 审 Claude 会把通过率从 91.4% 降到 82.8%，Claude 审 Codex 才是有效方向。**

⚠️ **证据强度**：论文存在性、会议、作者、AO/OA 记法已交叉确认；**上述数字仅来自搜索引擎对 ResearchGate 页面的摘要，原文 PDF 未取得，未经核实。**

**影响**：我们原设计的 `CC 改码 + Codex 评审` 正是 `AO`，即该文声称会掉分的方向。

**行动**：① 取得 PDF 核实；② 用小规模 pilot（≥20 case）自测 `AO` vs `OA`；③ 若不对称成立，把「写审方向」提为一级因子或直接改用占优方向。**不要默认沿用 AO。**

### 3.1 自变量 A：交接包内容 —— 主因子

对同一 case、同一份 CC 第一版产出，构造不同交接包给 Codex：

| 代号 | 交接包内容 | 对应现实 |
|---|---|---|
| `P0` | 仅 Claude 的自然语言回复（无 diff） | **官方插件 Stop hook 的实际行为**（劣势基线） |
| `P1` | 仅 diff | 最朴素的 review |
| `P2` | diff + 原始任务/需求描述 | 常见做法 |
| `P3` | diff + 任务 + 相关源文件全文 | 上下文加厚 |
| `P4` | diff + 任务 + **测试结果（含失败用例）** | 带执行证据 |
| `P5` | P4 + CC 自陈的「不确定点 / 已知风险」 | 主动暴露弱点 |
| `P6` | 不给 diff，只给任务 + 最终代码 | 去锚定，防 reviewer 被 diff 框住 |

**假设**：`P0` 显著劣于其他；`P4`/`P5` 最优；`P6` 可能发现 diff 之外的问题（对应 smoke 里 Codex 报出的 `-Infinity` 那类"测试没覆盖但真实存在"的缺陷）。

### 3.2 自变量 B：协作场景 —— 次因子

| 场景 | 协议定义 | 备注 |
|---|---|---|
| `Review` | CC 改 → Codex 只读评审 → CC 修正 | 已被 KDD'26 那篇覆盖，**降级为验证 harness 的基线场景** |
| `Consult` | CC 卡住/低置信时才问 Codex 一句，Codex 只给建议 | 触发条件如何定义是研究点 |
| `Handoff` | CC 做前半段 → 打包交接 → Codex 接手做完 | 交接包内容 = 自变量 A，天然耦合 |
| `Consensus` | CC + Codex **并行独立**评审同一产出 → 聚合共识/独家发现 | 记录重合率、独家发现率、误报率 |

先跑 `Review × P0..P6` 做出 A 的主效应，再扩展场景。

### 3.3 控制变量

- 路径固定 shell-out；Codex 调用固定 `codex exec --sandbox read-only --ephemeral`（**`--ephemeral` 是硬要求**）。
- 模型版本、温度、effort 固定并记录。
- 每个 case 从同一初始 commit 还原后开跑。

---

## 4. 指标

| 指标 | 定义 |
|---|---|
| 最终通过率 | 修正后代码是否过 hidden test |
| 修正收益 | 最终通过率 − CC 第一版通过率 |
| 真实缺陷检出数 | Codex 指出的、经第三方确认成立的问题数 |
| **测试盲区检出数** ⭐ | Codex 发现的、**hidden test 未覆盖但确实成立**的缺陷数 |
| 误报率 | Codex 提出但不成立、或采纳后导致负收益的比例 |
| 成本 | token / 时长 |

⭐ **「测试盲区检出数」是本实验最该看重的指标**：测试能抓到的 bug 谁都能发现，**测试抓不到的 bug 才是跨模型 reviewer 的真正价值**。smoke 里 Codex 报的空数组 `-Infinity` 就是这一类。

### 4.1 误报判定：绝不能让 CC 自己判

**当前 smoke 的方法论错误**：`aider-polyglot` case 中 Codex 提出 `-Infinity` 风险，**由 CC 自己判定为"超出任务边界"并记为 `possible_false_positive`**——让被审方当法官，会系统性高估误报率。

**替代方案**（优先级从高到低）：
1. **golden fix 比对**——BugsInPy 的 `-v 1` 就是官方修复版。
2. **第三方 LLM judge**——直接复用 `code-review-benchmark/offline/code_review_benchmark/step3_judge_comments.py`，别自己发明 judge。
3. 人工抽检，用于校准前两者。

---

## 5. 样本：难度筛选是当前唯一硬阻塞

**现状**：`review-eval/` 里 3 个 case 全是**照题型手搓的仿制品**，`CC-only` 3/3 全过 → **天花板效应，增益无处可测**。

**效应量校准**：Cross-Context Review 的 CCR F1 仅 **28.6%**（对比 SR 24.6% / SA 23.8%），用了 **30 artifacts / 150 injected errors / 360 reviews** 才做到 p=0.008。**跨模型协作的效应量本来就小——3 个 case 不可能看出任何东西。**

**筛选协议**：样本池换成 **BugsInPy 的 501 条真实历史 bug**（真实、难度天然分布、自带 golden fix），**停止手搓样本**。对每个候选 case 跑 `CC-only` **k = 5** 次：

| pass 次数 | 处置 |
|---|---|
| 5/5 | **丢弃**（天花板，零区分度） |
| 0/5 | 单独分组（地板效应） |
| **1/5 ~ 4/5** | **黄金样本**——协作增益唯一可能显现的区间 |

主指标随之变为：同一 case 上 `CC-only` 与 `CC+Codex` 的 pass rate 之差。天生带方差、可算显著性。

**门槛**：若黄金区间 < 20 个 case，说明 CC 在 BugsInPy 上要么太强要么太弱，**必须换数据集——这个结论要在建 runner 之前就知道。**

---

## 6. 工程底座：不要从零写 harness

| 现成资产 | 位置 | 用途 |
|---|---|---|
| `bugsinpy-checkout` / `-compile` / `-test` | `review-eval/sources/BugsInPy/framework/bin/` | **runner 底座**，脏活它全做完了 |
| BugsInPy `-v 1` | 同上 | **golden fix**，用于误报裁定 |
| `step3_judge_comments.py` | `review-eval/sources/code-review-benchmark/offline/code_review_benchmark/` | **第三方 judge** |
| `summary_table.py` / `analysis/benchmark_dashboard.py` | 同上 | 按 arm 聚合 + 出图骨架 |
| aider `benchmark/benchmark.py` | 需另 clone aider 主仓 | pass@k / per-exercise 隔离的参考实现 |

**要自己写的只有中间那层**：调 agent、组交接包、解析 verdict。

单 case 流程：

```
bugsinpy-checkout -v 0            # 还原到 buggy 版本
  → CC 第一版修改                  # 记录 diff、token、耗时
  → bugsinpy-test                 # 记录第一版 pass/fail
  → 按 P0..P6 构造交接包
  → codex exec --sandbox read-only --ephemeral   # 强制 JSON schema 输出 verdict
  → CC 读 verdict 修正             # 记录是否采纳、最终 diff
  → bugsinpy-test                 # 记录最终 pass/fail
  → step3-style judge 裁定缺陷真伪  # 第三方，不让 CC 自判
```

---

## 7. 定位

**已被占的坑**（不硬碰）：

| 工作 | 覆盖了什么 |
|---|---|
| Cross-Model LLM Code Review（Agentic SE @ KDD '26） | CC/Codex 互查 + 写审方向不对称 |
| Cross-Context Review（arXiv 2603.12123） | 独立上下文 review > 同上下文 self-review |

**工程先行实现**（值得抄，不是竞品）：

| 项目 | 对应场景 |
|---|---|
| [shimo4228/codex-review](https://github.com/shimo4228/codex-review) | shell-out 互查（read-only second opinion on a diff） |
| [Z-M-Huang/claude-codex](https://github.com/Z-M-Huang/claude-codex) | plugin + Codex final gate + hook 强制 |
| [AlessioZazzarini/claude-codex-collab](https://github.com/AlessioZazzarini/claude-codex-collab) | Consult + Handoff |
| [dsifry/metaswarm](https://github.com/dsifry/metaswarm) | Consensus（多 reviewer 并行 gate） |
| [SmartScope: Three Levels — SKILL.md / Plugin / Pipeline](https://smartscope.blog/en/blog/claude-code-codex-review-loop-automation-2026/) | 三种交互方式的选择建议（结论一致：先 shell 验证价值，再上 plugin） |

**我们的空白**：

1. ⭐ **交接包内容作为自变量**——没有任何工作系统研究过"给跨模型 reviewer 喂什么上下文最有效"。官方插件只喂 `last_assistant_message` 这一事实本身就是强动机。
2. **Handoff / Consult / Consensus 的量化对照**——工程实现有，**对照实验和数据没有**。

---

## 8. 下一步（严格按序）

1. **[Blocker] 取得 KDD'26 那篇 PDF**，核实写审方向的不对称结论。
2. **[Blocker] 跑 BugsInPy 难度筛选**（k=5，50-100 case）→ 黄金样本池。**只需一个薄脚本，不需要"评测框架"。**
3. 检查黄金池规模；< 20 则换数据集。
4. `Review × P0..P6` 做交接包主效应实验。
5. 扩展到 Consult / Handoff / Consensus。

---

## 9. 材料链接

- Cross-Model LLM Code Review (Agentic SE @ KDD '26): https://www.researchgate.net/publication/407032793_Cross-Model_LLM_Code_Review_Should_you_use_Claude_to_review_Codex_or_vice_versa
- Agentic SE @ KDD '26: https://agent-se.github.io/
- Cross-Context Review: https://arxiv.org/abs/2603.12123
- Anthropic Building Effective Agents（Evaluator-Optimizer）: https://www.anthropic.com/engineering/building-effective-agents
- BugsInPy: https://github.com/soarsmu/BugsInPy
- Aider Polyglot Benchmark: https://github.com/Aider-AI/polyglot-benchmark
- Martian Code Review Benchmark: https://github.com/withmartian/code-review-benchmark
