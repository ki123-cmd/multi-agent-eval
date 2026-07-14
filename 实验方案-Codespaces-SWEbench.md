# 实验方案：Codespaces + SWE-bench Verified

更新日期：2026-07-14

## 结论

**环境**：GitHub Codespaces（16核/64GB/128GB）
**数据集**：SWE-bench Verified，**按 repo 分批**跑
**交互方式**：shell-out（`codex exec`）
**目标**：端到端 resolve rate —— CC 拿 Codex 的 review 改完后，测试通过率提升多少

---

## 为什么是这套

| 约束 | 结论 |
|---|---|
| 本机内存仅 15.7GB（SWE-bench 要 16GB） | 本地跑不了，VirtualBox 也救不了 |
| 无 Docker / 无 WSL / 可能无管理员权限 | Codespaces 全部绕开：不碰公司电脑、自带 Docker |
| SWE-bench 要 120GB 磁盘 | **磁盘只取决于用到几个环境镜像，不是 instance 条数**——按 repo 分批 + 跑完清理，128GB 够用 |

已排除：BugsInPy（Windows 上 `nose` 装不上、CRLF 破坏 patch，实测失败）、Polyglot（84% 通过、77% 触顶）、HumanEvalFix（HumanEval 已饱和 96-98%）、Martian/CodeReviewer（无可执行测试，测不出端到端）。

---

## 核心设计：配对分支

**每个 instance 只让 CC 写一次第一版 patch，冻结它，所有 payload 臂从同一份 patch 分叉。**

```
CC 第一版 patch（跑一次，冻结）
  ├── CC-only（不审，直接交）        ← 基线
  ├── P0 → codex 审 → CC 改 → 评测
  ├── P1 → codex 审 → CC 改 → 评测
  └── ...
```

各臂起点字节级相同 → 唯一变化的是 **Codex 看到了什么** → 可用配对检验（McNemar），样本量需求大幅降低。

### Payload（自变量）

| 代号 | 内容 |
|---|---|
| `P0` | 只给 CC 的自然语言说明，**不给 diff**（= 官方 Codex 插件的真实行为） |
| `P1` | 只给 diff |
| `P2` | diff + issue statement |
| `P3` | diff + issue + 被改文件全文 |
| `P4` | diff + issue + **测试执行结果** |
| `P5` | P4 + CC 自陈的不确定点 |

### 必须做的控制

1. **⚠️ 工作目录隔离**——`codex exec` 会自己读仓库。必须给它一个只含本臂 payload 的临时目录，仓库不可达。**不做这条，P1/P2/P3 会全部塌成同一个臂。**
2. **长度对照臂**——同 token 量但填无关内容，排除"只是上下文更长"。
3. **prompt 模板冻死**——只有 `{{PAYLOAD}}` 槽位变，指令和输出 schema 一字不改。
4. **Codex 重复 m≥3 次**——消掉它自身的抖动。
5. **基础设施故障不进分母**——超时/崩溃单独记账，不能和"没修好"混同。

---

## 执行流程

**第 0 步：把 `D:\multi-agent` 推成 GitHub 私有仓库**

**第 1 步：开 Codespace，验证链路（10 条）**
- `devcontainer.json` 加 `docker-in-docker` feature
- `pip install swebench`
- 用 `--instance_ids` 只跑 10 条（集中在少数 repo → 只构建少量镜像 → 10-30GB）
- 先用 `--predictions_path gold` 冒烟：确认 golden patch 能评测通过
- 装 `claude` / `codex` CLI，API key 走 Codespaces secrets

**第 2 步：难度筛选**
- 候选池 100-200 条，跑 CC-only × k=3
- 保留 pass rate 在 **1/3 ~ 2/3** 的黄金样本（全过=天花板，全败=地板，都无区分度）
- 目标黄金池 **30-50 条**；不足则扩候选池

**第 3 步：主实验（配对分支）**
- 冻结第一版 patch → 六个 payload 臂分叉 → `codex exec` 审 → CC 改 → 评测
- 主指标：各臂 resolve rate vs CC-only 基线，配对检验

**第 4 步：分析**
- 主效应：哪个 payload 带来显著提升
- 关键对照：`P0`（插件现状）vs `P4/P5`（带执行证据）

---

## 磁盘与成本控制

- **按 repo 分批**：同 repo+version 的 instance 共用一个环境镜像
- `cache_level=env`（**绝不用 `instance`，那要 2TB**），每批跑完清理
- Codespaces 闲置 30 分钟自动停机 → 长任务用 `nohup` 后台跑
- 免费额度 120 核·小时/月（**组织账户无免费额度**）；16核约 $1.44/小时
- 真正的开销是 agent 调用，不是机器

---

## 已知风险

- **写审方向**：KDD'26 那篇称 `CC写 + Codex审` 是劣势方向（91.4%→82.8%），但数字未经核实。需取得 PDF 或自己 pilot 验证，无论如何要在论文里声明。
- **新颖性收窄**：AACR-Bench 已证明"repo-level 上下文优于 diff-only"。我们剩下的空白是**协作特有的 payload**（`P0` 写者的自然语言、`P5` 写者自陈的不确定点）——这些在单模型 ACR 里不存在。
