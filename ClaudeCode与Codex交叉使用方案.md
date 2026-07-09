# Claude Code 与 Codex 交叉使用方案

> 目标：打通 Claude Code 与 OpenAI Codex CLI，探索两者协同的最佳实践——什么场景用哪个、怎么互查互补，跑出数据后沉淀成团队指引。
>
> 本文档区分三类信息：**[已验证]** 本机实测确认；**[待验证]** 有来源但未实机确认；**[未证实]** 流传广但无方法论支撑，不可作为决策依据。
>
> **实测环境**：`codex-cli 0.143.0` / Windows 11 / API key 登录（按 token 计费）/ 实测日期 2026-07-09

---

## 一、三种连接方式

三者**不是三条并列的技术路线，而是三个抽象层级**。官方插件构建在 shell-out / app-server 之上，MCP 是把同一套能力压成固定 schema 的工具。选择的是抽象层级，不是路线。

### 1. Bash shell-out —— 能力天花板最高

Claude Code 用 Bash 工具直接调用 Codex 的非交互模式。

**[已验证 @ 0.143.0]** `codex exec`（别名 `codex e`）核心参数，全部经本机 `--help` 与实跑确认：

| 参数 | 说明 |
|------|------|
| `-s` / `--sandbox read-only \| workspace-write \| danger-full-access` | 评审场景**必须** `read-only` |
| `-m` / `--model` | 模型覆盖 |
| `--json` | 输出 NDJSON 事件流 |
| `-C` / `--cd <DIR>` | 设置工作目录 |
| `--output-schema <FILE>` | JSON Schema 约束结构化输出，**实测生效** |
| `-o` / `--output-last-message <FILE>` | 把最终消息单独落盘 —— **结果提取应该用这个** |
| `-c` / `--config <key=value>` | 内联配置覆盖，可重复。如 `-c model_reasoning_effort=low` |
| `--skip-git-repo-check` | 允许在非 git 目录运行 |
| `--ephemeral` | 不持久化会话 |
| 位置参数 或 stdin `-` | prompt 输入方式 |

子命令：`codex exec resume`（恢复会话）、**`codex exec review --uncommitted`**（内置代码评审）。

**[已验证] 可用模型 slug**（`codex debug models`）：

```
gpt-5.5          ← frontier，最强，推理慢
gpt-5.4
gpt-5.4-mini     ← 快，适合冒烟测试
gpt-5.3-codex
gpt-5.2
codex-auto-review
```

> ⚠️ `/santa-loop` 里写死的 `-m gpt-5.4` **是有效模型名**，但已非最强。评审场景应改用 `gpt-5.5`。

反方向（Codex 调 Claude）用 `claude -p "<prompt>" --output-format json`，机制对称，但生态成熟度低得多。

**特征**：一次性 RPC，进程级上下文隔离，全部参数你说了算。

**代价**：prompt 拼装、临时文件管理、结果解析都得自己写。

---

### ⚠️ 关键实测发现：Windows 沙箱不可用，必须「推」上下文而非「拉」

**[已验证]** 在本机 `--sandbox read-only` 下，Codex 起子进程读文件时被系统拒绝：

```
ERROR codex_core::exec: exec error: windows sandbox:
      CreateProcessWithLogonW failed: 1385
```

`1385 = ERROR_LOGON_TYPE_NOT_GRANTED`——当前账户缺少 "Log on as a batch job" 权限。Codex 连续 4 次尝试用不同方式起 PowerShell，全部失败。

**危险之处在于它不报错退出，而是返回一个格式完全合法的 verdict：**

```json
{"verdict":"FAIL","critical_issues":["Unable to inspect target.py ..."]}
```

Schema 通过，`turn.completed` 正常，退出码 0。**跑在自动化流水线里，你会得到「Codex 判定 FAIL」，而真实原因是它压根没读到代码。** 这是会毒化整个跨模型实验的静默故障。

#### 解法：Push 上下文，不要让 Codex 去 Pull

把待审内容直接从 **stdin 灌进 prompt**，并明确禁止工具调用：

```bash
{
  echo "Review the code below. Criteria: ..."
  echo "Do NOT run any commands or read any files; everything you need is inline."
  echo
  echo '```python'; cat target.py; echo '```'
} > prompt.txt

codex exec --sandbox read-only --skip-git-repo-check \
  -m gpt-5.5 \
  --output-schema verdict.schema.json \
  -o result.json \
  - < prompt.txt
```

**实测对比**（同一段代码、同一 rubric）：

| 方式 | tokens | 结果 |
|------|--------|------|
| 让 Codex 自己读文件 | 34,720 | ❌ 假 FAIL，无有效发现 |
| stdin 推入 | **6,634** | ✅ 3 条真实发现（null 安全、price 未校验、边界处理） |

**便宜 5 倍，且更快**（无失败的工具调用往返）。

而且——**即使没有这个 Windows bug，push 也是正确架构**：
- 双评审必须看到**逐字节相同**的输入，这是 Santa Method 的硬性不变量。让两个模型各自去 `cat` 文件，你无法保证它们读到了同样的东西
- 无工具调用 = 无不确定性，可复现
- 成本可预测

> 若确实需要 Codex 自主探索仓库（如案例 D 的救援场景），需给账户授予 "Log on as a batch job" 权限（需管理员），或改在 WSL 中运行。**评审场景不需要。**

#### 结果提取

`--json` 事件流里 final message 会出现两次（`item.completed` 中一次、末尾再一次），`tail -1` 很脆。用 `-o result.json` 直接落盘。

---

### 2. MCP (`codex mcp-server`) —— 唯一支持多轮会话

**[已验证]** `codex mcp-server` 把 Codex 自身作为 MCP server 跑在 stdio JSON-RPC 上，供 Claude Code 等客户端连接。暴露两个工具：

- `codex()` —— 开启一轮新会话
- `codex-reply()` —— 延续已有会话

**关键区别**：这是三种方式里**唯一能跨多次调用保持 Codex 会话状态**的。适合"来回讨论"而非"一问一答"。

⚠️ 注意区分：`codex mcp`（管理 Codex 作为**客户端**连接的 server 配置，写入 `~/.codex/config.toml`）与 `codex mcp-server`（把 Codex 变成**服务端**）。两者常被混为一谈。

**特征**：模型自主决定调用时机；结果直接回流进 CC 主上下文。

**代价**：**破坏可观测性与上下文隔离**——详见"已知坑"。

---

### 3. 官方插件 `openai/codex-plugin-cc` —— 上手最快

**[待验证]** OpenAI 官方维护的 Claude Code 插件，调用本机 codex 二进制。提供命令：`/codex:review`、`/codex:adversarial-review`、`/codex:rescue`、`/codex:transfer`、`/codex:status`、`/codex:result`、`/codex:cancel`、`/codex:setup`。

前置：Node ≥ 18.18、`npm install -g @openai/codex`、`codex login`。

其 README 自己警告 fan-out "may drain usage limits quickly"。

**特征**：命令确定、开箱即用，但能力被限定在官方封装的那几条命令内，内部实现不透明。

---

### 三者对比

| | 能力天花板 | 确定性 | 会话延续 | 上下文隔离 | 上手成本 |
|---|---|---|---|---|---|
| Bash shell-out | 完整 CLI 参数面 | 脚本写死，完全可控 | ✗ | ✓ 进程级 | 高 |
| `codex mcp-server` | 固定 tool schema | 模型自主决定 | ✓ | ✗ 结果回流主上下文 | 中 |
| `codex-plugin-cc` | 官方封装的命令集 | 命令确定，内部不透明 | 部分 | 视命令而定 | 低 |

---

## 二、三种协作形状

连接方式不是研究变量，**它们解锁的协作形状才是**。每种通道天然对应一类协作：

| 形状 | 通道 | 语义 | 触发者 |
|------|------|------|--------|
| **互查 Review** | shell-out | 给你产物，还我 verdict。双方互不知情 | 脚本 |
| **互问 Consult** | MCP | 干活干到一半卡住，随手问一句 | 模型自己 |
| **互接 Handoff** | 插件 `transfer` / `rescue` | 整个任务连同上下文交给对方接手 | 人 |

要沉淀完整的协同指引，三格都得填。santa-loop 只覆盖了第一格。

---

## 三、工程级交叉使用案例

### 案例 A：PR 门禁 —— 对抗式双审（互查 / shell-out）

最成熟、收益最容易验证的场景。

```
Claude 写代码
  → git diff 提取变更
  → 并行发两个独立评审：
      Reviewer A = Claude Opus subagent
      Reviewer B = codex exec --sandbox read-only --output-schema verdict.json
  → 双 PASS 才放行；任一 FAIL → 修复 → 换全新评审重跑
  → 封顶 3 轮，仍不过则转人审
```

要点：
- `--sandbox read-only` 是硬约束，评审者不得改仓库
- `--output-schema` 强制结构化 verdict，不要解析自然语言
- 每轮换**全新**评审进程，避免锚定偏差
- **记录两个评审的问题重合率**——这是判断"跨模型到底有没有增量"的核心指标

本地 `ecs` plugin 的 `/santa-loop` 已实现此形状，但有两个必须先修的问题（见"已知坑"）。

---

### 案例 B：测试资产交叉评审（互查 / shell-out）—— 本项目最高价值切入点

本机 `ecs-qa` plugin 里的 `test-case-review`、`test-scheme-review` 已经在做「多 agent 并行 → 汇总去重 → 按严重程度排序 → 标注来源 agent」。

**它的架构已经完全就位，只是所有 agent 都是 Claude。**

改造成本极低：把并行评审 agent 池里替换/新增一个 Codex 评审者，复用现有的 rubric、汇总、去重逻辑。

为什么这个场景特别适合做跨模型：
- 测试用例覆盖度是**枚举型**任务——漏掉的边界条件是客观事实，不是风格偏好，`FAIL` 可判定
- 汇总环节天然产出"哪个 agent 独家发现了什么"，重合率数据自动落盘
- 产出物是文档而非代码，评审无需执行环境，成本低

---

### 案例 C：不确定语义的第二意见（互问 / MCP）

Claude 写代码时撞上不确定的东西——正则边界、SQL 隔离级别、并发内存序、某个 API 的确切语义——自己决定去问一句 Codex。

**前置条件**：你得先知道 Codex 强在哪儿，模型才知道该问什么。所以这个形状**必须放在案例 A/B 之后做**，不能一上来就开。

---

### 案例 D：死循环救援（互接 / 插件）

Claude 在同一个 bug 上反复修反复失败（典型信号：连续 3 轮 fix 后测试仍红，且失败原因在漂移），或长任务上下文即将耗尽。

用 `/codex:transfer` 把任务连同上下文交给 Codex 接手。

**工程要点**：交接面用**磁盘文件**（`spec.md` / `plan.md` / diff 包），不要依赖共享 session。社区项目 `formin/multi-model-review` 正是为绕开共享 session 的上下文丢失问题才这么设计的。

---

## 四、已知坑

### 坑 0：Windows 沙箱静默产出假 FAIL **[已验证，本机复现]**

见第一节。`CreateProcessWithLogonW failed: 1385` 导致 Codex 读不到任何文件，却返回 schema 合规的 `FAIL`。

**这是本项目当前最高优先级的正确性风险**——它会让"Codex 比 Claude 更严格"这类结论完全失真。

**对策**：一律 push 上下文（stdin），prompt 中明确禁止工具调用。

### 坑 1：MCP 会静默污染你的观测

一旦挂上 `codex mcp-server`，Codex 就出现在 CC 的工具列表里，模型**可能在你没打算让它问的时候自己去问**。你以为在测"CC 单独写代码的基线"，实际它中途咨询了 Codex 三次，而日志里并不显眼。

**对策**：分阶段启用，一次只挂一种通道。需要同开时用 `--allowedTools` 在特定 session 里关掉 MCP 工具。

### 坑 2：`/santa-loop` 会静默降级

检测不到 `codex` / `gemini` 时，Reviewer B 会 fallback 成第二个 Claude Opus。文档标了 "true model diversity was not achieved"，但**那只是一行日志**。

**结果**：你以为在做跨模型评审，实际在做上下文隔离评审——而这恰好是下面"坑 4"那个混淆变量。

**现状**：codex 已装（0.143.0），当前不会触发降级。但它同时依赖 Codex 自主读文件，会撞上坑 0。

**对策**：把降级从「警告」改成「硬失败」；把 Reviewer B 改成 push 上下文模式；`-m gpt-5.4` → `gpt-5.5`。

### 坑 3：`/santa-loop` 双 PASS 后会 `git push -u origin HEAD`

自动推送。用之前先拆掉这行。

### 坑 4：「跨模型」与「上下文隔离」是两个变量，普遍被混为一谈

santa-method 的核心论证是：*单个 agent 审自己的输出，用的是生产该输出的同一套偏见与知识缺口。*

**这句话论证的是「上下文隔离」的必要性，不是「模型多样性」的必要性。**

**[未证实]** arXiv 2603.12123 "Cross-Context Review" 用**同一模型**在分离 session 里互审，同样报告了收益。这暗示归因给"跨模型"的好处，可能相当一部分来自角色/上下文分离本身。

**对策**：任何声称"跨模型更强"的实验，必须有「同模型 + 隔离 session」对照组。

### 坑 5：对抗式 prompt 会制造人为抬杠

"你的任务是找问题，不是批准" 能压制 rubber-stamping，同时会产出噪音发现。Mozilla.ai 的 Star Chamber 因此明确把自己定位成 **advisory 而非 blocking**。

**对策**：区分 `critical_issues`（阻塞）与 `suggestions`（非阻塞），只让前者触发修复循环。

### 坑 6：成本与分歧死锁

官方插件自己承认会快速耗尽额度。Star Chamber 的文档直接承认 debate 模式下"没有机制能阻止无限分歧循环"。

**对策**：硬性轮数上限 + 转人审。批量场景用分层抽样而非全量验证。

---

## 五、关于「效果提升」的证据现状

**这一节必须读，否则容易基于假数据做决策。**

**[未证实]** 广泛流传的数字——"跨模型多抓 40–60% 问题"、"resolution rate 76%"、"issue 数翻倍"——溯源全部指向无方法论、无样本量、无原始数据的内容营销博客。OpenAI 官方"消除阿谀偏见 (eliminates sycophancy bias)"是厂商文案，非独立测量。

**[待验证]** 最扎实的公开 benchmark 是 Factory.ai 的 code review 评测（13 模型 × 50 个真实 PR × 人工 golden bug 集），但它测的是**「哪个单模型审得最好」**，不是「跨模型比自审好多少」——回答的是隔壁问题。

**[未证实]** arXiv 2603.03406 "Review Beats Planning" 方向上支持 review 式双模型优于前置 planning 式，但数值表格未能提取核实。

**结论**：跨模型评审的**理论动机成立**（不同训练数据 → 不同盲点），但"提升多少"目前**没有可复现的公开测量**。

> **要在团队推这件事，唯一诚实的做法是自己测，而不是引用别人的数字。**

---

## 六、落地路线

按「信息增益 / 成本比」递减排序：

### 阶段 0：环境就绪 ✅ **已完成**

```bash
codex --version        # codex-cli 0.143.0 ✅
codex login status     # Logged in using an API key ✅（按 token 计费，注意成本）
codex debug models     # gpt-5.5 / 5.4 / 5.4-mini / 5.3-codex / 5.2 ✅
```

冒烟测试已通过（stdin 推入 + `--output-schema`，6,634 tokens 拿到 3 条真实发现）。

**遗留**：Windows 沙箱不可用（坑 0），已用 push 模式绕过。`codex mcp-server` 尚未实机验证。

### 阶段 1：插件试水（半天）
装 `codex-plugin-cc`，跑 `/codex:review` 与 `/codex:adversarial-review`。

**唯一要回答的问题**：Codex 的评审意见，是「确实抓到了 Claude 漏的东西」还是「一堆风格抬杠」？

这个答案决定整个方向值不值得继续投入。若是后者，停下来重新想。

### 阶段 2：shell-out 固化（主力工作台）
把评审固化成可重复脚本：`--sandbox read-only` + `--output-schema` + 结构化 verdict 落盘。

优先接入 **案例 B**（ecs-qa 测试资产评审）——改造成本最低，可判定性最强。

### 阶段 3：MCP 接入（最后）
只有在已知 Codex 强项之后才有意义，且必须先解决坑 1 的观测污染问题。

---

## 七、沉淀指引需要的数据

**指引的质量 = 观察条数 × 记录质量。** 跑 5 条就下结论，产出物和那些内容农场博客没有区别。

每次跨模型调用记录：

| 字段 | 说明 |
|------|------|
| 任务类型 | 代码 / 测试用例 / 测试方案 / 文档 |
| 角色分配 | 谁生成、谁评审 |
| 发现列表 | 各评审者独立产出 |
| **重合率** | 两方都标出的问题 / 全部问题 —— **最关键指标** |
| 真阳性判定 | 该发现是真 bug 还是噪音（人工裁定） |
| 修复后回归 | 修完是否引入新问题 |
| 成本 | token / 时长 |

**重合率的解读**：
- **高重合** → 模型多样性没带来增量，钱白花了
- **低重合 + 高真阳性** → 真正互补，方向成立
- **低重合 + 低真阳性** → rubric 太松，两边都在自由发挥

目标样本量：**20–30 条**起，规律才会浮出来。

---

## 附：参考来源

- [Codex CLI 命令行参考](https://developers.openai.com/codex/cli/reference) —— exec 参数、`mcp-server` 子命令 **[已验证]**
- [openai/codex — docs/exec.md](https://github.com/openai/codex/blob/main/docs/exec.md)
- [Codex MCP 文档](https://developers.openai.com/codex/mcp)
- [codex-mcp-server 实现说明 (DeepWiki)](https://deepwiki.com/openai/codex/6.4-mcp-server-implementation-(codex-mcp-server)) —— `codex()` / `codex-reply()` 两工具
- [Claude Code Headless Mode](https://code.claude.com/docs/en/headless)
- [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) **[待验证]**
- [Mozilla.ai — The Star Chamber](https://blog.mozilla.ai/the-star-chamber-multi-llm-consensus-for-code-quality/)
- [Factory.ai — Which Model Reviews Code Best?](https://factory.ai/news/code-review-benchmark)
- [formin/multi-model-review](https://github.com/formin/multi-model-review) —— 文件交接式跨模型
- 本机 `ecs` plugin：`~/.claude/plugins/cache/ecs/ecs/0.8.14/commands/santa-{loop,method}.md`

