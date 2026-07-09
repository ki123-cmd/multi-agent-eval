# review-package

从真实 PR 构造逐字节可复现的评审输入包。所有实验臂必须看到**完全相同**的输入，否则重合率与召回率之间无法归因。

## ADDED Requirements

### Requirement: 输入字节一致性
同一 item 的 package MUST 由 sha256 锚定，且所有臂 MUST 消费同一个 package 文件。

#### Scenario: 多臂消费同一 package
- **WHEN** 实验对某 item 运行 N 个臂
- **THEN** 每个臂读取的 package 内容 sha256 MUST 相同
- **AND** 该 sha256 MUST 随每条结果一同落盘

### Requirement: 上下文以 push 方式提供
package 的全部内容 MUST 通过 stdin 灌入评审者进程，prompt MUST 明确禁止工具调用。

#### Scenario: 构造 package
- **WHEN** 给定一个公开 PR 的 diff
- **THEN** package MUST 内联完整 diff、任务描述与评审 rubric
- **AND** package MUST 记录 `first_changed_file` 与 `changed_file_count` 作为 canary 期望值

### Requirement: 超长 diff 的显式处理
系统 MUST NOT 静默截断 diff。

#### Scenario: diff 超出预算
- **WHEN** diff 字节数超过配置上限
- **THEN** 该 item MUST 被跳过并记入 `skipped` 列表
- **AND** 系统 MUST NOT 仅截断后继续评审
