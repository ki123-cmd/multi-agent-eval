# verdict-validation

把评审者的静默故障转为硬失败。这是整个实验可信度的前提：本机已实测 Codex 在沙箱下读不到文件却仍返回 schema 合规的 `FAIL`。

## ADDED Requirements

### Requirement: Canary 校验
每份 verdict MUST 包含 `canary` 对象，其中 `first_changed_file` 与 `changed_file_count` 只能从 pushed 的 diff 中得出。系统 MUST 将其与 package 元数据比对。

#### Scenario: 评审者真实读到了输入
- **WHEN** verdict 的 `canary` 与 package 元数据完全一致
- **THEN** 该运行标记为 `VALID`，进入指标统计

#### Scenario: 评审者未读到输入（静默故障）
- **WHEN** `canary` 与 package 元数据不一致，或 `canary` 缺失
- **THEN** 该运行标记为 `INVALID`，MUST NOT 计入任何指标
- **AND** 系统 MUST 记录原始输出以供事后诊断

### Requirement: Schema 校验
verdict MUST 通过 `harness/schema/verdict.schema.json` 校验。

#### Scenario: 输出不合 schema
- **WHEN** 评审者返回的 JSON 不满足 schema
- **THEN** 该运行标记为 `INVALID`，并记录 schema 错误路径

### Requirement: 禁止自读文件的评审路径
系统 MUST NOT 调用任何依赖评审者自主读取工作区的命令。

#### Scenario: 试图使用 Codex 自读模式
- **WHEN** 配置要求 Codex 以 `--sandbox danger-full-access` 或 `codex exec review` 运行
- **THEN** harness MUST 拒绝启动并报错
