## 1. 环境与真值集

- [x] 1.1 重建 `.git`（原为空目录，`git diff` 链路不通）
- [x] 1.2 `openspec init --tools claude,codex`
- [x] 1.3 实测三种 sandbox 模式下 Codex 的文件读取能力
- [x] 1.4 clone `withmartian/code-review-benchmark`，确认 136 条 golden comments

## 2. Harness 实现

- [x] 2.1 `harness/schema/verdict.schema.json`（含 canary）
- [x] 2.2 `harness/package.py`：构造 package + sha256 + canary 期望值
- [x] 2.3 `harness/reviewers.py`：codex / claude 对称适配器
- [x] 2.4 `harness/validate.py`：schema + canary 校验，静默故障转硬失败
- [x] 2.5 `harness/judge.py`：第三方裁判做 finding→golden 语义匹配
- [x] 2.6 `harness/run.py`：多臂编排、重复采样、指标落盘

## 3. 验证

- [x] 3.1 负向测试：故意让评审者读不到 diff，确认被判 `INVALID` 而非假 FAIL
- [x] 3.2 试点运行：小样本跑通全链路，产出真实指标
- [x] 3.3 估计 `p_disc`（≈0.5，n=4）→ 正式实验需 ~102–140 item
- [ ] 3.4 采集 Codex 侧 token / 成本（`-o` 不含用量，须解析 `--json` 事件流）
- [ ] 3.5 正式运行：136 item × 臂 × 重复 8 次
- [ ] 3.6 人工抽检 10–20% 裁判判定，报告 Cohen's κ
- [ ] 3.7 第二批：抽取知识截止日（2026-01）之后的新 PR，对比 TPR 以量化记忆污染

## 4. 场景扩展（Review 之后）

- [ ] 4.1 互补 Consult（MCP）——必须先解决可观测性污染
- [ ] 4.2 互接 Handoff（文件化交接）
- [ ] 4.3 主从式 Orchestrator-Worker
- [ ] 4.4 功能实现类任务（非 bug-fix），真值集待定
